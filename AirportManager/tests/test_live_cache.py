"""Run: python3 -m unittest discover -s tests -p 'test_*.py'."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('airport_server', Path(__file__).resolve().parents[1] / 'hkia_live_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class CacheTests(unittest.TestCase):
    def test_live_endpoint_uses_cached_rows_without_network(self):
        request = object.__new__(server.Handler)
        request.path = '/api/live'
        request.wfile = io.BytesIO()
        request.send_response = lambda status: self.assertEqual(status, 200)
        request.send_header = lambda *args: None
        request.end_headers = lambda: None
        rows = [{'f': 'CX1', 'dir': 'D', 'time': '14:00'}]
        with patch.multiple(server, POLL_ROWS=rows, POLL_TS=time.time()-400), \
             patch.object(server, 'fetch_upstream', side_effect=AssertionError('Network on request path')), \
             patch.object(server, 'wx_now', side_effect=AssertionError('Weather on request path')), \
             patch.object(server, 'compute_pairs', return_value={}), \
             patch.object(server, 'load_reglog', return_value={}), \
             patch.object(server, 'common_types', return_value={}), \
             patch.object(server, 'load_arrgates', return_value={}), \
             patch.object(server, 'predict_runways', return_value=None):
            request.do_GET()
        result = json.loads(request.wfile.getvalue())
        self.assertEqual(result['rows'], rows)
        self.assertTrue(result['stale'])
        self.assertFalse(result['loading'])

    def test_lan_config_hides_saved_key(self):
        request = object.__new__(server.Handler)
        request.path = '/api/config'
        request.client_address = ('192.168.0.10', 50000)
        request.wfile = io.BytesIO()
        request.send_response = lambda status: self.assertEqual(status, 200)
        request.send_header = lambda *args: None
        request.end_headers = lambda: None
        with patch.dict(server.os.environ, {'GEO_KEY': 'test-private-key'}):
            request.do_GET()
        self.assertEqual(json.loads(request.wfile.getvalue()), {'geoKey': ''})

    def test_restore_cache_preserves_original_timestamp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'cache.json')
            path.write_text(json.dumps({'rows': [{'f': 'CX1'}], 'ts': 123}))
            with patch.multiple(server, LIVE_CACHE_PATH=str(path), POLL_ROWS=[], POLL_TS=0):
                server.restore_live_cache()
                self.assertEqual(server.POLL_ROWS, [{'f': 'CX1'}])
                self.assertEqual(server.POLL_TS, 123)

    def test_daily_archive_retains_both_directions_and_latest_status(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(server, 'DATA', folder):
            rows = [dict(date='2026-09-21', dir=d, f='CX1', time='14:00', status='Scheduled') for d in ('A', 'D')]
            server.save_daily_snapshots(rows)
            rows[0]['status'] = 'At gate 14:05'
            server.save_daily_snapshots([rows[0]])
            saved = json.loads(Path(folder, 'daily_snapshots', '2026-09-21.json').read_text())
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved[0]['status'], 'At gate 14:05')

if __name__ == '__main__':
    unittest.main()
