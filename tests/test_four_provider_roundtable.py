from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "four_provider_roundtable.py"
SPEC = importlib.util.spec_from_file_location("four_provider_roundtable", MODULE_PATH)
assert SPEC and SPEC.loader
roundtable = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = roundtable
SPEC.loader.exec_module(roundtable)
common = importlib.import_module("agent_pontifex_roundtable.common")
bridge_module = importlib.import_module("agent_pontifex_roundtable.bridge")
providers_module = importlib.import_module("agent_pontifex_roundtable.providers")


class FourProviderRoundtableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix_path = ROOT / "tests" / "fixtures" / "four-provider-models.json"
        cls.matrix = roundtable.load_matrix(cls.matrix_path)
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

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(roundtable.ConformanceError):
                roundtable.run_roundtable(
                    bridge_url="http://127.0.0.1:1",
                    bridge_bearer="loopback-only",
                    matrix=self.matrix,
                    mode="live",
                    evidence_path=Path(directory) / "evidence.json",
                    timeout_seconds=1.0,
                    acknowledge_substitutions=False,
                )

    def test_live_runner_preflights_all_credentials_before_bridge_access(self) -> None:
        provider_env_names = {
            agent["credential_env"] for agent in self.matrix["agents"]
        }
        scrubbed = {
            key: value
            for key, value in os.environ.items()
            if key not in provider_env_names
        }
        with patch.dict(os.environ, scrubbed, clear=True):
            with self.assertRaisesRegex(
                roundtable.ConformanceError,
                "ANTHROPIC_API_KEY.*GEMINI_API_KEY.*OPENAI_API_KEY.*XAI_API_KEY",
            ):
                roundtable.run_roundtable(
                    bridge_url="http://127.0.0.1:9",
                    bridge_bearer="not-used-because-preflight-fails",
                    matrix=self.matrix,
                    mode="live",
                    evidence_path=ROOT / "target" / "should-not-exist.json",
                    timeout_seconds=1.0,
                    acknowledge_substitutions=True,
                )

    def test_cli_keeps_bearer_out_of_arguments_and_gates_live_calls(self) -> None:
        args = roundtable.parse_args([])
        self.assertFalse(hasattr(args, "bridge_bearer"))
        self.assertEqual(
            args.bridge_bearer_env, "AGENT_PONTIFEX_BRIDGE_BEARER"
        )
        with patch.dict(
            os.environ,
            {"AGENT_PONTIFEX_BRIDGE_BEARER": "loopback-only"},
            clear=True,
        ):
            with self.assertRaises(roundtable.ConformanceError) as raised:
                roundtable.main(
                    [
                        "--mode",
                        "live",
                        "--acknowledge-substitutions",
                        "--matrix",
                        str(self.matrix_path),
                    ]
                )
        self.assertIn(
            "AGENT_PONTIFEX_ALLOW_LIVE_PROVIDER_CALLS",
            str(raised.exception),
        )

    def test_live_http_error_body_is_redacted(self) -> None:
        secret_body = "provider-private-error-body"

        class ErrorHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                payload = json.dumps({"error": secret_body}).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), ErrorHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(roundtable.HttpJsonError) as raised:
                common.json_request(
                    f"http://127.0.0.1:{server.server_port}/error",
                    redact_error_body=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        rendered = json.dumps(raised.exception.payload, sort_keys=True)
        self.assertNotIn(secret_body, rendered)
        self.assertEqual(
            raised.exception.payload["error"], "redacted_http_error"
        )
        self.assertGreater(raised.exception.payload["response_bytes"], 0)

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

    def test_provider_binding_rejects_arbitrary_secret_environment_routing(self) -> None:
        spec = copy.deepcopy(self.by_protocol["openai_responses"])
        spec["credential_env"] = "GITHUB_TOKEN"
        with patch.dict(os.environ, {"GITHUB_TOKEN": "must-never-leave"}, clear=True):
            with patch.object(providers_module, "json_request") as request:
                with self.assertRaisesRegex(
                    roundtable.ConformanceError,
                    "must use credential environment variable 'OPENAI_API_KEY'",
                ) as raised:
                    roundtable.invoke_provider(
                        spec,
                        "observable prompt",
                        "live",
                        (),
                    )
        request.assert_not_called()
        self.assertNotIn("must-never-leave", str(raised.exception))

    def test_provider_binding_rejects_cross_provider_protocol_swap(self) -> None:
        spec = copy.deepcopy(self.by_protocol["openai_responses"])
        spec["protocol"] = "xai_chat_completions"
        with self.assertRaisesRegex(
            roundtable.ConformanceError,
            "must use protocol 'openai_responses'",
        ):
            roundtable.invoke_provider(spec, "observable prompt", "mock", ())

    def test_bridge_json_and_sse_redirects_do_not_forward_bearer(self) -> None:
        forwarded_authorization: list[str | None] = []
        collector = None

        class SinkHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                forwarded_authorization.append(self.headers.get("Authorization"))
                payload = b"unexpected redirect target"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        sink = ThreadingHTTPServer(("127.0.0.1", 0), SinkHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{sink.server_port}/capture",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        sink_thread = threading.Thread(target=sink.serve_forever, daemon=True)
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        sink_thread.start()
        redirect_thread.start()
        bearer = "bridge-bearer-must-not-forward"
        base_url = f"http://127.0.0.1:{redirect.server_port}"
        try:
            client = bridge_module.BridgeClient(base_url, bearer)
            with self.assertRaises(common.HttpJsonError) as raised:
                client.request("/redirect")
            self.assertEqual(raised.exception.payload["error"], "redirect_rejected")

            collector = bridge_module.SSECollector(
                base_url,
                bearer,
                "roundtable-room",
                "redirect-test",
            )
            collector.start()
            self.assertTrue(collector.ready.wait(timeout=3))
            deadline = time.monotonic() + 3
            while not collector.errors and time.monotonic() < deadline:
                time.sleep(0.025)
            self.assertTrue(collector.errors, "SSE redirect was not rejected")
            rendered = "\n".join(collector.errors)
            self.assertIn("redirect_rejected", rendered)
            self.assertNotIn(bearer, rendered)
            self.assertEqual(forwarded_authorization, [])
        finally:
            if collector is not None:
                collector.stop()
            redirect.shutdown()
            redirect.server_close()
            sink.shutdown()
            sink.server_close()
            redirect_thread.join(timeout=5)
            sink_thread.join(timeout=5)

    def test_bridge_origin_and_resume_cursor_fail_closed(self) -> None:
        for base_url in (
            "http://user@127.0.0.1:18142",
            "http://127.0.0.1:18142/prefix",
            "http://127.0.0.1:18142?query=1",
            "http://127.0.0.1:18142#fragment",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaises(roundtable.ConformanceError):
                    bridge_module.BridgeClient(base_url, "non-empty")
        with self.assertRaises(roundtable.ConformanceError):
            bridge_module.BridgeClient("http://127.0.0.1:18142", "")
        for after_seq in (-1, True):
            with self.subTest(after_seq=after_seq):
                with self.assertRaises(roundtable.ConformanceError):
                    bridge_module.SSECollector(
                        "http://127.0.0.1:18142",
                        "non-empty",
                        "room",
                        "invalid-resume",
                        after_seq=after_seq,
                    )


if __name__ == "__main__":
    unittest.main()
