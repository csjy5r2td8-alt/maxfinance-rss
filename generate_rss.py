#!/usr/bin/env python3
"""
Gera um feed RSS a partir do blog da Maxfinance (Drupal).
Vai à pagina do blog, apanha os artigos (titulo, link, data, resumo)
e escreve um ficheiro rss.xml.
"""

import re
import sys
import datetime as dt
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

BLOG_URL = "https://www.maxfinance.pt/pt-pt/blog"
SITE = "https://www.maxfinance.pt"
FEED_TITLE = "Blog Maxfinance"
FEED_DESC = ("Conteudos sobre credito e financas pessoais do blog da Maxfinance.")
LISBON = dt.timezone(dt.timedelta(hours=1))  # WEST/WET aproximado; serve para o pubDate

# Datas no formato 18.06.2026
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
# Links de artigo: /pt-pt/blog/<slug>  (exclui a propria listagem e filtros por ?tag=)
ARTICLE_RE = re.compile(r"^/pt-pt/blog/[a-z0-9\-]+$", re.I)


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; MaxfinanceRSS/1.0; "
            "+https://www.maxfinance.pt/)"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def parse_articles(html: str):
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    seen = set()

    # Cada artigo da listagem tem um titulo em <h2>/<h3> com link para a pagina.
    for heading in soup.find_all(["h2", "h3"]):
        link = heading.find("a", href=True)
        # Se o titulo nao tem link dentro, procura um link de artigo proximo.
        if not link:
            continue
        href = link["href"].strip()
        path = href.replace(SITE, "")
        if not ARTICLE_RE.match(path):
            continue

        full_url = urljoin(SITE, href)
        if full_url in seen:
            continue
        seen.add(full_url)

        title = link.get_text(strip=True)
        if not title:
            continue

        # A partir do titulo, varre os elementos seguintes a procura de data e resumo.
        date_val = None
        summary = ""
        for node in heading.find_all_next():
            # parar ao chegar ao proximo artigo (outro titulo com link de blog)
            if node.name in ("h2", "h3") and node is not heading:
                nlink = node.find("a", href=True)
                if nlink and ARTICLE_RE.match(nlink["href"].replace(SITE, "")):
                    break
            # ignorar o que esta dentro do proprio titulo
            if node in heading.descendants:
                continue
            text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
            if not text or text == title:
                continue
            if date_val is None:
                m = DATE_RE.search(text)
                if m and len(text) < 25:  # bloco que e so a data
                    d, mth, y = map(int, m.groups())
                    date_val = dt.datetime(y, mth, d, 9, 0, tzinfo=LISBON)
                    continue
            # primeiro paragrafo de texto com corpo vira resumo (ignora "Ler mais")
            if (not summary and len(text) > 40
                    and node.name not in ("h1", "h2", "h3", "h4")
                    and "ler mais" not in text.lower()):
                summary = text
            if date_val and summary:
                break

        articles.append(
            {
                "title": title,
                "url": full_url,
                "date": date_val,
                "summary": summary or title,
            }
        )

    return articles


def build_feed(articles) -> bytes:
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=BLOG_URL, rel="alternate")
    fg.description(FEED_DESC)
    fg.language("pt-pt")
    fg.lastBuildDate(dt.datetime.now(LISBON))
    fg.generator("MaxfinanceRSS")

    # feedgen escreve por ordem inversa, por isso adiciona-se do mais antigo p/ o mais novo
    for art in reversed(articles):
        fe = fg.add_entry()
        fe.title(art["title"])
        fe.link(href=art["url"])
        fe.guid(art["url"], permalink=True)
        fe.description(art["summary"])
        if art["date"]:
            fe.pubDate(art["date"])

    return fg.rss_str(pretty=True)


def main():
    html = fetch_html(BLOG_URL)
    articles = parse_articles(html)
    if not articles:
        print("ERRO: nao encontrei artigos. A estrutura do site pode ter mudado.",
              file=sys.stderr)
        sys.exit(1)
    rss = build_feed(articles)
    with open("rss.xml", "wb") as f:
        f.write(rss)
    print(f"OK: {len(articles)} artigos escritos em rss.xml")


if __name__ == "__main__":
    main()
