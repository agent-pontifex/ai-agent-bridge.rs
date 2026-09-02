"""Loopback bridge client and independent SSE subscriber."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

from .common import ConformanceError, RejectRedirects, json_request


def normalize_loopback_base_url(base_url: str) -> str:
    """Accept only a root loopback HTTP origin with no credential-bearing URL parts."""

    parsed = urllib.parse.urlsplit(base_url)
    try:
        parsed.port
    except ValueError as error:
        raise ConformanceError("conformance bridge URL has an invalid port") from error
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ConformanceError("conformance bridge URL must be loopback HTTP")
    if parsed.username is not None or parsed.password is not None:
        raise ConformanceError("conformance bridge URL must not contain user information")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConformanceError("conformance bridge URL must be a root origin")
    return base_url.rstrip("/")


class BridgeClient:
    def __init__(self, base_url: str, bearer: str):
        if not bearer:
            raise ConformanceError("conformance bridge bearer must be non-empty")
        self.base_url = normalize_loopback_base_url(base_url)
        self.bearer = bearer

    def request(self, path: str, *, method: str = "GET", body: Any | None = None) -> Any:
        return json_request(
            self.base_url + "/" + path.lstrip("/"),
            method=method,
            headers={"Authorization": f"Bearer {self.bearer}"},
            body=body,
            timeout=30.0,
            reject_redirects=True,
        )

    def register(self, spec: dict[str, Any]) -> None:
        response = self.request(
            "/agents/register",
            method="POST",
            body={
                "agent_key": spec["agent_key"],
                "display_name": spec["requested_label"],
                "kind": spec["kind"],
                "meta": {
                    "provider": spec["provider"],
                    "model": spec["model"],
                    "runtime": f"{spec['protocol']}-worker",
                    "capabilities": [
                        "agent.chat",
                        "agent.review",
                        "bridge.live-session",
                    ],
                },
            },
        )
        if response.get("agent", {}).get("agent_key") != spec["agent_key"]:
            raise ConformanceError(f"bridge failed to register {spec['agent_key']}")

    def resolve(self, created_by: str, nonce: str) -> str:
        response = self.request(
            "/channels/resolve",
            method="POST",
            body={
                "query": f"Agent Pontifex four-provider roundtable {nonce}",
                "created_by": created_by,
                "threshold": 1.0,
            },
        )
        slug = response.get("channel", {}).get("slug")
        if not isinstance(slug, str) or not slug:
            raise ConformanceError("bridge did not return a channel slug")
        return slug

    def join(self, slug: str, agent_key: str, role: str = "member") -> None:
        response = self.request(
            f"/channels/{urllib.parse.quote(slug, safe='')}/join",
            method="POST",
            body={"agent_key": agent_key, "role": role},
        )
        if response.get("member", {}).get("agent_key") != agent_key:
            raise ConformanceError(f"bridge failed to join {agent_key}")

    def publish(self, slug: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.request(
            f"/live-sessions/{urllib.parse.quote(slug, safe='')}/events",
            method="POST",
            body=body,
        )
        accepted = response.get("accepted")
        if not isinstance(accepted, dict) or not isinstance(accepted.get("seq"), int):
            raise ConformanceError("bridge publish response is missing accepted sequence")
        return response

    def replay(self, slug: str, since: int = 0) -> dict[str, Any]:
        return self.request(
            f"/live-sessions/{urllib.parse.quote(slug, safe='')}/events?since={since}"
        )

    def session(self, slug: str) -> dict[str, Any]:
        return self.request(f"/live-sessions/{urllib.parse.quote(slug, safe='')}")


class SSECollector:
    def __init__(self, base_url: str, bearer: str, slug: str, name: str, after_seq: int = 0):
        if not bearer:
            raise ConformanceError("conformance bridge bearer must be non-empty")
        if not isinstance(after_seq, int) or isinstance(after_seq, bool) or after_seq < 0:
            raise ConformanceError("SSE resume sequence must be a non-negative integer")
        base_url = normalize_loopback_base_url(base_url)
        quoted = urllib.parse.quote(slug, safe="")
        self.url = f"{base_url}/live-sessions/{quoted}/stream?after_seq={after_seq}"
        self.bearer = bearer
        self.name = name
        self.frames: list[tuple[dict[str, Any], float]] = []
        self.errors: list[str] = []
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._response: Any | None = None
        self._thread = threading.Thread(target=self._run, name=f"sse-{name}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        response = self._response
        if response is not None:
            try:
                response.close()
            except OSError:
                pass
        self._thread.join(timeout=5)

    def snapshot(self) -> list[tuple[dict[str, Any], float]]:
        with self._lock:
            return list(self.frames)

    def wait_for(self, predicate: Callable[[list[tuple[dict[str, Any], float]]], bool], timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frames = self.snapshot()
            if predicate(frames):
                return
            if self.errors:
                raise ConformanceError(f"SSE collector {self.name} failed: {self.errors}")
            time.sleep(0.025)
        raise ConformanceError(f"SSE collector {self.name} timed out with {len(self.snapshot())} frames")

    def _run(self) -> None:
        request = urllib.request.Request(
            self.url,
            headers={
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {self.bearer}",
                "Cache-Control": "no-cache",
            },
        )
        opener = urllib.request.build_opener(RejectRedirects())
        try:
            with opener.open(request, timeout=300) as response:
                self._response = response
                self.ready.set()
                for raw_line in response:
                    if self._stop.is_set():
                        break
                    line = raw_line.decode("utf-8", errors="strict").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    frame = json.loads(payload)
                    if not isinstance(frame, dict):
                        raise ConformanceError("SSE frame data must be an object")
                    with self._lock:
                        self.frames.append((frame, time.monotonic()))
        except Exception as error:  # closing the response during stop is expected
            if not self._stop.is_set():
                self.errors.append(f"{type(error).__name__}: {error}")
        finally:
            self._response = None
            self.ready.set()
