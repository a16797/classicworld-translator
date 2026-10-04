"""Offline tests: synthetic credentials, temporary data, no billable API calls."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import settings
import winapi
import engine

FAKE_KEY = "test-key-" + "a" * 24


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "CWTranslator"
        self.file = self.directory / "settings.json"
        self.patches = [patch.object(settings, "USER_DIR", self.directory),
                        patch.object(settings, "SETTINGS_FILE", self.file),
                        patch.dict(os.environ, {"DEEPSEEK_API_KEY": FAKE_KEY})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def write_config(self, value):
        self.directory.mkdir(exist_ok=True)
        self.file.write_text(json.dumps(value), encoding="utf-8")

    def test_dpapi_round_trip_and_no_plaintext_on_disk(self):
        s = settings.Settings()
        s.set_api_key(FAKE_KEY)
        s.save()
        self.assertNotIn(FAKE_KEY, self.file.read_text(encoding="utf-8"))
        s = settings.Settings()
        self.assertEqual(s.api_key, FAKE_KEY)
        self.assertEqual(s.key_source, "saved")
        self.assertEqual(winapi.unprotect(base64.b64decode(s["api_key_protected"])).decode(), FAKE_KEY)

    def test_clear_disables_environment_persistently(self):
        s = settings.Settings()
        self.assertEqual(s.key_source, "environment")
        s.set_api_key(FAKE_KEY)
        s.set_api_key("")
        s.save()
        reloaded = settings.Settings()
        self.assertEqual(reloaded.api_key, "")
        self.assertEqual(reloaded.key_source, "none")
        reloaded["use_environment_key"] = True
        self.assertEqual(reloaded.api_key, FAKE_KEY)

    def test_bad_ciphertext_fails_closed_with_honest_status(self):
        for bad in ("%%%", base64.b64encode(b"not a DPAPI blob").decode()):
            self.write_config({"api_key_protected": bad})
            s = settings.Settings()
            self.assertEqual(s.api_key, "")
            self.assertEqual(s.key_source, "saved_unavailable")

    def test_corrupt_types_and_ranges(self):
        for payload in (None, [], {"timeout_s": "bad", "api_key_protected": 123},
                        {"timeout_s": -1, "return_delay_ms": 999999, "hotkey": "nope", "model": "\n"}):
            self.write_config(payload)
            s = settings.Settings()
            self.assertEqual(s["timeout_s"], settings.DEFAULTS["timeout_s"])
            self.assertEqual(s["hotkey"], settings.DEFAULTS["hotkey"])
            self.assertEqual(s["model"], settings.DEFAULTS["model"])
            s.save()

    def test_bad_key_never_reaches_network_or_disk(self):
        for bad in ("short", "test-key-aaa\r\nX-Evil: yes", "a" * 513, "a" * 20 + " b"):
            s = settings.Settings()
            with self.assertRaises(ValueError):
                s.set_api_key(bad)
            with patch.object(engine.ft, "generate") as generate:
                self.assertTrue(engine.Engine(s).test_key(bad))
                generate.assert_not_called()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "bad\r\n"}):
            self.assertEqual(settings.Settings().key_source, "environment_invalid")

    def test_key_test_unexpected_errors_are_sanitized(self):
        with patch.object(engine.ft, "generate", side_effect=RuntimeError(FAKE_KEY)):
            message = engine.Engine(settings.Settings()).test_key(FAKE_KEY)
        self.assertTrue(message)
        self.assertNotIn(FAKE_KEY, message)


class NetworkTests(unittest.TestCase):
    def test_only_fixed_https_origin_and_no_redirect(self):
        client = engine.ft.GenerationClient()
        with patch.object(client, "_open") as connect:
            with self.assertRaises(engine.ft.TranslationError):
                client.post("https://attacker.invalid", FAKE_KEY, {}, 1, "generation")
            connect.assert_not_called()
        with self.assertRaises(engine.ft.TranslationError):
            engine.ft.post_json("http://api.deepseek.com/chat/completions", FAKE_KEY, {}, 1, "generation")
        self.assertIsNone(engine.ft.NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid"))

    def test_offline_dictionary_and_vendor_import(self):
        self.assertEqual(Path(engine.ft.__file__).parent, ROOT / "vendor")
        self.assertEqual(Path(engine.lookup.__file__).parent, ROOT / "vendor")
        with patch.object(engine, "Usage"):
            s = settings.Settings()
            s.set_api_key("")
            e = engine.Engine(s)
            e.preload()
            with patch.object(e.client, "post") as network:
                self.assertEqual(e.translate("收蓝魔法鞋").text, "B> Blue Magicshoes")
                network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
