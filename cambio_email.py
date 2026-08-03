#!/usr/bin/env python3
"""
Le o cambio do BHD (dolar e euro, compra e venda), compara com o dia anterior
e gera o corpo de um email. Guarda os valores para comparar no dia seguinte.
"""

import json
import os
import sys
import datetime as dt

import requests

URL = "https://backend.bhd.com.do/api/modal-cambio-rate?populate=deep"
ESTADO = "cambio_anterior.json"
CORPO = "cambio_body.html"
ASSUNTO = "cambio_subject.txt"

# Moedas que queremos, pela ordem no email.
MOEDAS = ["EUR", "USD"]
NOMES = {"EUR": "Euro", "USD": "Dólar"}


def fetch_rates():
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
        "Origin": "https://bhd.com.do",
        "Referer": "https://bhd.com.do/",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    r = requests.get(URL, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    rates = {}
    # exchangeRates esta dentro de data.attributes.exchangeRates
    lista = (
        data.get("data", {})
        .get("attributes", {})
        .get("exchangeRates", [])
    )
    for item in lista:
        cur = item.get("currency")
        if cur in MOEDAS:
            rates[cur] = {
                "compra": float(item["buyingRate"]),
                "venda": float(item["sellingRate"]),
            }
    return rates


def seta(diff):
    if diff is None:
        return "", "#666"
    if diff > 0.0001:
        return "&#9650;", "#c0392b"   # subiu (peso mais fraco - pagas mais)
    if diff < -0.0001:
        return "&#9660;", "#27ae60"   # desceu
    return "=", "#666"


def fmt_val(v):
    return f"{v:.2f}".replace(".", ",")


def fmt_diff(diff):
    if diff is None:
        return "&mdash;"
    sinal = "+" if diff >= 0 else "&minus;"
    return f"{sinal}{abs(diff):.2f}".replace(".", ",")


def build_email(atual, anterior):
    hoje = dt.date.today().strftime("%d/%m/%Y")
    houve_mudanca = False
    linhas = []

    for cur in MOEDAS:
        if cur not in atual:
            continue
        compra = atual[cur]["compra"]
        venda = atual[cur]["venda"]
        prev = anterior.get(cur) if anterior else None

        d_compra = (compra - prev["compra"]) if prev else None
        d_venda = (venda - prev["venda"]) if prev else None
        if (d_compra and abs(d_compra) > 0.0001) or (d_venda and abs(d_venda) > 0.0001):
            houve_mudanca = True

        sc, cc = seta(d_compra)
        sv, cv = seta(d_venda)

        linhas.append(f"""
        <tr>
          <td style="padding:12px;font-weight:700;border-bottom:1px solid #eee;font-size:15px;">
            {NOMES[cur]} <span style="color:#999;font-weight:400;">({cur})</span>
          </td>
          <td style="padding:12px;text-align:right;border-bottom:1px solid #eee;">
            <div style="font-size:16px;font-weight:600;">{fmt_val(compra)}</div>
            <div style="font-size:12px;color:{cc};">{sc} {fmt_diff(d_compra)}</div>
          </td>
          <td style="padding:12px;text-align:right;border-bottom:1px solid #eee;">
            <div style="font-size:16px;font-weight:600;">{fmt_val(venda)}</div>
            <div style="font-size:12px;color:{cv};">{sv} {fmt_diff(d_venda)}</div>
          </td>
        </tr>""")

    if not anterior:
        aviso = ("<p style='color:#888;font-size:13px;'>É a primeira recolha, "
                 "por isso ainda não há comparação com o dia anterior. A partir "
                 "de amanhã já aparece.</p>")
    elif houve_mudanca:
        aviso = ("<p style='background:#fff4e5;border-left:4px solid #f39c12;"
                 "padding:10px 14px;font-size:14px;margin:16px 0;'>"
                 "<b>Houve alteração</b> nas taxas face a ontem. Ver setas abaixo.</p>")
    else:
        aviso = ("<p style='background:#eef7ee;border-left:4px solid #27ae60;"
                 "padding:10px 14px;font-size:14px;margin:16px 0;'>"
                 "Sem alterações face a ontem. As taxas estão iguais.</p>")

    html = f"""<!DOCTYPE html>
<html lang="pt">
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#222;">
  <div style="max-width:560px;margin:0 auto;padding:24px;">
    <h1 style="font-size:20px;margin:0 0 4px;">Câmbio BHD &mdash; {hoje}</h1>
    <p style="color:#666;margin:0 0 8px;font-size:14px;">
      Taxas em pesos dominicanos (DOP) por unidade de moeda.
    </p>

    {aviso}

    <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
      <thead>
        <tr style="background:#0b6b3a;color:#fff;">
          <th style="padding:12px;text-align:left;font-size:13px;">Moeda</th>
          <th style="padding:12px;text-align:right;font-size:13px;">Compra</th>
          <th style="padding:12px;text-align:right;font-size:13px;">Venda</th>
        </tr>
      </thead>
      <tbody>
        {''.join(linhas)}
      </tbody>
    </table>

    <p style="color:#888;font-size:12px;margin-top:20px;line-height:1.5;">
      Compra = a quanto o banco compra a moeda; Venda = a quanto a vende.<br>
      As setas mostram a variação face ao dia anterior (vermelho = subiu).<br>
      Fonte: BHD (bhd.com.do). Recolha automática.
    </p>
  </div>
</body>
</html>"""

    # Assunto: destaca a venda do euro, que e o que te interessa para pagar fornecedores.
    eur_v = atual.get("EUR", {}).get("venda")
    if eur_v is not None:
        estado = "mudou" if houve_mudanca else "sem alteração"
        assunto = f"Câmbio BHD {hoje} — EUR venda {fmt_val(eur_v)} DOP ({estado})"
    else:
        assunto = f"Câmbio BHD {hoje}"

    return html, assunto


def main():
    atual = fetch_rates()
    if not atual:
        print("ERRO: nao consegui ler o cambio. A API pode ter mudado.",
              file=sys.stderr)
        sys.exit(1)

    anterior = {}
    if os.path.exists(ESTADO):
        try:
            with open(ESTADO, encoding="utf-8") as f:
                anterior = json.load(f).get("taxas", {})
        except Exception:
            anterior = {}

    corpo, assunto = build_email(atual, anterior)

    with open(CORPO, "w", encoding="utf-8") as f:
        f.write(corpo)
    with open(ASSUNTO, "w", encoding="utf-8") as f:
        f.write(assunto)

    novo = {"data": dt.date.today().isoformat(), "taxas": atual}
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(novo, f, ensure_ascii=False, indent=2)

    print(f"OK: email preparado ({assunto})")
    for cur in MOEDAS:
        if cur in atual:
            print(f"  {cur}: compra {atual[cur]['compra']} / venda {atual[cur]['venda']}")


if __name__ == "__main__":
    main()
