"""Live-event payload helpers and model-substitution gates."""
from __future__ import annotations

from typing import Any

from .common import ConformanceError, MAX_TRANSCRIPT_BYTES, ProviderResult


def event_frames(
    frames: list[tuple[dict[str, Any], float]],
) -> list[tuple[dict[str, Any], float]]:
    values: list[tuple[dict[str, Any], float]] = []
    for frame, received_at in frames:
        if frame.get("type") == "event" and isinstance(frame.get("event"), dict):
            values.append((frame["event"], received_at))
    return values


def make_publish_body(
    *,
    slug: str,
    nonce: str,
    spec: dict[str, Any],
    phase: str,
    content: str,
    result: ProviderResult,
    recipients: list[str],
) -> dict[str, Any]:
    return {
        "client_event_id": f"{nonce}-{phase}-{spec['agent_key']}",
        "session_id": slug,
        "channel": slug,
        "sender": spec["agent_key"],
        "recipients": recipients,
        "correlation_id": f"four-provider-roundtable-{nonce}",
        "idempotency_key": f"roundtable-{nonce}-{phase}-{spec['agent_key']}",
        "payload": {
            "kind": "message",
            "content": content,
            "content_type": "text/plain",
        },
        "extensions": {
            "agent-pontifex.roundtable": {
                "phase": phase,
                "provider": spec["provider"],
                "requested_label": spec["requested_label"],
                "resolved_model": spec["model"],
                "protocol": spec["protocol"],
                "prompt_sha256": result.prompt_sha256,
                "response_sha256": result.response_sha256,
                "response_bytes": result.response_bytes,
            }
        },
    }


def transcript_from(events: list[dict[str, Any]], phase: str) -> str:
    rows: list[str] = []
    for event in sorted(events, key=lambda value: value["seq"]):
        extension = event.get("extensions", {}).get("agent-pontifex.roundtable", {})
        if extension.get("phase") != phase:
            continue
        content = event.get("payload", {}).get("content")
        if isinstance(content, str):
            rows.append(f"[{event['seq']}] {event['sender']}: {content}")
    transcript = "\n".join(rows)
    if len(transcript.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
        raise ConformanceError("observable transcript exceeds the conformance safety limit")
    return transcript


def assert_substitution_acknowledged(
    matrix: dict[str, Any], acknowledged: bool
) -> None:
    substitutions = [
        agent
        for agent in matrix["agents"]
        if agent["resolution"] == "explicit_substitution"
    ]
    if substitutions and not acknowledged:
        labels = ", ".join(agent["requested_label"] for agent in substitutions)
        raise ConformanceError(
            "live mode requires explicit acknowledgement for model substitutions: "
            + labels
        )

