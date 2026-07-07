#!/usr/bin/env python3
"""
Todos os dias vai ao blog da Maxfinance, ve se ha artigos novos face aos ja
conhecidos e, se houver, prepara um email com eles. Guarda a lista de artigos
ja vistos para nao repetir.
"""

import json
import os
import re
import sys
import datetime as dt
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BLOG_URL = "https://www.maxfinance.pt/pt-pt/blog"
SITE = "https://www.maxfinance.pt"
ESTADO = "blog_vistos.json"      # urls de artigos ja conhecidos
CORPO = "blog_body.html"
ASSUNTO = "blog_subject.txt"
STATUS = "blog_status.txt"       # "novos" ou "nada" (o workflow le isto)

ARTICLE_RE = re.compile(r"^/pt-pt/blog/[a-z0-9\-]+$", re.I)
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MaxfinanceBlog/1.0; "
                      "+https://www.maxfinance.pt/)"
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def parse_articles(html: str):
    soup = BeautifulSoup(html, "html.parser")
    artigos = []
    seen = set()

    def is_article_link(a):
        if not a or not a.get("href"):
            return False
        return bool(ARTICLE_RE.match(a["href"].strip().replace(SITE, "")))

    for heading in soup.find_all(["h2", "h3"]):
        title = heading.get_text(" ", strip=True)
        if not title:
            continue

        url = None
        inner = heading.find("a", href=True)
        if is_article_link(inner):
            url = urljoin(SITE, inner["href"].strip())
        if url is None:
            for node in heading.find_all_next():
                if node.name in ("h2", "h3") and node is not heading:
                    break
                if node.name == "a" and is_article_link(node):
                    url = urljoin(SITE, node["href"].strip())
                    break
        if url is None:
            for node in heading.find_all_previous():
                if node.name in ("h2", "h3") and node is not heading:
                    break
                if node.name == "a" and is_article_link(node):
                    url = urljoin(SITE, node["href"].strip())
                    break

        if not url or url in seen:
            continue
        seen.add(url)

        data_txt = ""
        resumo = ""
        for node in heading.find_all_next():
            if node.name in ("h2", "h3") and node is not heading:
                if node.get_text(strip=True):
                    break
            if node in heading.descendants:
                continue
            text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
            if not text or text == title:
                continue
            if not data_txt:
                m = DATE_RE.search(text)
                if m and len(text) < 25:
                    data_txt = m.group(0)
                    continue
            if (not resumo and len(text) > 40
                    and node.name not in ("h1", "h2", "h3", "h4")
                    and "ler mais" not in text.lower()):
                resumo = text
            if data_txt and resumo:
                break

        artigos.append({"title": title, "url": url,
                        "data": data_txt, "resumo": resumo or ""})

    return artigos


def build_email(novos):
    hoje = dt.date.today().strftime("%d/%m/%Y")
    n = len(novos)
    titulo = "1 artigo novo no blog" if n == 1 else f"{n} artigos novos no blog"

    blocos = []
    for a in novos:
        data_linha = f"<span style='color:#888;font-size:13px;'>{a['data']}</span>" if a["data"] else ""
        resumo = a["resumo"]
        if len(resumo) > 220:
            resumo = resumo[:220].rsplit(" ", 1)[0] + "..."
        blocos.append(f"""
        <div style="background:#fff;border-radius:8px;padding:18px 20px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
          <h2 style="font-size:17px;margin:0 0 6px;color:#1f2d3d;">{a['title']}</h2>
          {data_linha}
          <p style="font-size:14px;color:#444;line-height:1.5;margin:8px 0 14px;">{resumo}</p>
          <a href="{a['url']}" style="display:inline-block;background:#1f6feb;color:#fff;text-decoration:none;padding:8px 16px;border-radius:6px;font-size:14px;">Ler o artigo &rarr;</a>
        </div>""")

    html = f"""<!DOCTYPE html>
<html lang="pt">
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#222;">
  <div style="max-width:600px;margin:0 auto;padding:24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">{titulo}</h1>
    <p style="color:#666;margin:0 0 20px;font-size:14px;">Verificado a {hoje} em maxfinance.pt/pt-pt/blog</p>
    {''.join(blocos)}
    <p style="color:#888;font-size:12px;margin-top:20px;line-height:1.5;">
      Aviso automático sempre que sai conteúdo novo no blog.<br>
      Maxfinance Balance.
    </p>
  </div>
</body>
</html>"""

    if n == 1:
        assunto = f"Blog Maxfinance: {novos[0]['title']}"
    else:
        assunto = f"Blog Maxfinance: {n} artigos novos"
    return html, assunto


def escrever(status, corpo=None, assunto=None):
    with open(STATUS, "w", encoding="utf-8") as f:
        f.write(status)
    if corpo is not None:
        with open(CORPO, "w", encoding="utf-8") as f:
            f.write(corpo)
    if assunto is not None:
        with open(ASSUNTO, "w", encoding="utf-8") as f:
            f.write(assunto)


def main():
    html = fetch_html(BLOG_URL)
    artigos = parse_articles(html)
    if not artigos:
        print("ERRO: nao encontrei artigos. A estrutura do site pode ter mudado.",
              file=sys.stderr)
        sys.exit(1)

    urls_atuais = [a["url"] for a in artigos]

    primeira_vez = not os.path.exists(ESTADO)
    vistos = []
    if not primeira_vez:
        try:
            with open(ESTADO, encoding="utf-8") as f:
                vistos = json.load(f).get("urls", [])
        except Exception:
            vistos = []

    vistos_set = set(vistos)

    if primeira_vez:
        # Primeira corrida: manda os artigos atuais (para veres que funciona)
        # e fica a saber que estes ja foram vistos.
        novos = artigos
    else:
        novos = [a for a in artigos if a["url"] not in vistos_set]

    if novos:
        corpo, assunto = build_email(novos)
        escrever("novos", corpo, assunto)
        print(f"OK: {len(novos)} artigo(s) para enviar.")
        for a in novos:
            print("  -", a["title"])
    else:
        escrever("nada")
        print("OK: sem artigos novos hoje.")

    # Atualizar a lista de vistos (mantem os antigos + os atuais)
    todos = list(dict.fromkeys(list(vistos) + urls_atuais))
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump({"atualizado": dt.date.today().isoformat(), "urls": todos},
                  f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
