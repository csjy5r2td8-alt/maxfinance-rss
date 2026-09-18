#!/usr/bin/env python3
"""Deteta alterações nas taxas Euribor e abre uma Issue no GitHub."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SOURCE_URL = "https://www.euribor-rates.eu/pt/taxas-euribor-actuais/"
STATE_FILE = Path("euribor_alerta_github_estado.json")
TERMS = ("1 semana", "1 mês", "3 meses", "6 meses", "12 meses")
MARKER_PREFIX = "euribor-change-event:"


def make_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (compatible; Maxfinance-Euribor-Monitor/2.0)"}
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def to_float(text: str) -> float | None:
    match = re.search(r"(-?\d+)[.,](\d+)", text)
    if not match:
        return None
    sign = -1 if match.group(1).startswith("-") else 1
    whole = match.group(1).lstrip("-")
    return sign * float(f"{whole}.{match.group(2)}")


def fetch_rates(session: requests.Session) -> tuple[str, dict[str, float]]:
    logging.info("A consultar as taxas Euribor: %s", SOURCE_URL)
    response = session.get(SOURCE_URL, timeout=45)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    latest_date = "Data não indicada"
    rates: dict[str, float] = {}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = rows[0].find_all(["th", "td"])
        dates = [cell.get_text(strip=True) for cell in header[1:]]
        dates = [date for date in dates if re.search(r"\d{2}/\d{2}/\d{4}", date)]
        if not dates:
            continue
        latest_date = dates[0]

        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True)
            term = next((candidate for candidate in TERMS if candidate in label), None)
            if not term:
                continue
            value = to_float(cells[1].get_text(" ", strip=True))
            if value is not None:
                rates[term] = value
        if rates:
            break

    missing = [term for term in TERMS if term not in rates]
    if missing:
        raise RuntimeError(f"Não foram encontradas taxas para: {', '.join(missing)}.")
    logging.info("Foram encontradas %s taxas, com data %s.", len(rates), latest_date)
    for term in TERMS:
        logging.info("Euribor %s: %.3f%%", term, rates[term])
    return latest_date, rates


def load_state() -> dict[str, Any] | None:
    if not STATE_FILE.exists():
        return None
    with STATE_FILE.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state.get("taxas"), dict):
        raise ValueError(f"Formato inválido em {STATE_FILE}.")
    return state


def save_state(source_date: str, rates: dict[str, float]) -> None:
    state = {
        "data": source_date,
        "verificado_em": datetime.now(timezone.utc).isoformat(),
        "taxas": rates,
    }
    temporary = STATE_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(STATE_FILE)


def find_changes(old: dict[str, Any], new: dict[str, float]) -> list[dict[str, Any]]:
    changes = []
    for term in TERMS:
        old_value = old.get(term)
        new_value = new[term]
        if old_value is None or abs(float(old_value) - new_value) > 0.0005:
            changes.append(
                {"term": term, "old": None if old_value is None else float(old_value), "new": new_value}
            )
    return changes


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def event_id(old_state: dict[str, Any], new_rates: dict[str, float]) -> str:
    material = json.dumps(
        {"old": old_state, "new": new_rates},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def marker(identifier: str) -> str:
    return f"<!-- {MARKER_PREFIX}{identifier} -->"


def issue_exists(
    session: requests.Session, repository: str, token: str, identifier: str
) -> bool:
    expected = marker(identifier)
    page = 1
    while True:
        response = session.get(
            f"https://api.github.com/repos/{repository}/issues",
            headers=github_headers(token),
            params={"state": "all", "per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        issues = response.json()
        if any(expected in (issue.get("body") or "") for issue in issues):
            return True
        if len(issues) < 100:
            return False
        page += 1


def format_rate(value: float | None) -> str:
    return "não registada" if value is None else f"{value:.3f}%"


def create_issue(
    session: requests.Session,
    repository: str,
    token: str,
    source_date: str,
    rates: dict[str, float],
    changes: list[dict[str, Any]],
    identifier: str,
) -> str:
    rows = []
    for change in changes:
        difference = "—" if change["old"] is None else f"{change['new'] - change['old']:+.3f} p.p."
        rows.append(
            f"| {change['term']} | {format_rate(change['old'])} | "
            f"{format_rate(change['new'])} | {difference} |"
        )
    current_rows = [f"| {term} | {rates[term]:.3f}% |" for term in TERMS]
    body = f"""Foram detetadas alterações nas taxas Euribor.

## Taxas alteradas

| Prazo | Valor anterior | Novo valor | Variação |
|---|---:|---:|---:|
{chr(10).join(rows)}

## Taxas atuais

| Prazo | Taxa |
|---|---:|
{chr(10).join(current_rows)}

- **Data indicada na fonte:** {source_date}
- **Fonte:** [Taxas Euribor atuais]({SOURCE_URL})

{marker(identifier)}
"""
    owner = repository.split("/", maxsplit=1)[0]
    response = session.post(
        f"https://api.github.com/repos/{repository}/issues",
        headers=github_headers(token),
        json={
            "title": "Alteração nas taxas Euribor",
            "body": body,
            "assignees": [owner],
        },
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["html_url"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    session = make_session()
    source_date, rates = fetch_rates(session)
    state = load_state()

    if state is None:
        logging.info("Primeira execução: as taxas atuais serão a referência inicial.")
        save_state(source_date, rates)
        logging.info("Nenhuma Issue ou notificação foi criada.")
        return 0

    changes = find_changes(state["taxas"], rates)
    if not changes:
        logging.info("Nenhuma taxa mudou. Nenhuma Issue ou notificação foi criada.")
        return 0

    logging.info("Foram detetadas %s alterações:", len(changes))
    for change in changes:
        logging.info(
            "Euribor %s: %s -> %.3f%%",
            change["term"],
            format_rate(change["old"]),
            change["new"],
        )

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN e GITHUB_REPOSITORY são obrigatórios.")

    identifier = event_id(state, rates)
    if issue_exists(session, repository, token, identifier):
        logging.info("A Issue desta alteração já existe; duplicado evitado.")
    else:
        url = create_issue(
            session, repository, token, source_date, rates, changes, identifier
        )
        logging.info("Issue criada e atribuída ao proprietário: %s", url)

    save_state(source_date, rates)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("A monitorização da Euribor falhou.")
        raise SystemExit(1)
