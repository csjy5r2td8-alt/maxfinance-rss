#!/usr/bin/env python3
"""
Resumo diario de futebol por email.
Para cada competicao (das que o plano gratuito da football-data.org permite):
  - resultados de ontem
  - jogos de hoje
  - classificacao atual
  - melhores marcadores
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
 
# Competicoes confirmadas como disponiveis no plano gratuito (TIER_ONE),
# com a bandeira do pais/area e uma cor de destaque propria para cada uma.
COMPETICOES = [
    ("PPL", "Liga Portugal", "https://crests.football-data.org/765.svg", "#0b6b3a"),
    ("PL", "Premier League", "https://crests.football-data.org/770.svg", "#3d195b"),
    ("PD", "La Liga", "https://crests.football-data.org/760.svg", "#ee8707"),
    ("SA", "Serie A", "https://crests.football-data.org/784.svg", "#0068a8"),
    ("BL1", "Bundesliga", "https://crests.football-data.org/759.svg", "#d20515"),
    ("FL1", "Ligue 1", "https://crests.football-data.org/773.svg", "#0055a4"),
    ("CL", "Champions League", "https://crests.football-data.org/EUR.svg", "#0e1e5b"),
    ("EC", "Europeu", "https://crests.football-data.org/EUR.svg", "#1a3e8c"),
    ("WC", "Mundial", None, "#b8860b"),
]
 
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
                        "escudo": r["team"].get("crest"),
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
                "escudo": s["team"].get("crest") if s.get("team") else None,
                "golos": s["goals"]} for s in data.get("scorers", [])]
    except Exception as e:
        print(f"Aviso: sem marcadores para {codigo}: {e}", file=sys.stderr)
        return []
 
 
def escudo_img(url, tam=22):
    if not url:
        return (f'<span style="display:inline-block;width:{tam}px;height:{tam}px;'
                f'vertical-align:middle;"></span>')
    return (f'<img src="{url}" width="{tam}" height="{tam}" alt="" '
            f'style="vertical-align:middle;object-fit:contain;">')
 
 
def nome_curto(t):
    return t["shortName"] or t["name"]
 
 
def cartao_resultado(m, cor):
    h = nome_curto(m["homeTeam"])
    a = nome_curto(m["awayTeam"])
    eh = escudo_img(m["homeTeam"].get("crest"), 26)
    ea = escudo_img(m["awayTeam"].get("crest"), 26)
    hs = m["score"]["fullTime"]["home"]
    as_ = m["score"]["fullTime"]["away"]
    venceu_casa = hs is not None and as_ is not None and hs > as_
    venceu_fora = hs is not None and as_ is not None and as_ > hs
    peso_h = "700" if venceu_casa else "400"
    peso_a = "700" if venceu_fora else "400"
    cor_h = "#1a1a1a" if venceu_casa else "#8a8a8a"
    cor_a = "#1a1a1a" if venceu_fora else "#8a8a8a"
    return f"""
    <table role="presentation" style="width:100%;border-collapse:collapse;margin-bottom:8px;">
      <tr>
        <td style="width:42%;text-align:right;padding:10px 10px 10px 4px;font-size:13.5px;font-weight:{peso_h};color:{cor_h};">
          {h} {eh}
        </td>
        <td style="width:16%;text-align:center;padding:0;">
          <span style="display:inline-block;min-width:50px;padding:5px 8px;border-radius:8px;
            background:{cor}0d;color:{cor};font-weight:800;font-size:15px;border:1.5px solid {cor}33;">
            {hs} &ndash; {as_}
          </span>
        </td>
        <td style="width:42%;text-align:left;padding:10px 4px 10px 10px;font-size:13.5px;font-weight:{peso_a};color:{cor_a};">
          {ea} {a}
        </td>
      </tr>
    </table>"""
 
 
def cartao_jogo_hoje(m, cor):
    h = nome_curto(m["homeTeam"])
    a = nome_curto(m["awayTeam"])
    eh = escudo_img(m["homeTeam"].get("crest"), 24)
    ea = escudo_img(m["awayTeam"].get("crest"), 24)
    hora_utc = m["utcDate"][11:16]
    try:
        hh, mm = map(int, hora_utc.split(":"))
        hora_local = f"{(hh + 1) % 24:02d}:{mm:02d}"
    except Exception:
        hora_local = hora_utc
    return f"""
    <table role="presentation" style="width:100%;border-collapse:collapse;margin-bottom:6px;">
      <tr>
        <td style="width:42%;text-align:right;padding:8px 10px 8px 4px;font-size:13px;color:#333;">
          {h} {eh}
        </td>
        <td style="width:16%;text-align:center;padding:0;">
          <span style="display:inline-block;min-width:46px;padding:3px 6px;border-radius:7px;
            background:#f2f2f4;color:#666;font-weight:700;font-size:12px;">
            &#9200; {hora_local}
          </span>
        </td>
        <td style="width:42%;text-align:left;padding:8px 4px 8px 10px;font-size:13px;color:#333;">
          {ea} {a}
        </td>
      </tr>
    </table>"""
 
 
def linha_classificacao(r):
    medalha = {1: "&#129351;", 2: "&#129352;", 3: "&#129353;"}.get(r["pos"], "")
    fundo = {1: "#fff8e1", 2: "#f7f7f9", 3: "#fdf0e6"}.get(r["pos"], "#fff")
    peso = "700" if r["pos"] <= 3 else "500"
    return f"""<tr style="background:{fundo};">
      <td style="padding:7px 8px;border-bottom:1px solid #eee;font-size:12.5px;color:#555;width:26px;">{medalha or r['pos']}</td>
      <td style="padding:7px 8px;border-bottom:1px solid #eee;font-size:13px;font-weight:{peso};">{escudo_img(r['escudo'], 18)} {r['equipa']}</td>
      <td style="padding:7px 8px;text-align:right;border-bottom:1px solid #eee;font-size:12.5px;color:#888;">{r['jogos']}</td>
      <td style="padding:7px 8px;text-align:right;border-bottom:1px solid #eee;font-size:13.5px;font-weight:800;">{r['pts']}</td>
      <td style="padding:7px 8px;text-align:right;border-bottom:1px solid #eee;font-size:12px;color:#999;">{r['gd']:+d}</td>
    </tr>"""
 
 
def linha_marcador(g, i, cor):
    return f"""<tr>
      <td style="padding:7px 8px;border-bottom:1px solid #f2f2f2;font-size:12px;color:{cor};font-weight:800;width:20px;">{i}</td>
      <td style="padding:7px 8px;border-bottom:1px solid #f2f2f2;font-size:13px;">
        {g['jogador']}<br><span style="font-size:11px;color:#999;">{escudo_img(g['escudo'], 14)} {g['equipa']}</span>
      </td>
      <td style="padding:7px 8px;text-align:right;border-bottom:1px solid #f2f2f2;font-size:13px;font-weight:800;color:#1a1a1a;">
        &#9917; {g['golos']}
      </td>
    </tr>"""
 
 
def secao_titulo(txt, cor):
    return (f'<div style="font-size:11px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;'
            f'color:{cor};margin:16px 0 8px;">{txt}</div>')
 
 
def bloco_competicao(nome, bandeira, cor, resultados, hoje_jogos, tabela, golos):
    bandeira_img = escudo_img(bandeira, 24) if bandeira else ""
 
    corpo = []
 
    corpo.append(secao_titulo("Resultados de ontem", cor))
    if resultados:
        corpo.append("".join(cartao_resultado(m, cor) for m in resultados))
    else:
        corpo.append("<p style='color:#aaa;font-size:12.5px;margin:0 0 8px;'>Sem jogos ontem.</p>")
 
    corpo.append(secao_titulo("Jogos de hoje", cor))
    if hoje_jogos:
        corpo.append("".join(cartao_jogo_hoje(m, cor) for m in hoje_jogos))
    else:
        corpo.append("<p style='color:#aaa;font-size:12.5px;margin:0 0 8px;'>Sem jogos hoje.</p>")
 
    if tabela:
        corpo.append(secao_titulo("Classificação", cor))
        linhas = "".join(linha_classificacao(r) for r in tabela[:10])
        corpo.append(f'<table style="width:100%;border-collapse:collapse;"><tbody>{linhas}</tbody></table>')
 
    if golos:
        corpo.append(secao_titulo("Melhores marcadores", cor))
        linhas = "".join(linha_marcador(g, i + 1, cor) for i, g in enumerate(golos))
        corpo.append(f'<table style="width:100%;border-collapse:collapse;"><tbody>{linhas}</tbody></table>')
 
    return f"""
    <div style="background:#fff;border-radius:14px;overflow:hidden;margin-bottom:18px;
      box-shadow:0 1px 4px rgba(0,0,0,0.07);border:1px solid #eee;">
      <div style="background:{cor};padding:14px 18px;">
        <span style="color:#fff;font-size:15.5px;font-weight:700;vertical-align:middle;">{bandeira_img} {nome}</span>
      </div>
      <div style="padding:6px 18px 18px;">
        {''.join(corpo)}
      </div>
    </div>"""
 
 
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
 
    for codigo, nome, bandeira, cor in COMPETICOES:
        todos = jogos(codigo, ontem_s, hoje_s)
        resultados = [m for m in todos if m["utcDate"][:10] == ontem_s and m["status"] == "FINISHED"]
        hoje_jogos = [m for m in todos if m["utcDate"][:10] == hoje_s]
        tabela = classificacao(codigo)
        golos = marcadores(codigo)
 
        total_jogos_ontem += len(resultados)
        total_jogos_hoje += len(hoje_jogos)
 
        if not resultados and not tabela and not golos and not hoje_jogos:
            continue
 
        blocos.append(bloco_competicao(nome, bandeira, cor, resultados, hoje_jogos, tabela, golos))
 
    hoje_fmt = hoje.strftime("%d/%m/%Y")
    dia_semana = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][hoje.weekday()]
 
    resumo_pills = (
        f'<span style="display:inline-block;background:rgba(255,255,255,.18);color:#fff;'
        f'font-size:12px;font-weight:700;padding:5px 12px;border-radius:20px;margin-right:8px;">'
        f'&#9917; {total_jogos_ontem} resultado{"s" if total_jogos_ontem != 1 else ""}</span>'
        f'<span style="display:inline-block;background:rgba(255,255,255,.18);color:#fff;'
        f'font-size:12px;font-weight:700;padding:5px 12px;border-radius:20px;">'
        f'&#128197; {total_jogos_hoje} hoje</span>'
    )
 
    html = f"""<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#eef0f3;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222;">
  <div style="max-width:600px;margin:0 auto;">
 
    <div style="background:linear-gradient(135deg,#0e1e5b,#1a3e8c);padding:28px 24px 22px;border-radius:0 0 18px 18px;">
      <div style="font-size:22px;font-weight:800;color:#fff;letter-spacing:-.3px;">&#9917; Resumo de Futebol</div>
      <div style="font-size:13px;color:#c9d4f0;margin:2px 0 14px;text-transform:capitalize;">{dia_semana}-feira, {hoje_fmt}</div>
      {resumo_pills}
    </div>
 
    <div style="padding:20px 16px 8px;">
      {''.join(blocos) if blocos else "<p style='color:#999;text-align:center;'>Sem informação disponível hoje.</p>"}
 
      <p style="color:#9aa0a6;font-size:11px;margin-top:8px;line-height:1.6;text-align:center;">
        Ligas, Champions, Europeu e Mundial (plano gratuito).<br>
        Taças, Liga Europa/Conference, Liga das Nações e Copa América não incluídas.<br>
        Dados de football-data.org &middot; Resumo automático
      </p>
    </div>
  </div>
</body>
</html>"""
 
    assunto = f"⚽ Futebol {hoje_fmt}: {total_jogos_ontem} resultado(s) ontem, {total_jogos_hoje} hoje"
 
    with open(CORPO, "w", encoding="utf-8") as f:
        f.write(html)
    with open(ASSUNTO, "w", encoding="utf-8") as f:
        f.write(assunto)
 
    print("OK:", assunto)
 
 
if __name__ == "__main__":
    main()
 



