from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "four_provider_roundtable.py"
SPEC = importlib.util.spec_from_file_location("four_provider_roundtable", MODULE_PATH)
assert SPEC and SPEC.loader
roundtable = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = roundtable
SPEC.loader.exec_module(roundtable)


class FourProviderRoundtableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = roundtable.load_matrix(
            ROOT / "tests" / "fixtures" / "four-provider-models.json"
        )
        cls.by_protocol = {
            agent["protocol"]: agent for agent in cls.matrix["agents"]
        }

    def test_matrix_covers_four_distinct_provider_protocols(self) -> None:
        self.assertEqual(
            {agent["provider"] for agent in self.matrix["agents"]},
            {"openai", "anthropic", "google", "xai"},
        )
        self.assertEqual(
            len({agent["agent_key"] for agent in self.matrix["agents"]}), 4
        )
        substitutions = {
            agent["requested_label"]: agent["model"]
            for agent in self.matrix["agents"]
            if agent["resolution"] == "explicit_substitution"
        }
        self.assertEqual(
            substitutions,
            {
                "Gemini 3.6 Pro": "gemini-3.1-pro-preview",
                "ChatGPT Sol 4.6": "gpt-5.6-sol",
            },
        )

    def test_provider_destinations_are_fixed_https_hosts(self) -> None:
        expected = {
            "openai_responses": "https://api.openai.com/v1/responses",
            "anthropic_messages": "https://api.anthropic.com/v1/messages",
            "gemini_generate_content": (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-3.1-pro-preview:generateContent"
            ),
            "xai_chat_completions": "https://api.x.ai/v1/chat/completions",
        }
        for protocol, expected_url in expected.items():
            with self.subTest(protocol=protocol):
                url, headers, body = roundtable.provider_request(
                    self.by_protocol[protocol], "hello", "not-a-real-key"
                )
                self.assertEqual(url, expected_url)
                if protocol != "gemini_generate_content":
                    self.assertIn("model", body)
                self.assertNotIn("not-a-real-key", json.dumps(body))
                self.assertTrue(
                    any("not-a-real-key" in value for value in headers.values())
                )

    def test_every_mock_protocol_round_trips_observable_text(self) -> None:
        for agent in self.matrix["agents"]:
            with self.subTest(protocol=agent["protocol"]):
                result = roundtable.invoke_provider(
                    agent,
                    "bounded prompt",
                    "mock",
                    ("peer-a", "peer-b", "peer-c"),
                )
                self.assertIn("peer-a", result.text)
                self.assertEqual(len(result.prompt_sha256), 64)
                self.assertEqual(len(result.response_sha256), 64)
                self.assertGreater(result.response_bytes, 0)

    def test_live_substitutions_fail_closed_without_acknowledgement(self) -> None:
        with self.assertRaises(roundtable.ConformanceError):
            roundtable.assert_substitution_acknowledged(self.matrix, False)
        roundtable.assert_substitution_acknowledged(self.matrix, True)

    def test_message_payload_uses_extension_for_metadata(self) -> None:
        agent = self.matrix["agents"][0]
        result = roundtable.ProviderResult("ok", "a" * 64, "b" * 64, 2)
        body = roundtable.make_publish_body(
            slug="room",
            nonce="1234567890abcdef",
            spec=agent,
            phase="intro",
            content="observable",
            result=result,
            recipients=[
                value["agent_key"] for value in self.matrix["agents"][1:]
            ],
        )
        self.assertEqual(set(body["payload"]), {"kind", "content", "content_type"})
        self.assertEqual(body["payload"]["kind"], "message")
        self.assertEqual(
            body["extensions"]["agent-pontifex.roundtable"]["response_sha256"],
            "b" * 64,
        )
        self.assertNotIn("credential", json.dumps(body).lower())

    def test_provider_response_parsers_ignore_non_text_reasoning_blocks(self) -> None:
        anthropic = {
            "content": [
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "observable answer"},
            ]
        }
        gemini = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"thought": True, "text": "private"},
                            {"text": "observable answer"},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(
            roundtable.provider_response_text("anthropic_messages", anthropic),
            "observable answer",
        )
        self.assertEqual(
            roundtable.provider_response_text("gemini_generate_content", gemini),
            "observable answer",
        )


if __name__ == "__main__":
    unittest.main()
