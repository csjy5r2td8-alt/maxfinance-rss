#!/usr/bin/env python3
"""
Resumo diario por email:
  - Noticias mais importantes: mundo e Portugal (via Google News RSS)
  - Previsao do tempo: hoje e proximos 7 dias, para Pombal e Santo Domingo
    (via Open-Meteo, gratuito e sem chave)
"""
 
import sys
import datetime as dt
import xml.etree.ElementTree as ET
 
import requests
 
CORPO = "noticias_tempo_body.html"
ASSUNTO = "noticias_tempo_subject.txt"
 
UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-PT,pt;q=0.9",
}
 
# --- Noticias: feeds do Google News (publicos, sem chave) ---
FEED_MUNDO = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=pt-PT&gl=PT&ceid=PT:pt"
FEED_PORTUGAL = "https://news.google.com/rss?hl=pt-PT&gl=PT&ceid=PT:pt"
FEED_RD = "https://news.google.com/rss?hl=es-DO&gl=DO&ceid=DO:es"
FEED_DESPORTO = "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=pt-PT&gl=PT&ceid=PT:pt"
FEED_SPORTING = ('https://news.google.com/rss/search?q=%22Sporting+CP%22+OR+%22Sporting+'
                 'Clube+de+Portugal%22&hl=pt-PT&gl=PT&ceid=PT:pt')
N_NOTICIAS = 6
 
# --- Tempo: locais (nome, latitude, longitude, bandeira) ---
LOCAIS = [
    ("Pombal", 39.9167, -8.6167, "&#127477;&#127481;"),
    ("Santo Domingo", 18.4861, -69.9312, "&#127465;&#127476;"),
]
 
# Codigos de tempo da Open-Meteo (padrao WMO) -> (emoji, descricao)
WMO = {
    0: ("&#9728;", "Céu limpo"),
    1: ("&#127774;", "Pouco nublado"),
    2: ("&#9925;", "Parcialmente nublado"),
    3: ("&#9729;", "Nublado"),
    45: ("&#127787;", "Nevoeiro"),
    48: ("&#127787;", "Nevoeiro gelado"),
    51: ("&#127783;", "Chuvisco fraco"),
    53: ("&#127783;", "Chuvisco"),
    55: ("&#127783;", "Chuvisco forte"),
    61: ("&#127783;", "Chuva fraca"),
    63: ("&#127783;", "Chuva"),
    65: ("&#127783;", "Chuva forte"),
    71: ("&#10052;", "Neve fraca"),
    73: ("&#10052;", "Neve"),
    75: ("&#10052;", "Neve forte"),
    80: ("&#127783;", "Aguaceiros fracos"),
    81: ("&#127783;", "Aguaceiros"),
    82: ("&#9928;", "Aguaceiros fortes"),
    95: ("&#9928;", "Trovoada"),
    96: ("&#9928;", "Trovoada com granizo"),
    99: ("&#9928;", "Trovoada forte"),
}
 
 
def icone_tempo(codigo):
    return WMO.get(codigo, ("&#9729;", "—"))
 
 
# ---------- NOTICIAS ----------
def get_noticias(url, limite=N_NOTICIAS):
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        itens = []
        for item in root.findall(".//item")[:limite]:
            titulo = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            fonte_el = item.find("source")
            fonte = fonte_el.text.strip() if fonte_el is not None and fonte_el.text else ""
            if fonte and titulo.endswith(f" - {fonte}"):
                titulo = titulo[: -(len(fonte) + 3)].strip()
            elif not fonte and " - " in titulo:
                titulo, fonte = titulo.rsplit(" - ", 1)
            itens.append({"titulo": titulo, "link": link, "fonte": fonte})
        return itens
    except Exception as e:
        print(f"Aviso: falha a ler noticias de {url}: {e}", file=sys.stderr)
        return []
 
 
# ---------- TEMPO ----------
def get_tempo(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=auto&forecast_days=8"
    )
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        data = r.json()["daily"]
        dias = []
        for i in range(len(data["time"])):
            dias.append({
                "data": data["time"][i],
                "codigo": data["weathercode"][i],
                "tmax": round(data["temperature_2m_max"][i]),
                "tmin": round(data["temperature_2m_min"][i]),
                "chuva": data["precipitation_probability_max"][i],
            })
        return dias
    except Exception as e:
        print(f"Aviso: falha a ler tempo ({lat},{lon}): {e}", file=sys.stderr)
        return []
 
 
# ---------- FORMATACAO ----------
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
 
 
def nome_dia(data_iso, indice):
    if indice == 0:
        return "Hoje"
    if indice == 1:
        return "Amanhã"
    d = dt.date.fromisoformat(data_iso)
    return DIAS_SEMANA[d.weekday()]
 
 
def cartao_tempo(nome, bandeira, dias):
    if not dias:
        return f"""
        <div style="background:#fff;border-radius:14px;padding:18px;margin-bottom:14px;
          box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;">
          <div style="font-size:14px;font-weight:700;">{bandeira} {nome}</div>
          <p style="color:#999;font-size:12.5px;margin:8px 0 0;">Sem dados disponíveis hoje.</p>
        </div>"""
 
    hoje = dias[0]
    emoji_h, desc_h = icone_tempo(hoje["codigo"])
 
    resto = dias[1:8]
    dias_html = "".join(f"""
      <td style="text-align:center;padding:8px 4px;">
        <div style="font-size:10.5px;color:#888;margin-bottom:4px;">{nome_dia(d['data'], i + 1)}</div>
        <div style="font-size:19px;">{icone_tempo(d['codigo'])[0]}</div>
        <div style="font-size:11.5px;font-weight:700;margin-top:2px;">{d['tmax']}&deg;</div>
        <div style="font-size:10.5px;color:#999;">{d['tmin']}&deg;</div>
      </td>""" for i, d in enumerate(resto))
 
    return f"""
    <div style="background:#fff;border-radius:14px;overflow:hidden;margin-bottom:14px;
      box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;">
      <div style="background:linear-gradient(135deg,#1e88c7,#4fb3e8);padding:16px 18px;color:#fff;">
        <div style="font-size:14.5px;font-weight:700;">{bandeira} {nome}</div>
        <table role="presentation" style="width:100%;margin-top:8px;">
          <tr>
            <td style="font-size:38px;vertical-align:middle;">{emoji_h}</td>
            <td style="vertical-align:middle;padding-left:8px;">
              <div style="font-size:26px;font-weight:800;line-height:1;">{hoje['tmax']}&deg; <span style="font-size:15px;font-weight:400;opacity:.8;">/ {hoje['tmin']}&deg;</span></div>
              <div style="font-size:12px;opacity:.9;margin-top:3px;">{desc_h} &middot; &#128167; {hoje['chuva']}%</div>
            </td>
          </tr>
        </table>
      </div>
      <table role="presentation" style="width:100%;border-collapse:collapse;">
        <tr>{dias_html}</tr>
      </table>
    </div>"""
 
 
def lista_noticias(itens):
    if not itens:
        return "<p style='color:#999;font-size:12.5px;'>Sem notícias disponíveis.</p>"
    linhas = []
    for n in itens:
        fonte_html = f"<span style='color:#999;font-size:11px;'> &middot; {n['fonte']}</span>" if n["fonte"] else ""
        linhas.append(f"""
        <div style="padding:10px 0;border-bottom:1px solid #f0f0f0;">
          <a href="{n['link']}" style="color:#1a1a1a;font-size:13.5px;font-weight:600;text-decoration:none;line-height:1.4;">
            {n['titulo']}
          </a>{fonte_html}
        </div>""")
    return "".join(linhas)
 
 
def secao_titulo(txt, emoji):
    return (f'<div style="font-size:15.5px;font-weight:800;margin:22px 0 4px;color:#1a1a1a;">'
            f'{emoji} {txt}</div>')
 
 
def main():
    hoje = dt.date.today()
    hoje_fmt = hoje.strftime("%d/%m/%Y")
    dia_semana = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][hoje.weekday()]
 
    noticias_mundo = get_noticias(FEED_MUNDO)
    noticias_pt = get_noticias(FEED_PORTUGAL)
    noticias_rd = get_noticias(FEED_RD)
    noticias_desporto = get_noticias(FEED_DESPORTO)
    noticias_sporting = get_noticias(FEED_SPORTING)
 
    cartoes_tempo = "".join(
        cartao_tempo(nome, bandeira, get_tempo(lat, lon))
        for nome, lat, lon, bandeira in LOCAIS
    )
 
    html = f"""<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#eef0f3;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222;">
  <div style="max-width:600px;margin:0 auto;">
 
    <div style="background:linear-gradient(135deg,#232526,#414345);padding:26px 24px 20px;border-radius:0 0 18px 18px;">
      <div style="font-size:21px;font-weight:800;color:#fff;">&#128240; Notícias &amp; Tempo</div>
      <div style="font-size:13px;color:#c9c9c9;margin-top:2px;text-transform:capitalize;">{dia_semana}-feira, {hoje_fmt}</div>
    </div>
 
    <div style="padding:18px 16px 8px;">
 
      {secao_titulo('Previsão do tempo', '&#127780;')}
      {cartoes_tempo}
 
      {secao_titulo('Notícias do Mundo', '&#127760;')}
      <div style="background:#fff;border-radius:14px;padding:6px 16px;box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;margin-bottom:6px;">
        {lista_noticias(noticias_mundo)}
      </div>
 
      {secao_titulo('Notícias de Portugal', '&#127477;&#127481;')}
      <div style="background:#fff;border-radius:14px;padding:6px 16px;box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;margin-bottom:6px;">
        {lista_noticias(noticias_pt)}
      </div>
 
      {secao_titulo('Notícias da República Dominicana', '&#127465;&#127476;')}
      <div style="background:#fff;border-radius:14px;padding:6px 16px;box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;margin-bottom:6px;">
        {lista_noticias(noticias_rd)}
      </div>
 
      {secao_titulo('Desporto', '&#127942;')}
      <div style="background:#fff;border-radius:14px;padding:6px 16px;box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;margin-bottom:6px;">
        {lista_noticias(noticias_desporto)}
      </div>
 
      <div style="margin:22px 0 4px;padding:10px 14px;background:linear-gradient(135deg,#0a6b34,#0f8a44);border-radius:12px 12px 0 0;">
        <span style="font-size:15.5px;font-weight:800;color:#fff;">&#127937; Sporting Clube de Portugal</span>
      </div>
      <div style="background:#fff;border-radius:0 0 14px 14px;padding:6px 16px;box-shadow:0 1px 4px rgba(0,0,0,0.06);border:1px solid #eee;border-top:none;margin-bottom:6px;">
        {lista_noticias(noticias_sporting)}
      </div>
 
      <p style="color:#9aa0a6;font-size:11px;margin-top:18px;line-height:1.6;text-align:center;">
        Tempo: Open-Meteo. Notícias: Google News.<br>Resumo automático.
      </p>
    </div>
  </div>
</body>
</html>"""
 
    assunto = f"📰🌤️ Notícias & Tempo — {hoje_fmt}"
 
    with open(CORPO, "w", encoding="utf-8") as f:
        f.write(html)
    with open(ASSUNTO, "w", encoding="utf-8") as f:
        f.write(assunto)
 
    print("OK:", assunto)
    print(f"  Notícias mundo: {len(noticias_mundo)} | Portugal: {len(noticias_pt)}")
 
 
if __name__ == "__main__":
    main()
 



