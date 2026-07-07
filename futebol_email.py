#!/usr/bin/env python3
"""
Resumo diario de futebol por email.
Para cada competicao (das que o plano gratuito da football-data.org permite):
  - resultados de ontem
  - classificacao atual
  - melhores marcadores
  - jogos de hoje
"""

import os
import sys
import time
import datetime as dt

import requests

TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "")
BASE = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": TOKEN}

CORPO = "futebol_body.html"
ASSUNTO = "futebol_subject.txt"

# Competicoes confirmadas como disponiveis no plano gratuito (TIER_ONE).
COMPETICOES = [
    ("PPL", "Liga Portugal"),
    ("PL", "Premier League"),
    ("PD", "La Liga"),
    ("SA", "Serie A"),
    ("BL1", "Bundesliga"),
    ("FL1", "Ligue 1"),
    ("CL", "Champions League"),
    ("EC", "Europeu"),
    ("WC", "Mundial"),
]

# Limite gratuito: 10 pedidos por minuto. Esta pausa entre pedidos mantem-nos
# bem dentro do limite mesmo com varias competicoes.
PAUSA = 6.5


def pedir(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    time.sleep(PAUSA)
    if r.status_code == 429:
        time.sleep(30)
        r = requests.get(url, headers=HEADERS, timeout=30)
        time.sleep(PAUSA)
    r.raise_for_status()
    return r.json()


def jogos(codigo, data_ini, data_fim):
    url = f"{BASE}/competitions/{codigo}/matches?dateFrom={data_ini}&dateTo={data_fim}"
    try:
        return pedir(url).get("matches", [])
    except Exception as e:
        print(f"Aviso: sem jogos para {codigo}: {e}", file=sys.stderr)
        return []


def classificacao(codigo):
    url = f"{BASE}/competitions/{codigo}/standings"
    try:
        data = pedir(url)
        for grp in data.get("standings", []):
            if grp["type"] == "TOTAL":
                return [{"pos": r["position"], "equipa": r["team"]["shortName"] or r["team"]["name"],
                        "pts": r["points"], "jogos": r["playedGames"],
                        "gd": r["goalDifference"]} for r in grp["table"]]
        return []
    except Exception as e:
        print(f"Aviso: sem classificacao para {codigo}: {e}", file=sys.stderr)
        return []


def marcadores(codigo):
    url = f"{BASE}/competitions/{codigo}/scorers?limit=5"
    try:
        data = pedir(url)
        return [{"jogador": s["player"]["name"],
                "equipa": (s["team"]["shortName"] or s["team"]["name"]) if s.get("team") else "",
                "golos": s["goals"]} for s in data.get("scorers", [])]
    except Exception as e:
        print(f"Aviso: sem marcadores para {codigo}: {e}", file=sys.stderr)
        return []


# ---------- FORMATACAO ----------
def linha_resultado(m):
    h = m["homeTeam"]["shortName"] or m["homeTeam"]["name"]
    a = m["awayTeam"]["shortName"] or m["awayTeam"]["name"]
    hs = m["score"]["fullTime"]["home"]
    as_ = m["score"]["fullTime"]["away"]
    return f"""<tr>
      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{h}</td>
      <td style="padding:6px 8px;text-align:center;border-bottom:1px solid #eee;font-weight:700;">{hs} - {as_}</td>
      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{a}</td>
    </tr>"""


def linha_jogo_hoje(m):
    h = m["homeTeam"]["shortName"] or m["homeTeam"]["name"]
    a = m["awayTeam"]["shortName"] or m["awayTeam"]["name"]
    hora_utc = m["utcDate"][11:16]
    try:
        hh, mm = map(int, hora_utc.split(":"))
        hora_local = f"{(hh + 1) % 24:02d}:{mm:02d}"
    except Exception:
        hora_local = hora_utc
    return f"""<tr>
      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{h}</td>
      <td style="padding:6px 8px;text-align:center;border-bottom:1px solid #eee;color:#888;">{hora_local}</td>
      <td style="padding:6px 8px;border-bottom:1px solid #eee;">{a}</td>
    </tr>"""


def bloco_competicao(nome, resultados, tabela, golos, hoje_jogos):
    partes = [f"""<h2 style="font-size:16px;color:#1f2d3d;margin:26px 0 10px;
      border-bottom:2px solid #eee;padding-bottom:6px;">{nome}</h2>"""]

    if resultados:
        linhas = "".join(linha_resultado(m) for m in resultados)
        partes.append(f"""
        <div style="font-size:12px;color:#888;margin-bottom:4px;">Resultados de ontem</div>
        <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden;margin-bottom:14px;">
          <tbody>{linhas}</tbody>
        </table>""")
    else:
        partes.append("<p style='color:#999;font-size:13px;'>Sem jogos ontem.</p>")

    if tabela:
        linhas = "".join(f"""<tr>
          <td style="padding:5px 8px;border-bottom:1px solid #eee;">{r['pos']}</td>
          <td style="padding:5px 8px;border-bottom:1px solid #eee;">{r['equipa']}</td>
          <td style="padding:5px 8px;text-align:right;border-bottom:1px solid #eee;">{r['jogos']}</td>
          <td style="padding:5px 8px;text-align:right;border-bottom:1px solid #eee;font-weight:700;">{r['pts']}</td>
          <td style="padding:5px 8px;text-align:right;border-bottom:1px solid #eee;color:#666;">{r['gd']:+d}</td>
        </tr>""" for r in tabela[:10])
        partes.append(f"""
        <div style="font-size:12px;color:#888;margin-bottom:4px;">Classificação (top 10)</div>
        <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden;margin-bottom:14px;">
          <thead><tr style="background:#1f2d3d;color:#fff;font-size:11px;">
            <th style="padding:5px 8px;text-align:left;">#</th>
            <th style="padding:5px 8px;text-align:left;">Equipa</th>
            <th style="padding:5px 8px;text-align:right;">J</th>
            <th style="padding:5px 8px;text-align:right;">Pts</th>
            <th style="padding:5px 8px;text-align:right;">DG</th>
          </tr></thead>
          <tbody>{linhas}</tbody>
        </table>""")

    if golos:
        linhas = "".join(f"""<tr>
          <td style="padding:5px 8px;border-bottom:1px solid #eee;">{g['jogador']}</td>
          <td style="padding:5px 8px;border-bottom:1px solid #eee;color:#666;">{g['equipa']}</td>
          <td style="padding:5px 8px;text-align:right;border-bottom:1px solid #eee;font-weight:700;">{g['golos']}</td>
        </tr>""" for g in golos)
        partes.append(f"""
        <div style="font-size:12px;color:#888;margin-bottom:4px;">Melhores marcadores</div>
        <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden;margin-bottom:14px;">
          <tbody>{linhas}</tbody>
        </table>""")

    if hoje_jogos:
        linhas = "".join(linha_jogo_hoje(m) for m in hoje_jogos)
        partes.append(f"""
        <div style="font-size:12px;color:#888;margin-bottom:4px;">Jogos de hoje (hora de Lisboa aprox.)</div>
        <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:6px;overflow:hidden;">
          <tbody>{linhas}</tbody>
        </table>""")
    else:
        partes.append("<p style='color:#999;font-size:13px;'>Sem jogos hoje.</p>")

    return "".join(partes)


def main():
    if not TOKEN:
        print("ERRO: falta a variavel FOOTBALL_DATA_TOKEN.", file=sys.stderr)
        sys.exit(1)

    hoje = dt.date.today()
    ontem = hoje - dt.timedelta(days=1)
    hoje_s, ontem_s = hoje.isoformat(), ontem.isoformat()

    blocos = []
    total_jogos_ontem = 0
    total_jogos_hoje = 0

    for codigo, nome in COMPETICOES:
        todos = jogos(codigo, ontem_s, hoje_s)
        resultados = [m for m in todos if m["utcDate"][:10] == ontem_s and m["status"] == "FINISHED"]
        hoje_jogos = [m for m in todos if m["utcDate"][:10] == hoje_s]
        tabela = classificacao(codigo)
        golos = marcadores(codigo)

        total_jogos_ontem += len(resultados)
        total_jogos_hoje += len(hoje_jogos)

        if not resultados and not tabela and not golos and not hoje_jogos:
            continue

        blocos.append(bloco_competicao(nome, resultados, tabela, golos, hoje_jogos))

    hoje_fmt = hoje.strftime("%d/%m/%Y")
    html = f"""<!DOCTYPE html>
<html lang="pt">
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#222;">
  <div style="max-width:600px;margin:0 auto;padding:24px;">
    <h1 style="font-size:21px;margin:0 0 2px;">Futebol &middot; {hoje_fmt}</h1>
    <p style="color:#666;margin:0 0 6px;font-size:14px;">
      Resultados de ontem, classificações, marcadores e jogos de hoje.
    </p>
    {''.join(blocos) if blocos else "<p style='color:#999;'>Sem informação disponível hoje.</p>"}
    <p style="color:#888;font-size:12px;margin-top:24px;line-height:1.5;">
      Ligas, Champions, Europeu e Mundial (plano gratuito). Taças, Liga Europa/Conference,
      Liga das Nações e Copa América não estão incluídas no plano atual.<br>
      Dados de football-data.org. Resumo automático.
    </p>
  </div>
</body>
</html>"""

    assunto = f"Futebol {hoje_fmt}: {total_jogos_ontem} resultado(s) ontem, {total_jogos_hoje} hoje"

    with open(CORPO, "w", encoding="utf-8") as f:
        f.write(html)
    with open(ASSUNTO, "w", encoding="utf-8") as f:
        f.write(assunto)

    print("OK:", assunto)


if __name__ == "__main__":
    main()
