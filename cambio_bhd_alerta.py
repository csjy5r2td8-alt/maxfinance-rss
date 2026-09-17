#!/usr/bin/env python3
"""Monitoriza as taxas de câmbio do BHD e abre uma Issue quando mudam."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_URL = "https://backend.bhd.com.do/api/modal-cambio-rate?populate=deep"
PAGE_URL = "https://bhd.com.do/homepage-personal"
DEFAULT_STATE_FILE = Path("cambio_bhd_alerta_estado.json")
CURRENCIES = ("USD", "EUR")
RATE_LABELS = {"compra": "Compra", "venda": "Venda"}
ISSUE_MARKER_PREFIX = "bhd-rate-change-id:"


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
        {
            "User-Agent": (
                "Mozilla/5.0 (compatible; Maxfinance-BHD-Monitor/2.0; "
                "+https://github.com/)"
            )
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_rates(session: requests.Session) -> dict[str, dict[str, float]]:
    logging.info("A consultar as taxas de câmbio do BHD: %s", API_URL)
    response = session.get(API_URL, timeout=45)
    response.raise_for_status()
    payload = response.json()

    try:
        rows = payload["data"]["attributes"]["exchangeRates"]
    except (KeyError, TypeError) as error:
        raise RuntimeError("A resposta do BHD não contém 'exchangeRates'.") from error

    rates: dict[str, dict[str, float]] = {}
    for row in rows:
        currency = str(row.get("currency", "")).upper().strip()
        if currency not in CURRENCIES:
            continue
        try:
            rates[currency] = {
                "compra": float(row["buyingRate"]),
                "venda": float(row["sellingRate"]),
            }
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(f"Taxas inválidas para {currency}.") from error

    missing = [currency for currency in CURRENCIES if currency not in rates]
    if missing:
        raise RuntimeError(f"O BHD não devolveu as taxas de: {', '.join(missing)}.")

    logging.info("Foram encontradas %s moedas e 4 taxas.", len(rates))
    for currency in CURRENCIES:
        logging.info(
            "%s — compra: %.2f DOP | venda: %.2f DOP",
            currency,
            rates[currency]["compra"],
            rates[currency]["venda"],
        )
    return rates


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state.get("taxas"), dict):
        raise ValueError(f"Formato inválido em {path}: falta o objeto 'taxas'.")
    return state


def save_state(path: Path, rates: dict[str, dict[str, float]], checked_at: str) -> None:
    state = {"data": checked_at, "taxas": rates}
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def find_changes(
    old_rates: dict[str, Any], new_rates: dict[str, dict[str, float]]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for currency in CURRENCIES:
        old_currency = old_rates.get(currency, {})
        for rate_name in RATE_LABELS:
            old_value = old_currency.get(rate_name)
            new_value = new_rates[currency][rate_name]
            if old_value is None or abs(float(old_value) - new_value) > 0.0001:
                changes.append(
                    {
                        "currency": currency,
                        "rate_name": rate_name,
                        "old": None if old_value is None else float(old_value),
                        "new": new_value,
                    }
                )
    return changes


def change_id(old_state: dict[str, Any], new_rates: dict[str, Any]) -> str:
    material = json.dumps(
        {"old": old_state, "new": new_rates},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def issue_marker(event_id: str) -> str:
    return f"<!-- {ISSUE_MARKER_PREFIX}{event_id} -->"


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def issue_already_exists(
    session: requests.Session, repository: str, token: str, event_id: str
) -> bool:
    marker = issue_marker(event_id)
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
        if any(marker in (issue.get("body") or "") for issue in issues):
            return True
        if len(issues) < 100:
            return False
        page += 1


def format_value(value: float | None) -> str:
    return "não registada" if value is None else f"{value:.2f} DOP"


def create_issue(
    session: requests.Session,
    repository: str,
    token: str,
    changes: list[dict[str, Any]],
    current_rates: dict[str, dict[str, float]],
    observed_at: datetime,
    event_id: str,
) -> str:
    changed_currencies = ", ".join(
        currency
        for currency in CURRENCIES
        if any(change["currency"] == currency for change in changes)
    )
    table_rows = []
    for change in changes:
        difference = "—"
        if change["old"] is not None:
            difference = f"{change['new'] - change['old']:+.2f} DOP"
        table_rows.append(
            "| {currency} | {rate} | {old} | {new} | {difference} |".format(
                currency=change["currency"],
                rate=RATE_LABELS[change["rate_name"]],
                old=format_value(change["old"]),
                new=format_value(change["new"]),
                difference=difference,
            )
        )

    current_rows = [
        f"| {currency} | {current_rates[currency]['compra']:.2f} DOP | "
        f"{current_rates[currency]['venda']:.2f} DOP |"
        for currency in CURRENCIES
    ]
    local_time = observed_at.astimezone(ZoneInfo("America/Santo_Domingo"))
    body = f"""Foi detetada uma alteração nas taxas publicadas pelo Banco BHD.

## Taxas alteradas

| Moeda | Operação | Valor anterior | Novo valor | Variação |
|---|---|---:|---:|---:|
{chr(10).join(table_rows)}

## Taxas atuais

| Moeda | Compra | Venda |
|---|---:|---:|
{chr(10).join(current_rows)}

- **Detetado em:** {local_time:%d/%m/%Y às %H:%M} (hora da República Dominicana)
- **Fonte:** [Página pessoal do Banco BHD]({PAGE_URL})

{issue_marker(event_id)}
"""
    owner = repository.split("/", maxsplit=1)[0]
    response = session.post(
        f"https://api.github.com/repos/{repository}/issues",
        headers=github_headers(token),
        json={
            "title": f"Alteração no câmbio BHD — {changed_currencies}",
            "body": body,
            "assignees": [owner],
        },
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["html_url"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o resultado sem criar Issue nem alterar o estado.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    session = make_session()
    current_rates = fetch_rates(session)
    previous_state = load_state(args.state_file)
    now = datetime.now(timezone.utc)

    if previous_state is None:
        logging.info("Ainda não existe histórico; as taxas atuais serão a referência inicial.")
        if not args.dry_run:
            save_state(args.state_file, current_rates, now.isoformat())
        logging.info("Nenhuma notificação foi criada na primeira execução.")
        return 0

    changes = find_changes(previous_state["taxas"], current_rates)
    if not changes:
        logging.info("Nenhuma alteração detetada. Nenhuma Issue ou notificação foi criada.")
        return 0

    logging.info("Foram detetadas %s alterações:", len(changes))
    for change in changes:
        logging.info(
            "%s %s: %s -> %.2f DOP",
            change["currency"],
            RATE_LABELS[change["rate_name"]],
            format_value(change["old"]),
            change["new"],
        )

    if args.dry_run:
        logging.info("Modo de teste: não foi criada Issue nem alterado o estado.")
        return 0

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN e GITHUB_REPOSITORY são obrigatórios quando há alteração.")

    event_id = change_id(previous_state, current_rates)
    if issue_already_exists(session, repository, token, event_id):
        logging.info("A Issue desta alteração já existe; não será criada uma duplicada.")
    else:
        issue_url = create_issue(
            session, repository, token, changes, current_rates, now, event_id
        )
        logging.info("Issue criada e atribuída ao proprietário do repositório: %s", issue_url)

    save_state(args.state_file, current_rates, now.isoformat())
    logging.info("O histórico foi atualizado após o registo da alteração.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("A monitorização do câmbio BHD falhou.")
        raise SystemExit(1)
