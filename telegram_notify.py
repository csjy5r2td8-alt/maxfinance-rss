"""Entrega comum de resumos e alertas ao Telegram, sem dependências externas."""
import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('style', 'script', 'head'):
            self.hidden += 1
        if self.hidden:
            return
        if tag == 'a':
            self.links.append(attrs.get('href', ''))
        if tag in ('div', 'p', 'tr', 'h1', 'h2', 'h3', 'li', 'br'):
            self.parts.append('\n')
        if tag in ('td', 'th'):
            self.parts.append(' | ')

    def handle_endtag(self, tag):
        if tag in ('style', 'script', 'head'):
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if tag == 'a' and self.links:
            link = self.links.pop()
            if link.startswith(('https://', 'http://')):
                self.parts.append('\n' + link + '\n')
        if tag in ('div', 'p', 'tr', 'h1', 'h2', 'h3', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(re.sub(r'\s+', ' ', data))

    def text(self):
        lines = [line.strip(' |') for line in ''.join(self.parts).splitlines()]
        return '\n'.join(line for line in lines if line)


def html_text(content):
    parser = TextHTML()
    parser.feed(content)
    return parser.text()


def chunks(text, limit=3500):
    current = []
    units = 0
    for char in text:
        size = 2 if ord(char) > 0xffff else 1
        if units + size > limit:
            yield ''.join(current)
            current, units = [], 0
        current.append(char)
        units += size
    if current:
        yield ''.join(current)


def send_message(text):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat:
        raise RuntimeError('Faltam TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID.')
    repository = os.environ.get('GITHUB_REPOSITORY', 'maxfinance-rss')
    for part in chunks(repository + '\n\n' + text):
        request = Request('https://api.telegram.org/bot' + token + '/sendMessage',
                          data=json.dumps({'chat_id': chat, 'text': part,
                                           'link_preview_options': {'is_disabled': True}}).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=40) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise RuntimeError('Telegram recusou a mensagem; verificar configuração.')
        except HTTPError as error:
            raise RuntimeError(f'Telegram HTTP {error.code}: verificar token, ID e /start no bot.') from None
        except (URLError, TimeoutError, ValueError):
            raise RuntimeError('Falha de ligação/resposta ao Telegram; consultar serviço antes de repetir.') from None
        time.sleep(0.1)
    print('Telegram: enviado')


def notify_issue(issue):
    body = re.sub(r'<!--.*?-->', '', issue.get('body') or '', flags=re.S).strip()
    send_message(issue.get('title', 'Novo alerta') + '\n\n' + body + '\n\n' + issue.get('html_url', ''))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html')
    parser.add_argument('--subject')
    parser.add_argument('--rss')
    args = parser.parse_args()
    if args.rss:
        root = ET.parse(args.rss).getroot()
        items = root.findall('.//item')
        text = 'Feed RSS Maxfinance atualizado\n\n' + '\n\n'.join(
            (item.findtext('title') or '') + '\n' + (item.findtext('link') or '') for item in items)
    elif args.html and args.subject:
        text = Path(args.subject).read_text(encoding='utf-8').strip() + '\n\n' + html_text(Path(args.html).read_text(encoding='utf-8'))
    else:
        parser.error('Usar --html e --subject, ou --rss')
    send_message(text)


if __name__ == '__main__':
    main()
