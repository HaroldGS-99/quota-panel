import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import collector
import providers
from model import remaining_percent, timestamp


class NormalizationTests(unittest.TestCase):
    def test_codex_actual_windows_multiple_buckets_and_reset_count(self):
        data = providers.normalize_codex({"rateLimitsByLimitId": {
            "codex": {"primary": {"usedPercent": 70, "windowDurationMins": 300, "resetsAt": 2000000000},
                      "secondary": {"usedPercent": 91, "windowDurationMins": 10080}},
            "review": {"limitName": "Reviews", "primary": {"usedPercent": 12, "windowDurationMins": 60}}},
            "rateLimitResetCredits": {"availableCount": 2, "credits": []}})
        self.assertEqual([q["label"] for q in data["quotas"]], ["5 horas", "Semanal", "60 min"])
        self.assertEqual(data["resetsAvailable"], 2)
        self.assertIsNone(data["quotas"][1]["resetsAt"])
        self.assertEqual(data["quotas"][2]["group"], "Reviews")

    def test_codex_legacy_and_missing_resets(self):
        for count in [None, 0, 3]:
            data = providers.normalize_codex({"rateLimits": {"primary": {"usedPercent": 0, "windowDurationMins": 300}},
                                             "rateLimitResetCredits": {"availableCount": count}})
            self.assertEqual(data["resetsAvailable"], count)
            self.assertEqual(data["quotas"][0]["usedPercent"], 0)
        self.assertEqual(providers.normalize_codex({})["status"], "unavailable")

    def test_opencode_three_windows_with_iso_resets_and_model_breakdown(self):
        item = {"percent": 90, "resetsAt": "2026-10-02T00:00:00Z"}
        data = providers.normalize_opencode({"usage": {"rolling": item, "weekly": item, "monthly": item},
                                             "models": {"test-model": {"usage": {"rolling": item}}}})
        self.assertEqual(len(data["quotas"]), 4)
        self.assertEqual(data["quotas"][2]["label"], "Mensual")
        self.assertEqual(data["quotas"][3]["group"], "test-model")
        self.assertEqual(data["quotas"][0]["resetsAt"], 1790899200)

    def test_missing_windows_are_not_fabricated(self):
        data = providers.normalize_opencode({"usage": {"rolling": {"status": "ok"}}})
        self.assertEqual(len(data["quotas"]), 1)
        self.assertIsNone(data["quotas"][0]["usedPercent"])

    def test_antigravity_shared_group_is_not_sum_of_models(self):
        data = providers.normalize_antigravity({"groups": [
            {"displayName": "GEMINI MODELS", "description": "Gemini Flash, Gemini Pro", "buckets": [
                {"bucketId": "gemini-5h", "window": "5 hours", "remainingFraction": 0.3,
                 "resetTime": "2026-10-02T00:00:00Z"},
                {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": 0.05}]},
            {"displayName": "Claude Models", "buckets": [{"window": "5 hours", "remainingFraction": 0}]}]})
        self.assertEqual(len(data["quotas"]), 2)
        self.assertEqual(data["quotas"][0]["usedPercent"], 70)
        self.assertEqual(data["quotas"][1]["usedPercent"], 95)
        self.assertEqual(data["quotas"][1]["label"], "Semanal")
        self.assertTrue(all(q["group"] == "Gemini Models" for q in data["quotas"]))

    def test_antigravity_does_not_substitute_per_model_or_daily_gemini_cli_quotas(self):
        data = providers.normalize_antigravity({"models": {"gemini-pro": {"quotaInfo": {"remainingFraction": 1}}}})
        self.assertEqual(data["status"], "unavailable")
        self.assertEqual(data["quotas"], [])

    def test_antigravity_only_known_window_and_fraction(self):
        data = providers.normalize_antigravity({"groups": [{"displayName": "Gemini Models", "buckets": [
            {"window": "daily", "remainingFraction": 4, "resetTime": "invalid", "disabled": True}]}]})
        q = data["quotas"][0]
        self.assertEqual(q["label"], "daily")
        self.assertIsNone(q["windowMinutes"])
        self.assertIsNone(q["usedPercent"])
        self.assertIsNone(q["resetsAt"])
        self.assertTrue(q["disabled"])

    def test_invalid_numbers_and_timestamps(self):
        for value in [None, "0.5", True, float("nan"), -1, 2]:
            self.assertIsNone(remaining_percent(value))
        self.assertEqual(remaining_percent(1), 0)
        self.assertEqual(remaining_percent(0), 100)
        self.assertIsNone(timestamp(float("nan")))
        self.assertIsNone(timestamp(True))
        self.assertEqual(timestamp({"seconds": "2000000000"}), 2000000000)


class IntegrationTests(unittest.TestCase):
    def test_codex_stdio_handshake_and_child_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / "codex"
            cli.write_text('''#!/usr/bin/python3
import json,sys
for line in sys.stdin:
 message=json.loads(line)
 if message['method']=='initialize':
  print(json.dumps({'id':1,'result':{}}),flush=True)
 if message['method']=='account/rateLimits/read':
  print(json.dumps({'id':2,'result':{'rateLimits':{'primary':{'usedPercent':42,'windowDurationMins':300}}}}),flush=True)
''')
            cli.chmod(0o700)
            data = providers.codex({"codexPath": str(cli)})
            self.assertEqual(data["quotas"][0]["usedPercent"], 42)
            self.assertFalse(providers.ACTIVE_CHILDREN)

    def test_opencode_reads_only_go_key_and_calls_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "opencode"
            p.mkdir()
            (p / "auth.json").write_text(json.dumps({"opencode-go": {"type": "api", "key": "fixture-secret"},
                                                    "openai": {"type": "api", "key": "wrong"}}))
            with patch.dict(os.environ, {"XDG_DATA_HOME": directory}), patch.object(providers, 'http_json', return_value={"usage": {}}) as request:
                providers.opencode({})
                request.assert_called_once_with("https://opencode.ai/zen/go/v1/usage", "fixture-secret")

    def test_antigravity_builtin_cli_command_zero_model_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / 'agy'
            cli.write_text('''#!/usr/bin/python3
import json, sys
assert sys.argv[1:] == ['--print', '/usage', '--output-format', 'json']
print(json.dumps({'status': 'SUCCESS', 'num_turns': 0, 'command': {'name': 'usage', 'data': {
 'groups': [{'name': 'Gemini Models', 'buckets': [
  {'id': 'gemini-weekly', 'window': 'weekly', 'remaining_fraction': 1,
   'reset_time': '2026-10-08T19:04:36Z'},
  {'id': 'gemini-5h', 'window': '5h', 'remaining_fraction': 0.75}]}]}}}))
''')
            cli.chmod(0o700)
            with patch.dict(os.environ, {'XDG_CACHE_HOME': directory}):
                data = providers.antigravity({'agyPath': str(cli)})
            self.assertEqual(data['status'], 'ok')
            self.assertEqual([q['usedPercent'] for q in data['quotas']], [0, 25])
            self.assertEqual([q['windowMinutes'] for q in data['quotas']], [10080, 300])
            self.assertIsNotNone(data['quotas'][0]['resetsAt'])
            self.assertFalse(providers.ACTIVE_CHILDREN)

    def test_antigravity_rejects_unstructured_or_model_response(self):
        for payload in ({'status': 'SUCCESS', 'response': 'fixture-secret', 'num_turns': 1},
                        {'status': 'ERROR', 'error': 'fixture-secret'}):
            with tempfile.TemporaryDirectory() as directory:
                cli = Path(directory) / 'agy'
                cli.write_text('#!/usr/bin/python3\nprint(' + repr(json.dumps(payload)) + ')\n')
                cli.chmod(0o700)
                with patch.dict(os.environ, {'XDG_CACHE_HOME': directory}):
                    data = collector.collect_one('antigravity', {'agyPath': str(cli)})
                self.assertNotEqual(data['status'], 'ok')
                self.assertNotIn('fixture-secret', json.dumps(data))
                self.assertFalse(providers.ACTIVE_CHILDREN)

    def test_network_errors_do_not_expose_credentials(self):
        for code, expected in [(401, 'auth'), (403, 'unavailable'), (429, 'throttled'), (503, 'offline')]:
            error = urllib.error.HTTPError('https://example.test/fixture-secret', code, 'fixture-secret', {}, io.BytesIO())
            with patch.object(providers, 'opencode', side_effect=error):
                data = collector.collect_one('opencode', {})
            self.assertEqual(data['status'], expected)
            self.assertNotIn('fixture-secret', json.dumps(data))
        with patch.object(providers, 'opencode', side_effect=RuntimeError('fixture-secret')):
            self.assertNotIn('fixture-secret', json.dumps(collector.collect_one('opencode', {})))

    def test_helper_sigterm_removes_running_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / 'codex'
            pid = Path(directory) / 'pid'
            cli.write_text(f'''#!/usr/bin/python3
import os,time
from pathlib import Path
Path({str(pid)!r}).write_text(str(os.getpid()))
time.sleep(60)
''')
            cli.chmod(0o700)
            proc = subprocess.Popen([sys.executable, str(Path(collector.__file__))], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                proc.stdin.write((json.dumps({'providers': ['codex'], 'codexPath': str(cli)}) + '\n').encode())
                proc.stdin.flush()
                for _ in range(100):
                    if pid.exists(): break
                    time.sleep(.02)
                self.assertTrue(pid.exists())
                child = int(pid.read_text())
                proc.terminate()
                proc.wait(timeout=5)
                with self.assertRaises(ProcessLookupError): os.kill(child, 0)
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
                proc.stdin.close(); proc.stdout.close()


if __name__ == '__main__':
    unittest.main()
