#!/usr/bin/env python3
"""Deteta artigos novos no blog Maxfinance e abre uma Issue no GitHub."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BLOG_URL = "https://www.maxfinance.pt/pt-pt/blog"
SITE_URL = "https://www.maxfinance.pt"
STATE_FILE = Path("blog_vistos_github.json")
ARTICLE_RE = re.compile(r"^/pt-pt/blog/[a-z0-9\-]+$", re.I)
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
MARKER_PREFIX = "maxfinance-blog-event:"


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
        {"User-Agent": "Mozilla/5.0 (compatible; Maxfinance-Blog-Monitor/2.0)"}
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_articles(session: requests.Session) -> list[dict[str, str]]:
    logging.info("A consultar o blog Maxfinance: %s", BLOG_URL)
    response = session.get(BLOG_URL, timeout=45)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    articles: list[dict[str, str]] = []
    seen: set[str] = set()

    def article_url(link: Any) -> str | None:
        if not link or not link.get("href"):
            return None
        href = str(link["href"]).strip()
        relative = href.replace(SITE_URL, "")
        return urljoin(SITE_URL, href) if ARTICLE_RE.match(relative) else None

    for link in soup.find_all("a", href=True):
        url = article_url(link)
        if not url or url in seen:
            continue

        card_text = ""
        for container in link.parents:
            candidate = container.get_text(" ", strip=True)
            if DATE_RE.search(candidate):
                card_text = candidate
                break
        match = DATE_RE.search(card_text)
        if not match:
            logging.warning("Artigo ignorado por não ter data: %s", url)
            continue

        title = card_text[: match.start()].strip()
        remainder = card_text[match.end() :].strip()
        excerpt = re.sub(r"\s*Ler mais\s*$", "", remainder, flags=re.I).strip()
        if not title:
            logging.warning("Artigo ignorado por não ter título: %s", url)
            continue

        seen.add(url)
        articles.append(
            {
                "title": title,
                "url": url,
                "date": match.group(0),
                "excerpt": excerpt,
            }
        )

    if not articles:
        raise RuntimeError("Nenhum artigo encontrado; a estrutura do blog pode ter mudado.")
    logging.info("Foram encontrados %s artigos na página.", len(articles))
    return articles


def load_state() -> dict[str, Any] | None:
    if not STATE_FILE.exists():
        return None
    with STATE_FILE.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state.get("urls"), list):
        raise ValueError(f"Formato inválido em {STATE_FILE}.")
    return state


def save_state(urls: list[str]) -> None:
    state = {"atualizado": datetime.now(timezone.utc).isoformat(), "urls": urls}
    temporary = STATE_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(STATE_FILE)


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def event_id(articles: list[dict[str, str]]) -> str:
    urls = "|".join(sorted(article["url"] for article in articles))
    return hashlib.sha256(urls.encode("utf-8")).hexdigest()[:24]


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


def create_issue(
    session: requests.Session,
    repository: str,
    token: str,
    articles: list[dict[str, str]],
    identifier: str,
) -> str:
    blocks = []
    for article in articles:
        excerpt = article["excerpt"].strip()
        if len(excerpt) > 400:
            excerpt = excerpt[:400].rsplit(" ", 1)[0] + "…"
        details = f"\n\n{excerpt}" if excerpt else ""
        date_text = f" — {article['date']}" if article["date"] else ""
        blocks.append(f"### [{article['title']}]({article['url']}){date_text}{details}")

    count = len(articles)
    title = "Novo artigo no blog Maxfinance" if count == 1 else f"{count} novos artigos no blog Maxfinance"
    body = f"""Foram detetados novos conteúdos no blog Maxfinance.

{chr(10).join(blocks)}

[Consultar o blog Maxfinance]({BLOG_URL})

{marker(identifier)}
"""
    owner = repository.split("/", maxsplit=1)[0]
    response = session.post(
        f"https://api.github.com/repos/{repository}/issues",
        headers=github_headers(token),
        json={"title": title, "body": body, "assignees": [owner]},
        timeout=30,
    )
    response.raise_for_status()
    return str(response.json()["html_url"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    session = make_session()
    articles = fetch_articles(session)
    current_urls = [article["url"] for article in articles]
    state = load_state()

    if state is None:
        logging.info("Primeira execução: os artigos atuais serão a referência inicial.")
        save_state(current_urls)
        logging.info("Nenhuma Issue ou notificação foi criada.")
        return 0

    known = set(state["urls"])
    new_articles = [article for article in articles if article["url"] not in known]
    if not new_articles:
        logging.info("Nenhum artigo novo. Nenhuma Issue ou notificação foi criada.")
        return 0

    logging.info("Foram detetados %s artigos novos:", len(new_articles))
    for article in new_articles:
        logging.info("- %s | %s", article["title"], article["url"])

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN e GITHUB_REPOSITORY são obrigatórios.")

    identifier = event_id(new_articles)
    if issue_exists(session, repository, token, identifier):
        logging.info("A Issue desta novidade já existe; duplicado evitado.")
    else:
        url = create_issue(session, repository, token, new_articles, identifier)
        logging.info("Issue criada e atribuída ao proprietário: %s", url)

    all_urls = list(dict.fromkeys(state["urls"] + current_urls))
    save_state(all_urls)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.exception("A monitorização do blog falhou.")
        raise SystemExit(1)
