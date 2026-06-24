#!/usr/bin/env python3
"""
Le as taxas Euribor actuais, compara com a semana anterior e gera o corpo
de um email (HTML) com o resumo. Guarda os valores para comparar na proxima semana.
"""

import json
import os
import re
import sys
import datetime as dt

import requests
from bs4 import BeautifulSoup

URL = "https://www.euribor-rates.eu/pt/taxas-euribor-actuais/"
ESTADO = "euribor_anterior.json"   # guarda os valores da semana passada
CORPO = "email_body.html"
ASSUNTO = "email_subject.txt"

# Prazos que nos interessam, pela ordem em que aparecem no email.
PRAZOS = ["1 semana", "1 mês", "3 meses", "6 meses", "12 meses"]
# Os mais relevantes para credito habitacao em Portugal.
DESTAQUE = {"6 meses", "12 meses"}


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; EuriborResumo/1.0; "
            "+https://www.maxfinance.pt/)"
        )
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def to_float(txt: str):
    """ '2,874 %' -> 2.874 """
    m = re.search(r"(\d+)[.,](\d+)", txt)
    if not m:
        return None
    return float(f"{m.group(1)}.{m.group(2)}")


def parse_rates(html: str):
    """
    Devolve (data_mais_recente, {prazo: {'hoje': x, 'ontem': y}}).
    A tabela tem uma linha por prazo e colunas pelos ultimos dias uteis
    (a primeira coluna de dados e a mais recente).
    """
    soup = BeautifulSoup(html, "html.parser")
    data_recente = None
    resultado = {}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # Cabecalho: primeira linha, datas nas celulas a seguir a primeira.
        header_cells = rows[0].find_all(["th", "td"])
        datas = [c.get_text(strip=True) for c in header_cells[1:]]
        datas = [d for d in datas if re.search(r"\d{2}/\d{2}/\d{4}", d)]
        if not datas:
            continue
        if data_recente is None:
            data_recente = datas[0]

        for tr in rows[1:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True)
            prazo = next((p for p in PRAZOS if p in label), None)
            if not prazo:
                continue
            valores = [to_float(c.get_text(strip=True)) for c in cells[1:]]
            valores = [v for v in valores if v is not None]
            if not valores:
                continue
            resultado[prazo] = {
                "hoje": valores[0],
                "ontem": valores[1] if len(valores) > 1 else None,
            }

    return data_recente, resultado


def seta(diff):
    if diff is None:
        return "", "#666"
    if diff > 0.0005:
        return "&#9650;", "#c0392b"   # subiu (vermelho - pior para quem paga credito)
    if diff < -0.0005:
        return "&#9660;", "#27ae60"   # desceu (verde)
    return "=", "#666"


def fmt_diff(diff):
    if diff is None:
        return "—"
    sinal = "+" if diff >= 0 else ""
    return f"{sinal}{diff:.3f}".replace(".", ",")


def build_email(data_recente, atual, anterior):
    hoje = dt.date.today().strftime("%d/%m/%Y")

    linhas = []
    for prazo in PRAZOS:
        if prazo not in atual:
            continue
        hoje_v = atual[prazo]["hoje"]
        ontem_v = atual[prazo]["ontem"]
        diff_dia = (hoje_v - ontem_v) if ontem_v is not None else None

        prev = anterior.get(prazo) if anterior else None
        diff_sem = (hoje_v - prev) if isinstance(prev, (int, float)) else None

        s_dia, c_dia = seta(diff_dia)
        s_sem, c_sem = seta(diff_sem)
        destaque = prazo in DESTAQUE
        peso = "700" if destaque else "400"
        fundo = "#f4f8ff" if destaque else "#ffffff"

        linhas.append(f"""
        <tr style="background:{fundo};">
          <td style="padding:10px 12px;font-weight:{peso};border-bottom:1px solid #eee;">
            Euribor {prazo}{' &#9733;' if destaque else ''}
          </td>
          <td style="padding:10px 12px;text-align:right;font-weight:{peso};border-bottom:1px solid #eee;">
            {('%.3f' % hoje_v).replace('.', ',')} %
          </td>
          <td style="padding:10px 12px;text-align:right;color:{c_dia};border-bottom:1px solid #eee;">
            {s_dia} {fmt_diff(diff_dia)}
          </td>
          <td style="padding:10px 12px;text-align:right;color:{c_sem};border-bottom:1px solid #eee;">
            {s_sem} {fmt_diff(diff_sem)}
          </td>
        </tr>""")

    nota_semana = ""
    if not anterior:
        nota_semana = ("<p style='color:#888;font-size:13px;'>"
                       "(Esta é a primeira recolha, por isso ainda não há comparação "
                       "com a semana anterior. A partir da próxima já aparece.)</p>")

    html = f"""<!DOCTYPE html>
<html lang="pt">
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#222;">
  <div style="max-width:600px;margin:0 auto;padding:24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">Resumo semanal Euribor</h1>
    <p style="color:#666;margin:0 0 20px;font-size:14px;">
      Taxas mais recentes ({data_recente}) &middot; relatório de {hoje}
    </p>

    <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <thead>
        <tr style="background:#1f2d3d;color:#fff;">
          <th style="padding:10px 12px;text-align:left;font-size:13px;">Prazo</th>
          <th style="padding:10px 12px;text-align:right;font-size:13px;">Taxa</th>
          <th style="padding:10px 12px;text-align:right;font-size:13px;">vs dia anterior</th>
          <th style="padding:10px 12px;text-align:right;font-size:13px;">vs semana anterior</th>
        </tr>
      </thead>
      <tbody>
        {''.join(linhas)}
      </tbody>
    </table>

    {nota_semana}

    <p style="color:#888;font-size:12px;margin-top:20px;line-height:1.5;">
      &#9733; prazos mais usados no crédito habitação em Portugal.<br>
      Fonte: euribor-rates.eu. As taxas têm 24h de atraso, conforme exigido pelo EMMI.<br>
      Resumo automático — Maxfinance Balance.
    </p>
  </div>
</body>
</html>"""

    # Assunto com a taxa a 12 meses, que e a referencia mais comum.
    ref = atual.get("12 meses", {}).get("hoje")
    if ref is not None:
        assunto = f"Euribor semanal — 12M em {('%.3f' % ref).replace('.', ',')}% ({data_recente})"
    else:
        assunto = f"Resumo semanal Euribor ({data_recente})"

    return html, assunto


def main():
    html = fetch_html(URL)
    data_recente, atual = parse_rates(html)
    if not atual:
        print("ERRO: nao consegui ler as taxas. A pagina pode ter mudado.",
              file=sys.stderr)
        sys.exit(1)

    anterior = {}
    if os.path.exists(ESTADO):
        try:
            with open(ESTADO, encoding="utf-8") as f:
                anterior = json.load(f).get("taxas", {})
        except Exception:
            anterior = {}

    corpo, assunto = build_email(data_recente, atual, anterior)

    with open(CORPO, "w", encoding="utf-8") as f:
        f.write(corpo)
    with open(ASSUNTO, "w", encoding="utf-8") as f:
        f.write(assunto)

    # Guardar os valores de hoje para comparar na proxima semana.
    novo_estado = {
        "data": data_recente,
        "taxas": {p: atual[p]["hoje"] for p in atual},
    }
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(novo_estado, f, ensure_ascii=False, indent=2)

    print(f"OK: email preparado. Taxas de {data_recente}.")
    for p in PRAZOS:
        if p in atual:
            print(f"  Euribor {p}: {atual[p]['hoje']}")


if __name__ == "__main__":
    main()
