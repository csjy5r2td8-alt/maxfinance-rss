import io
import json
import os
import unittest
import importlib
from unittest.mock import patch
from urllib.error import HTTPError
import telegram_notify as notify


class Tests(unittest.TestCase):
    def test_existing_issue_is_delivered_on_retry(self):
        from unittest.mock import Mock
        for module_name, function, marker in [
            ('blog_alerta_github', 'issue_exists', 'maxfinance-blog-event:'),
            ('euribor_alerta_github', 'issue_exists', 'euribor-change-event:'),
            ('cambio_bhd_alerta', 'issue_already_exists', 'bhd-rate-change-id:'),
            ('dgii_check', 'issue_already_exists', 'dgii-notice-id:')]:
            module = importlib.import_module(module_name)
            session = Mock()
            issue = {'title':'Alerta','body':f'<!-- {marker}abc -->','html_url':'https://example.com'}
            session.get.return_value.json.return_value = [issue]
            with self.subTest(module=module_name), patch.object(module, 'notify_issue') as send:
                self.assertTrue(getattr(module, function)(session, 'owner/repo', 'token', 'abc'))
                send.assert_called_once_with(issue)

    def test_unchanged_euribor_stays_quiet(self):
        import euribor_alerta_github as module
        with patch.object(module,'make_session'), patch.object(module,'fetch_rates',return_value=('01/10/2026',{})), patch.object(module,'load_state',return_value={'taxas':{}}), patch.object(module,'find_changes',return_value=[]), patch.object(module,'notify_issue') as send:
            self.assertEqual(module.main(), 0)
            send.assert_not_called()

    def test_html_preserves_content_links_and_rows(self):
        text = notify.html_text('<head><style>hidden</style></head><h1>Notícias &amp; Tempo</h1><a href="https://example.com">Artigo</a><table><tr><td>Pombal</td><td>25°</td></tr><tr><td>Amanhã</td><td>20°</td></tr></table>')
        self.assertNotIn('hidden', text)
        self.assertIn('Notícias & Tempo', text)
        self.assertIn('https://example.com', text)
        self.assertIn('Pombal | 25°', text)
        self.assertIn('Amanhã | 20°', text)

    def test_unicode_chunks_preserve_all_content(self):
        text = '⚽á\n' * 4000
        parts = list(notify.chunks(text))
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(p.encode('utf-16-le')) // 2 <= 3500 for p in parts))

    def test_issue_removes_internal_markers(self):
        with patch.object(notify, 'send_message') as send:
            notify.notify_issue({'title':'Euribor','body':'Taxa 2% <!-- marker -->','html_url':'https://example.com'})
        self.assertIn('Taxa 2%', send.call_args.args[0])
        self.assertNotIn('marker', send.call_args.args[0])

    def test_failed_send_does_not_leak_token(self):
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN':'SECRET','TELEGRAM_CHAT_ID':'123'}), patch.object(notify, 'urlopen', side_effect=HTTPError('https://api.telegram.org/botSECRET/sendMessage',400,'bad',{},io.BytesIO())):
            with self.assertRaises(RuntimeError) as error:
                notify.send_message('test')
        self.assertNotIn('SECRET', str(error.exception))


if __name__ == '__main__': unittest.main()
