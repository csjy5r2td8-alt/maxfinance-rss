#!/usr/bin/env python3
"""
Resumo diario Maxfinance num so email:
  1) Euribor (1 semana, 1, 3, 6 e 12 meses)
  2) Artigos novos no blog Maxfinance
Compara com o envio anterior e mostra o que mudou.
"""

import json
import os
import re
import sys
import datetime as dt
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

EURIBOR_URL = "https://www.euribor-rates.eu/pt/taxas-euribor-actuais/"
BLOG_URL = "https://www.maxfinance.pt/pt-pt/blog"
SITE = "https://www.maxfinance.pt"

ESTADO = "resumo_estado.json"
CORPO = "resumo_body.html"
ASSUNTO = "resumo_subject.txt"

PRAZOS = ["1 semana", "1 mês", "3 meses", "6 meses", "12 meses"]
DESTAQUE = {"6 meses", "12 meses"}

ARTICLE_RE = re.compile(r"^/pt-pt/blog/[a-z0-9\-]+$", re.I)
DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")

UA = {"User-Agent": "Mozilla/5.0 (compatible; ResumoMaxfinance/1.0)"}


# ---------- EURIBOR ----------
def _to_float(txt):
    m = re.search(r"(\d+)[.,](\d+)", txt)
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def get_euribor():
    try:
        r = requests.get(EURIBOR_URL, headers=UA, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        out = {}
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            head = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])[1:]]
            if not any(re.search(r"\d{2}/\d{2}/\d{4}", h) for h in head):
                continue
            for tr in rows[1:]:
                cells = tr.find_all(["th", "td"])
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(" ", strip=True)
                prazo = next((p for p in PRAZOS if p in label), None)
                if not prazo:
                    continue
                v = _to_float(cells[1].get_text(strip=True))
                if v is not None:
                    out[prazo] = v
        return out
    except Exception as e:
        print("Aviso: falha a ler euribor:", e, file=sys.stderr)
        return {}


# ---------- BLOG ----------
def get_blog():
    try:
        r = requests.get(BLOG_URL, headers=UA, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        artigos, seen = [], set()

        def ok(a):
            return a and a.get("href") and ARTICLE_RE.match(a["href"].strip().replace(SITE, ""))

        for h in soup.find_all(["h2", "h3"]):
            title = h.get_text(" ", strip=True)
            if not title:
                continue
            url = None
            if ok(h.find("a", href=True)):
                url = urljoin(SITE, h.find("a", href=True)["href"].strip())
            if url is None:
                for node in h.find_all_next():
                    if node.name in ("h2", "h3") and node is not h:
                        break
                    if node.name == "a" and ok(node):
                        url = urljoin(SITE, node["href"].strip()); break
            if url is None:
                for node in h.find_all_previous():
                    if node.name in ("h2", "h3") and node is not h:
                        break
                    if node.name == "a" and ok(node):
                        url = urljoin(SITE, node["href"].strip()); break
            if not url or url in seen:
                continue
            seen.add(url)
            data_txt, resumo = "", ""
            for node in h.find_all_next():
                if node.name in ("h2", "h3") and node is not h and node.get_text(strip=True):
                    break
                if node in h.descendants:
                    continue
                text = node.get_text(" ", strip=True) if hasattr(node, "get_text") else ""
                if not text or text == title:
                    continue
                if not data_txt:
                    m = DATE_RE.search(text)
                    if m and len(text) < 25:
                        data_txt = m.group(0); continue
                if (not resumo and len(text) > 40
                        and node.name not in ("h1", "h2", "h3", "h4")
                        and "ler mais" not in text.lower()):
                    resumo = text
                if data_txt and resumo:
                    break
            artigos.append({"title": title, "url": url, "data": data_txt, "resumo": resumo})
        return artigos
    except Exception as e:
        print("Aviso: falha a ler blog:", e, file=sys.stderr)
        return []


# ---------- FORMATACAO ----------
def seta(diff, casas=3):
    if diff is None:
        return "", "#666"
    lim = 0.5 * 10 ** (-casas)
    if diff > lim:
        return "&#9650;", "#c0392b"
    if diff < -lim:
        return "&#9660;", "#27ae60"
    return "=", "#666"


def fmt(v, casas=3):
    return f"{v:.{casas}f}".replace(".", ",")


def fmt_diff(diff, casas=3):
    if diff is None:
        return "&mdash;"
    sinal = "+" if diff >= 0 else "&minus;"
    return f"{sinal}{abs(diff):.{casas}f}".replace(".", ",")


def secao_euribor(atual, prev):
    if not atual:
        return "<p style='color:#999;'>Euribor indisponível hoje.</p>"
    linhas = []
    for prazo in PRAZOS:
        if prazo not in atual:
            continue
        v = atual[prazo]
        p = prev.get(prazo) if prev else None
        d = (v - p) if isinstance(p, (int, float)) else None
        s, cor = seta(d)
        dest = prazo in DESTAQUE
        peso = "700" if dest else "400"
        fundo = "#f4f8ff" if dest else "#fff"
        linhas.append(f"""
        <tr style="background:{fundo};">
          <td style="padding:9px 12px;font-weight:{peso};border-bottom:1px solid #eee;">Euribor {prazo}{' &#9733;' if dest else ''}</td>
          <td style="padding:9px 12px;text-align:right;font-weight:{peso};border-bottom:1px solid #eee;">{fmt(v)} %</td>
          <td style="padding:9px 12px;text-align:right;color:{cor};border-bottom:1px solid #eee;">{s} {fmt_diff(d)}</td>
        </tr>""")
    return f"""
    <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;">
      <thead><tr style="background:#1f2d3d;color:#fff;">
        <th style="padding:10px 12px;text-align:left;font-size:13px;">Prazo</th>
        <th style="padding:10px 12px;text-align:right;font-size:13px;">Taxa</th>
        <th style="padding:10px 12px;text-align:right;font-size:13px;">vs ontem</th>
      </tr></thead>
      <tbody>{''.join(linhas)}</tbody>
    </table>"""


def secao_blog(novos):
    if not novos:
        return "<p style='color:#666;font-size:14px;'>Sem artigos novos hoje.</p>"
    blocos = []
    for a in novos:
        data_l = f"<span style='color:#888;font-size:12px;'>{a['data']}</span>" if a["data"] else ""
        resumo = a["resumo"]
        if len(resumo) > 180:
            resumo = resumo[:180].rsplit(" ", 1)[0] + "..."
        blocos.append(f"""
        <div style="background:#fff;border-radius:8px;padding:14px 16px;margin-bottom:10px;">
          <div style="font-size:15px;font-weight:700;color:#1f2d3d;margin-bottom:4px;">{a['title']}</div>
          {data_l}
          <p style="font-size:13px;color:#444;line-height:1.5;margin:6px 0 10px;">{resumo}</p>
          <a href="{a['url']}" style="display:inline-block;background:#1f6feb;color:#fff;text-decoration:none;padding:7px 14px;border-radius:6px;font-size:13px;">Ler o artigo &rarr;</a>
        </div>""")
    return "".join(blocos)


def titulo_secao(txt):
    return (f'<h2 style="font-size:15px;text-transform:uppercase;letter-spacing:.5px;'
            f'color:#888;margin:26px 0 10px;border-bottom:2px solid #eee;padding-bottom:6px;">{txt}</h2>')


def build_email(euribor, blog_novos, prev):
    hoje = dt.date.today().strftime("%d/%m/%Y")
    html = f"""<!DOCTYPE html>
<html lang="pt">
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#222;">
  <div style="max-width:600px;margin:0 auto;padding:24px;">
    <h1 style="font-size:21px;margin:0 0 2px;">Resumo Maxfinance</h1>
    <p style="color:#666;margin:0 0 6px;font-size:14px;">{hoje}</p>

    {titulo_secao('Euribor')}
    {secao_euribor(euribor, prev.get('euribor', {}))}

    {titulo_secao('Blog')}
    {secao_blog(blog_novos)}

    <p style="color:#888;font-size:12px;margin-top:26px;line-height:1.5;">
      Setas a vermelho = subiu face a ontem. &#9733; prazos de crédito habitação.<br>
      Euribor de euribor-rates.eu (24h de atraso). Blog de maxfinance.pt.<br>
      Resumo automático &middot; Maxfinance Balance.
    </p>
  </div>
</body>
</html>"""

    e12 = euribor.get("12 meses")
    partes = []
    if e12 is not None:
        partes.append(f"Eur12M {fmt(e12)}%")
    if blog_novos:
        n = len(blog_novos)
        partes.append(f"{n} artigo{'s' if n>1 else ''} novo{'s' if n>1 else ''}")
    assunto = "Resumo Maxfinance " + hoje + (" — " + " · ".join(partes) if partes else "")
    return html, assunto


def main():
    euribor = get_euribor()
    artigos = get_blog()

    if not euribor and not artigos:
        print("ERRO: nao consegui ler nenhuma das fontes.", file=sys.stderr)
        sys.exit(1)

    prev = {}
    primeira_vez = not os.path.exists(ESTADO)
    if not primeira_vez:
        try:
            with open(ESTADO, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}

    urls_atuais = [a["url"] for a in artigos]
    vistos = prev.get("blog_urls", [])
    if primeira_vez:
        blog_novos = artigos
    else:
        blog_novos = [a for a in artigos if a["url"] not in set(vistos)]

    corpo, assunto = build_email(euribor, blog_novos, prev)
    with open(CORPO, "w", encoding="utf-8") as f:
        f.write(corpo)
    with open(ASSUNTO, "w", encoding="utf-8") as f:
        f.write(assunto)

    novo_estado = {
        "data": dt.date.today().isoformat(),
        "euribor": euribor or prev.get("euribor", {}),
        "blog_urls": list(dict.fromkeys(list(vistos) + urls_atuais)),
    }
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(novo_estado, f, ensure_ascii=False, indent=2)

    print("OK:", assunto)
    print(f"  euribor: {len(euribor)} prazos | blog novos: {len(blog_novos)}")


if __name__ == "__main__":
    main()
