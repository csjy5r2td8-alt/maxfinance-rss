#!/usr/bin/env python3
"""Gera rss.xml com os artigos atuais do blog Maxfinance."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from feedgen.feed import FeedGenerator

from blog_alerta_github import BLOG_URL, fetch_articles, make_session


SITE_URL = "https://www.maxfinance.pt"
OUTPUT = Path("rss.xml")
LISBON = ZoneInfo("Europe/Lisbon")


def publication_date(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(value, "%d.%m.%Y").replace(
            hour=9, tzinfo=LISBON
        )
    except (TypeError, ValueError):
        return None


def build_feed(articles: list[dict[str, str]]) -> bytes:
    feed = FeedGenerator()
    feed.title("Blog Maxfinance")
    feed.link(href=BLOG_URL, rel="alternate")
    feed.description(
        "Conteúdos sobre crédito e finanças pessoais do blog da Maxfinance."
    )
    feed.language("pt-PT")
    feed.lastBuildDate(dt.datetime.now(LISBON))
    feed.generator("MaxfinanceRSS")

    # A fonte devolve primeiro os artigos mais recentes. O feedgen apresenta
    # primeiro a última entrada adicionada, por isso inserimos em ordem inversa.
    for article in reversed(articles):
        entry = feed.add_entry()
        entry.title(article["title"])
        entry.link(href=article["url"])
        entry.guid(article["url"], permalink=True)
        entry.description(article.get("excerpt") or article["title"])
        published = publication_date(article.get("date", ""))
        if published is not None:
            entry.pubDate(published)

    return feed.rss_str(pretty=True)


def main() -> None:
    articles = fetch_articles(make_session())
    if not articles:
        raise RuntimeError("Nenhum artigo encontrado; o RSS anterior foi preservado.")

    temporary = OUTPUT.with_suffix(".xml.tmp")
    temporary.write_bytes(build_feed(articles))
    temporary.replace(OUTPUT)
    print(f"OK: {len(articles)} artigos escritos em {OUTPUT}.")


if __name__ == "__main__":
    main()
