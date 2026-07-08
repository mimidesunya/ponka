import sys
import types
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ponka.gemini_client import create_gemini_client, should_use_vertex_ai  # noqa: E402


class GeminiClientConfigTest(unittest.TestCase):
    def test_adc_auth_selects_vertex_ai_client(self):
        calls = []

        class FakeClient:
            def __init__(self, **kwargs):
                calls.append(kwargs)

        google_module = types.ModuleType("google")
        genai_module = types.ModuleType("google.genai")
        genai_module.Client = FakeClient
        google_module.genai = genai_module
        previous_google = sys.modules.get("google")
        previous_genai = sys.modules.get("google.genai")
        sys.modules["google"] = google_module
        sys.modules["google.genai"] = genai_module
        try:
            create_gemini_client(
                {
                    "auth": "adc",
                    "project": "test-project",
                    "location": "global",
                    "httpTimeoutMs": 120000,
                }
            )
        finally:
            if previous_google is None:
                sys.modules.pop("google", None)
            else:
                sys.modules["google"] = previous_google
            if previous_genai is None:
                sys.modules.pop("google.genai", None)
            else:
                sys.modules["google.genai"] = previous_genai

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["vertexai"])
        self.assertEqual(calls[0]["project"], "test-project")
        self.assertEqual(calls[0]["location"], "global")
        self.assertEqual(calls[0]["http_options"]["timeout"], 120000)
        self.assertNotIn("api_key", calls[0])

    def test_api_key_config_keeps_developer_api_client(self):
        self.assertFalse(should_use_vertex_ai({"apiKey": "key"}))

    def test_missing_api_key_defaults_to_vertex_ai_adc(self):
        self.assertTrue(should_use_vertex_ai({"location": "global"}))
        self.assertTrue(should_use_vertex_ai({"auth": "ADC"}))


if __name__ == "__main__":
    unittest.main()
