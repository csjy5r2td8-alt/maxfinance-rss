"""Monitoriza o preço anunciado, sem usar valores da descrição ou prestações."""
import argparse
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from telegram_notify import send_message

URL = 'https://www.olx.pt/d/anuncio/tesla-model-3-performance-full-extras-IDJzGPM.html'
STATE = Path('data/olx_tesla_preco.json')


def parse_price(content):
    soup = BeautifulSoup(content, 'html.parser')
    container = soup.select_one('[data-testid="ad-price-container"]')
    if container:
        match = re.search(r'([\d.,\s\u00a0]+)\s*€', container.get_text(' ', strip=True))
        if match:
            value = re.sub(r'[\s\u00a0.]', '', match.group(1)).replace(',', '.')
            price = Decimal(value)
            if price > 0:
                return str(price.quantize(Decimal('0.01')))
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nodes.extend(node.get('@graph', []))
            if node.get('@type') not in ('Product', 'Vehicle', 'Car'):
                continue
            offers = node.get('offers', {})
            offers = offers if isinstance(offers, list) else [offers]
            for offer in offers:
                if offer.get('priceCurrency') == 'EUR' and offer.get('price') is not None:
                    price = Decimal(str(offer['price']))
                    if price > 0:
                        return str(price.quantize(Decimal('0.01')))
    raise RuntimeError('Não foi encontrado o preço principal; referência anterior preservada.')


def fetch_price():
    response = requests.get(URL, timeout=40, headers={'User-Agent':'Mozilla/5.0 (compatible; PriceMonitor/1.0)'})
    if response.status_code in (403, 429):
        raise RuntimeError(f'OLX bloqueou a consulta automática (HTTP {response.status_code}). Não foi alterada a referência.')
    response.raise_for_status()
    if 'IDJzGPM' not in response.url:
        raise RuntimeError('Anúncio redirecionado/indisponível; referência preservada.')
    return parse_price(response.text)


def monitor(price):
    old = json.loads(STATE.read_text()) if STATE.exists() else None
    if old and old['price'] == price:
        print('Preço sem alterações.')
        return
    if old:
        difference = Decimal(price) - Decimal(old['price'])
        message = f"Tesla Model 3 Performance — preço alterado\nAnterior: {old['price']} €\nAtual: {price} €\nVariação: {difference:+.2f} €\n{URL}"
    else:
        message = f'Tesla Model 3 Performance — monitorização iniciada\nPreço de referência: {price} €\n{URL}'
    send_message(message)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps({'url':URL,'price':price,'checked_at':datetime.now(timezone.utc).isoformat()},indent=2)+'\n')
    temporary.replace(STATE)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    price = fetch_price()
    if args.dry_run:
        print('Preço principal:', price, 'EUR — sem envio ou alteração de referência')
    else:
        monitor(price)
