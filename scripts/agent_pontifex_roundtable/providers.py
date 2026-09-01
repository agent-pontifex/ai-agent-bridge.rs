"""Fixed-destination provider adapters shared by mock and live lanes."""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

from .common import (
    ConformanceError,
    PROVIDER_TIMEOUT_SECONDS,
    ProviderResult,
    bounded_text,
    json_request,
    sha256_text,
)


def provider_request(
    spec: dict[str, Any], prompt: str, api_key: str
) -> tuple[str, dict[str, str], dict[str, Any]]:
    protocol = spec["protocol"]
    model = spec["model"]
    if protocol == "openai_responses":
        return (
            "https://api.openai.com/v1/responses",
            {"Authorization": f"Bearer {api_key}"},
            {"model": model, "input": prompt, "max_output_tokens": 512},
        )
    if protocol == "anthropic_messages":
        return (
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {
                "model": model,
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    if protocol == "gemini_generate_content":
        quoted_model = urllib.parse.quote(model, safe="-._")
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/{quoted_model}:generateContent",
            {"x-goog-api-key": api_key},
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 512},
            },
        )
    if protocol == "xai_chat_completions":
        return (
            "https://api.x.ai/v1/chat/completions",
            {"Authorization": f"Bearer {api_key}"},
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 512,
            },
        )
    raise ConformanceError(f"unsupported provider protocol {protocol!r}")


def mock_provider_response(protocol: str, text: str) -> dict[str, Any]:
    if protocol == "openai_responses":
        return {
            "id": "resp_mock",
            "output": [{"content": [{"type": "output_text", "text": text}]}],
        }
    if protocol == "anthropic_messages":
        return {"id": "msg_mock", "content": [{"type": "text", "text": text}]}
    if protocol == "gemini_generate_content":
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if protocol == "xai_chat_completions":
        return {"id": "chatcmpl_mock", "choices": [{"message": {"content": text}}]}
    raise ConformanceError(f"unsupported provider protocol {protocol!r}")


def provider_response_text(protocol: str, payload: dict[str, Any]) -> str:
    try:
        if protocol == "openai_responses":
            direct = payload.get("output_text")
            if isinstance(direct, str) and direct.strip():
                return bounded_text(direct)
            texts: list[str] = []
            for output in payload.get("output", []):
                for content in output.get("content", []):
                    if content.get("type") in {"output_text", "text"} and isinstance(
                        content.get("text"), str
                    ):
                        texts.append(content["text"])
            return bounded_text("\n".join(texts))
        if protocol == "anthropic_messages":
            texts = [
                part["text"]
                for part in payload.get("content", [])
                if part.get("type") == "text" and isinstance(part.get("text"), str)
            ]
            return bounded_text("\n".join(texts))
        if protocol == "gemini_generate_content":
            texts = []
            for candidate in payload.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if isinstance(part.get("text"), str) and not part.get("thought", False):
                        texts.append(part["text"])
            return bounded_text("\n".join(texts))
        if protocol == "xai_chat_completions":
            return bounded_text(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise ConformanceError(f"malformed {protocol} response") from error
    raise ConformanceError(f"unsupported provider protocol {protocol!r}")


def invoke_provider(
    spec: dict[str, Any], prompt: str, mode: str, visible_peers: tuple[str, ...]
) -> ProviderResult:
    prompt_digest = sha256_text(prompt)
    if mode == "mock":
        peer_text = ",".join(visible_peers) if visible_peers else "none"
        synthetic = (
            f"{spec['requested_label']} processed observable peers={peer_text}; "
            f"prompt_sha256={prompt_digest}; reliability finding: preserve ordered replay and idempotency."
        )
        payload = mock_provider_response(spec["protocol"], synthetic)
    elif mode == "live":
        credential = os.environ.get(spec["credential_env"], "")
        if not credential:
            raise ConformanceError(f"missing live credential {spec['credential_env']}")
        url, headers, body = provider_request(spec, prompt, credential)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {
            "api.openai.com",
            "api.anthropic.com",
            "generativelanguage.googleapis.com",
            "api.x.ai",
        }:
            raise ConformanceError(f"provider destination is not allow-listed: {url}")
        payload = json_request(
            url,
            method="POST",
            headers=headers,
            body=body,
            timeout=PROVIDER_TIMEOUT_SECONDS,
            reject_redirects=True,
        )
    else:
        raise ConformanceError(f"unsupported mode {mode!r}")
    text = provider_response_text(spec["protocol"], payload)
    return ProviderResult(
        text=text,
        prompt_sha256=prompt_digest,
        response_sha256=sha256_text(text),
        response_bytes=len(text.encode("utf-8")),
    )

