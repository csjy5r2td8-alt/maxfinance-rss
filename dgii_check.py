#!/usr/bin/env python3
"""Monitoriza os Avisos Informativos da DGII e abre Issues para avisos novos."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PAGE_URL = (
    "https://www.dgii.gov.do/publicacionesOficiales/"
    "avisosInformativos/Paginas/default.aspx"
)
DEFAULT_STATE_FILE = Path("data/dgii_known_notices.json")
ISSUE_TITLE = "Novo aviso DGII sobre incentivo de Facturación Electrónica"
ISSUE_MARKER_PREFIX = "dgii-notice-id:"

# A comparação é feita sem acentos e sem distinguir maiúsculas de minúsculas.
KEYWORDS = {
    "Incentivo Fiscal": "incentivo fiscal",
    "Facturación Electrónica": "facturacion electronica",
    "Pequeños": "pequen",
    "Micro": "micro",
    "No Clasificados": "no clasificado",
    "implementación de Facturación Electrónica": (
        "implementacion de facturacion electronica"
    ),
    "periodo de voluntariedad": "periodo de voluntariedad",
}


def normalize(value: str) -> str:
    """Normaliza texto para permitir pesquisas tolerantes a acentos e espaços."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().casefold()


def make_session() -> requests.Session:
    """Cria uma sessão HTTP com tentativas automáticas para erros temporários."""
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
                "Mozilla/5.0 (compatible; Maxfinance-DGII-Monitor/1.0; "
                "+https://github.com/)"
            )
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_page(session: requests.Session, page_file: Path | None = None) -> str:
    if page_file:
        logging.info("A ler página de teste: %s", page_file)
        return page_file.read_text(encoding="utf-8")

    logging.info("A consultar a página da DGII: %s", PAGE_URL)
    response = session.get(PAGE_URL, timeout=45)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    logging.info(
        "Página consultada com sucesso (%s; %s bytes).",
        response.status_code,
        len(response.content),
    )
    return response.text


def notice_id(title: str, date: str, url: str) -> str:
    raw = "|".join((normalize(title), date.strip(), url.strip()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def parse_notices(html: str) -> list[dict[str, Any]]:
    """Extrai os cartões de avisos da estrutura atualmente usada pela DGII."""
    soup = BeautifulSoup(html, "html.parser")
    notices: list[dict[str, Any]] = []

    for card in soup.select("li.card__content"):
        link = card.select_one("a[href]")
        code_node = card.select_one(".file-card__title")
        date_nodes = card.select(".file-card__date")
        if not link or not code_node or not date_nodes:
            continue

        code = " ".join(code_node.stripped_strings)
        description = " ".join(date_nodes[0].stripped_strings)
        date = str(card.get("data-modified", "")).strip()
        if not date:
            metadata = " ".join(card.stripped_strings)
            match = re.search(r"Modificado:\s*(\d{2}/\d{2}/\d{4})", metadata)
            date = match.group(1) if match else "Data não indicada"

        url = urljoin(PAGE_URL, str(link.get("href", "")).strip())
        full_title = f"{code} {description}".strip()
        notices.append(
            {
                "id": notice_id(full_title, date, url),
                "code": code,
                "title": full_title,
                "description": description,
                "date": date,
                "url": url,
            }
        )

    if not notices:
        raise RuntimeError(
            "Nenhum aviso foi encontrado. A estrutura da página da DGII pode ter mudado."
        )
    return notices


def matched_keywords(notice: dict[str, Any]) -> list[str]:
    text = normalize(f"{notice['title']} {notice['description']}")
    return [label for label, term in KEYWORDS.items() if term in text]


def is_relevant(notice: dict[str, Any]) -> bool:
    """Exige Facturación Electrónica, um público-alvo e contexto do incentivo."""
    text = normalize(f"{notice['title']} {notice['description']}")
    has_electronic_invoicing = "facturacion electronica" in text
    has_target_group = any(
        term in text for term in ("pequen", "micro", "no clasificado")
    )
    has_incentive_context = any(
        term in text
        for term in (
            "incentivo fiscal",
            "periodo de voluntariedad",
            "implementacion de facturacion electronica",
        )
    )
    return has_electronic_invoicing and has_target_group and has_incentive_context


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_checked_at": None, "notices": []}
    with path.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state.get("notices"), list):
        raise ValueError(f"Formato inválido em {path}: 'notices' deve ser uma lista.")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def issue_marker(item_id: str) -> str:
    return f"<!-- {ISSUE_MARKER_PREFIX}{item_id} -->"


def issue_already_exists(
    session: requests.Session, repository: str, token: str, item_id: str
) -> bool:
    """Procura o marcador único em todas as Issues, abertas ou fechadas."""
    marker = issue_marker(item_id)
    url = f"https://api.github.com/repos/{repository}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    page = 1
    while True:
        response = session.get(
            url,
            headers=headers,
            params={"state": "all", "per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        items = response.json()
        if any(marker in (item.get("body") or "") for item in items):
            return True
        if len(items) < 100:
            return False
        page += 1


def create_issue(
    session: requests.Session,
    repository: str,
    token: str,
    notice: dict[str, Any],
) -> str:
    marker = issue_marker(notice["id"])
    excerpt = notice["description"][:500].strip()
    repository_owner = repository.split("/", maxsplit=1)[0]
    body = f"""Foi detetado um novo aviso relevante na página da DGII.

- **Aviso:** {notice['title']}
- **Data indicada pela DGII:** {notice['date']}
- **Ligação:** {notice['url']}
- **Trecho encontrado:** {excerpt}

Verificar o documento oficial e confirmar a aplicabilidade do incentivo fiscal às pequenas empresas, microempresas ou contribuintes não classificados.

{marker}
"""
    response = session.post(
        f"https://api.github.com/repos/{repository}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "title": ISSUE_TITLE,
            "body": body,
            "assignees": [repository_owner],
        },
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["html_url"])


def state_entry(notice: dict[str, Any], recorded_at: str) -> dict[str, str]:
    return {
        "id": notice["id"],
        "code": notice["code"],
        "title": notice["title"],
        "date": notice["date"],
        "url": notice["url"],
        "recorded_at": recorded_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument(
        "--page-file", type=Path, help="HTML local para teste, em vez da página real."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Não cria Issues nem altera o histórico."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    logging.Formatter.converter = __import__("time").gmtime

    session = make_session()
    html = fetch_page(session, args.page_file)
    notices = parse_notices(html)
    logging.info("Total de avisos encontrados na página: %d", len(notices))

    candidates = []
    for notice in notices:
        matches = matched_keywords(notice)
        if matches:
            logging.info(
                "Palavras-chave em '%s': %s",
                notice["title"],
                ", ".join(matches),
            )
        if is_relevant(notice):
            candidates.append(notice)

    logging.info("Avisos que satisfazem todos os critérios: %d", len(candidates))
    for notice in candidates:
        logging.info("Aviso relevante: %s | %s", notice["title"], notice["url"])

    state = load_state(args.state_file)
    known_ids = {str(item.get("id")) for item in state["notices"]}
    new_notices = [item for item in candidates if item["id"] not in known_ids]
    logging.info("Novos avisos relevantes detetados: %d", len(new_notices))

    if args.dry_run:
        for notice in new_notices:
            logging.info("[DRY RUN] Novo aviso: %s", notice["title"])
        return 0

    if new_notices:
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if not token or not repository:
            raise RuntimeError(
                "GITHUB_TOKEN e GITHUB_REPOSITORY são necessários para criar Issues."
            )

        for notice in new_notices:
            if issue_already_exists(session, repository, token, notice["id"]):
                logging.info(
                    "A Issue deste aviso já existe; não será duplicada: %s",
                    notice["title"],
                )
            else:
                issue_url = create_issue(session, repository, token, notice)
                logging.info("Issue criada: %s", issue_url)
            state["notices"].append(state_entry(notice, checked_at))
        state["last_checked_at"] = checked_at
        save_state(args.state_file, state)
        logging.info("Histórico atualizado em %s", args.state_file)
    else:
        logging.info("Nenhum aviso novo. Nenhuma Issue será criada.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("A verificação da DGII falhou.")
        raise SystemExit(1)
