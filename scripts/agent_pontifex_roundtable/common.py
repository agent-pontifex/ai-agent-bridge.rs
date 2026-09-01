"""Shared bounds, validation, and metadata-only evidence types."""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_HTTP_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PROVIDER_TEXT_BYTES = 16 * 1024
MAX_TRANSCRIPT_BYTES = 64 * 1024
PROVIDER_TIMEOUT_SECONDS = 120.0
EXPECTED_PROTOCOLS = {
    "openai_responses",
    "anthropic_messages",
    "gemini_generate_content",
    "xai_chat_completions",
}
EXPECTED_PROVIDERS = {"openai", "anthropic", "google", "xai"}

class ConformanceError(RuntimeError):
    """Raised when an observable conformance invariant is not satisfied."""


class HttpJsonError(ConformanceError):
    def __init__(self, status: int, payload: Any, url: str):
        super().__init__(f"HTTP {status} from {url}: {payload!r}")
        self.status = status
        self.payload = payload
        self.url = url


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise HttpJsonError(code, {"error": "redirect_rejected"}, req.full_url)


@dataclass(frozen=True)
class ProviderResult:
    text: str
    prompt_sha256: str
    response_sha256: str
    response_bytes: int


@dataclass(frozen=True)
class PublishedEvent:
    phase: str
    agent_key: str
    seq: int
    send_started: float
    response_sha256: str
    response_bytes: int
    visible_peers: tuple[str, ...]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bounded_text(value: str, limit: int = MAX_PROVIDER_TEXT_BYTES) -> str:
    value = value.strip()
    if not value:
        raise ConformanceError("provider returned no observable text")
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    encoded = encoded[:limit]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            encoded = encoded[: error.start]
    raise ConformanceError("provider output could not be bounded as UTF-8")


def load_matrix(path: Path) -> dict[str, Any]:
    matrix = json.loads(path.read_text(encoding="utf-8"))
    validate_matrix(matrix)
    return matrix


def validate_matrix(matrix: dict[str, Any]) -> None:
    if matrix.get("schema_version") != 1:
        raise ConformanceError("model matrix schema_version must be 1")
    if matrix.get("realtime_semantics") != "turn_level_sse":
        raise ConformanceError("model matrix must declare turn_level_sse semantics")
    agents = matrix.get("agents")
    if not isinstance(agents, list) or len(agents) != 4:
        raise ConformanceError("model matrix must contain exactly four agents")
    keys: set[str] = set()
    providers: set[str] = set()
    protocols: set[str] = set()
    for agent in agents:
        if not isinstance(agent, dict):
            raise ConformanceError("every model matrix agent must be an object")
        for field in (
            "agent_key",
            "requested_label",
            "provider",
            "model",
            "protocol",
            "kind",
            "credential_env",
            "resolution",
        ):
            if not isinstance(agent.get(field), str) or not agent[field].strip():
                raise ConformanceError(f"matrix agent has invalid {field}")
        if agent["agent_key"] in keys:
            raise ConformanceError(f"duplicate agent_key {agent['agent_key']!r}")
        keys.add(agent["agent_key"])
        providers.add(agent["provider"])
        protocols.add(agent["protocol"])
        if agent["resolution"] not in {"exact", "explicit_substitution"}:
            raise ConformanceError("resolution must be exact or explicit_substitution")
    if providers != EXPECTED_PROVIDERS:
        raise ConformanceError(f"expected providers {sorted(EXPECTED_PROVIDERS)}, got {sorted(providers)}")
    if protocols != EXPECTED_PROTOCOLS:
        raise ConformanceError(f"expected protocols {sorted(EXPECTED_PROTOCOLS)}, got {sorted(protocols)}")


def read_bounded(response: Any, limit: int = MAX_HTTP_RESPONSE_BYTES) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ConformanceError(f"HTTP response exceeded {limit} bytes")
    return payload


def json_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any | None = None,
    timeout: float = 15.0,
    reject_redirects: bool = False,
) -> Any:
    raw = None if body is None else canonical_json(body)
    request_headers = {"Accept": "application/json", **(headers or {})}
    if raw is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=raw, headers=request_headers, method=method)
    opener = urllib.request.build_opener(RejectRedirects()) if reject_redirects else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = read_bounded(response)
            return json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        payload = error.read(MAX_HTTP_RESPONSE_BYTES + 1)
        try:
            decoded = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            decoded = {"error": "non_json_response", "bytes": len(payload)}
        raise HttpJsonError(error.code, decoded, url) from error
    except urllib.error.URLError as error:
        raise ConformanceError(f"request failed for {url}: {error.reason}") from error

