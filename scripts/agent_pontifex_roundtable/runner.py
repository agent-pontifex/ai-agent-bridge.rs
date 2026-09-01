"""Four-participant turn-level roundtable orchestration and assertions."""
from __future__ import annotations

import copy
import json
import secrets
import time
from pathlib import Path
from typing import Any

from .bridge import BridgeClient, SSECollector
from .common import ConformanceError, HttpJsonError, PublishedEvent
from .protocol import event_frames, make_publish_body, transcript_from
from .providers import invoke_provider


def run_roundtable(
    *,
    bridge_url: str,
    bridge_bearer: str,
    matrix: dict[str, Any],
    mode: str,
    evidence_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    bridge = BridgeClient(bridge_url, bridge_bearer)
    nonce = secrets.token_hex(8)
    agents: list[dict[str, Any]] = matrix["agents"]
    agent_keys = [agent["agent_key"] for agent in agents]

    for spec in agents:
        bridge.register(spec)
    slug = bridge.resolve(agent_keys[0], nonce)
    for index, spec in enumerate(agents):
        bridge.join(slug, spec["agent_key"], "owner" if index == 0 else "member")

    session = bridge.session(slug).get("session", {})
    participants = session.get("participants", [])
    if len(participants) != 4:
        raise ConformanceError(
            f"live session has {len(participants)} participants, expected 4"
        )
    observed_identities = {
        (
            participant.get("identity", {}).get("participant_id"),
            participant.get("identity", {}).get("provider"),
            participant.get("identity", {}).get("model"),
        )
        for participant in participants
    }
    expected_identities = {
        (agent["agent_key"], agent["provider"], agent["model"]) for agent in agents
    }
    if observed_identities != expected_identities:
        raise ConformanceError(
            "session participant provider/model identities do not match the matrix"
        )

    collectors = [
        SSECollector(bridge_url, bridge_bearer, slug, key) for key in agent_keys
    ]
    for collector in collectors:
        collector.start()
    published: list[PublishedEvent] = []
    try:
        for collector in collectors:
            if not collector.ready.wait(timeout=10):
                raise ConformanceError(f"SSE collector {collector.name} did not connect")
            collector.wait_for(
                lambda frames: any(
                    frame.get("type") == "welcome" for frame, _ in frames
                ),
                10,
            )

        for index, spec in enumerate(agents):
            peers = tuple(key for key in agent_keys if key != spec["agent_key"])
            prompt = (
                f"You are {spec['requested_label']} in Agent Pontifex conformance session {nonce}. "
                "Publish one concise, externally observable bridge reliability invariant. "
                "Do not expose hidden reasoning, private traces, credentials, or claim unobserved side effects."
            )
            result = invoke_provider(spec, prompt, mode, ())
            content = f"{spec['requested_label']}: {result.text}"
            body = make_publish_body(
                slug=slug,
                nonce=nonce,
                spec=spec,
                phase="intro",
                content=content,
                result=result,
                recipients=list(peers),
            )
            send_started = time.monotonic()
            response = bridge.publish(slug, body)
            seq = response["accepted"]["seq"]
            published.append(
                PublishedEvent(
                    "intro",
                    spec["agent_key"],
                    seq,
                    send_started,
                    result.response_sha256,
                    result.response_bytes,
                    (),
                )
            )
            if index == 0:
                replayed = bridge.publish(slug, body)
                if (
                    replayed["accepted"].get("replayed") is not True
                    or replayed["accepted"].get("seq") != seq
                ):
                    raise ConformanceError(
                        "exact idempotent retry did not replay the accepted event"
                    )
                conflict = copy.deepcopy(body)
                conflict["payload"]["content"] += " changed"
                try:
                    bridge.publish(slug, conflict)
                except HttpJsonError as error:
                    if (
                        error.status != 409
                        or error.payload.get("error") != "idempotency_conflict"
                    ):
                        raise
                else:
                    raise ConformanceError(
                        "conflicting idempotency reuse was accepted"
                    )

        for collector in collectors:
            collector.wait_for(
                lambda frames: len(event_frames(frames)) >= 4,
                timeout_seconds,
            )

        replay_after_intros = bridge.replay(slug, 0)
        intro_events = replay_after_intros.get("events", [])
        transcript = transcript_from(intro_events, "intro")
        if not transcript:
            raise ConformanceError("bridge replay did not contain intro events")

        for spec in agents:
            peers = tuple(key for key in agent_keys if key != spec["agent_key"])
            prompt = (
                f"You are {spec['requested_label']} in Agent Pontifex conformance session {nonce}.\n"
                f"You received observable turns from these peers: {', '.join(peers)}.\n"
                "Review every peer turn below and publish one concise interoperability handoff. "
                "Do not expose hidden reasoning, private traces, credentials, or claim unobserved side effects.\n\n"
                f"OBSERVABLE_TRANSCRIPT_BEGIN\n{transcript}\nOBSERVABLE_TRANSCRIPT_END"
            )
            result = invoke_provider(spec, prompt, mode, peers)
            content = (
                f"{spec['requested_label']} received peers={','.join(peers)}; "
                f"response: {result.text}"
            )
            body = make_publish_body(
                slug=slug,
                nonce=nonce,
                spec=spec,
                phase="ack",
                content=content,
                result=result,
                recipients=list(peers),
            )
            send_started = time.monotonic()
            response = bridge.publish(slug, body)
            published.append(
                PublishedEvent(
                    "ack",
                    spec["agent_key"],
                    response["accepted"]["seq"],
                    send_started,
                    result.response_sha256,
                    result.response_bytes,
                    peers,
                )
            )

        for collector in collectors:
            collector.wait_for(
                lambda frames: len(event_frames(frames)) >= 8,
                timeout_seconds,
            )
            if collector.errors:
                raise ConformanceError(
                    f"SSE collector {collector.name} failed: {collector.errors}"
                )

        replay = bridge.replay(slug, 0)
        replay_events = replay.get("events", [])
        sequences = [event.get("seq") for event in replay_events]
        if sequences != list(range(1, 9)):
            raise ConformanceError(
                f"bridge replay sequence is not contiguous 1..8: {sequences!r}"
            )
        if replay.get("high_water_seq") != 8:
            raise ConformanceError(
                f"unexpected high-water sequence {replay.get('high_water_seq')!r}"
            )

        publication_by_seq = {event.seq: event for event in published}
        propagation: dict[str, list[float]] = {}
        collector_sequences: dict[str, list[int]] = {}
        for collector in collectors:
            observed = event_frames(collector.snapshot())
            seqs = [event.get("seq") for event, _ in observed]
            if seqs != list(range(1, 9)):
                raise ConformanceError(
                    f"collector {collector.name} saw non-contiguous sequences {seqs!r}"
                )
            collector_sequences[collector.name] = seqs
            timings: list[float] = []
            for event, received_at in observed:
                published_event = publication_by_seq[event["seq"]]
                timings.append(
                    max(
                        0.0,
                        (received_at - published_event.send_started) * 1000.0,
                    )
                )
            propagation[collector.name] = timings

        visibility: dict[str, list[str]] = {}
        for record in published:
            if record.phase != "ack":
                continue
            expected_peers = sorted(set(agent_keys) - {record.agent_key})
            actual_peers = sorted(record.visible_peers)
            if actual_peers != expected_peers:
                raise ConformanceError(
                    f"{record.agent_key} visibility mismatch: {actual_peers!r}"
                )
            visibility[record.agent_key] = actual_peers
        if set(visibility) != set(agent_keys):
            raise ConformanceError(
                "not every provider published a peer-aware acknowledgement"
            )

        maximum_propagation_ms = max(
            value for values in propagation.values() for value in values
        )
        if mode == "mock" and maximum_propagation_ms > 5_000:
            raise ConformanceError(
                "mock SSE propagation exceeded 5000 ms: "
                f"{maximum_propagation_ms:.1f}"
            )

        evidence = {
            "schema_version": 1,
            "ok": True,
            "mode": mode,
            "realtime_semantics": "turn_level_sse",
            "session_id": slug,
            "participants": [
                {
                    "agent_key": agent["agent_key"],
                    "requested_label": agent["requested_label"],
                    "provider": agent["provider"],
                    "model": agent["model"],
                    "protocol": agent["protocol"],
                    "resolution": agent["resolution"],
                }
                for agent in agents
            ],
            "provider_calls": len(published),
            "published_events": [
                {
                    "phase": event.phase,
                    "agent_key": event.agent_key,
                    "seq": event.seq,
                    "response_sha256": event.response_sha256,
                    "response_bytes": event.response_bytes,
                    "visible_peers": list(event.visible_peers),
                }
                for event in published
            ],
            "replay": {
                "event_count": len(replay_events),
                "high_water_seq": replay["high_water_seq"],
                "contiguous_sequences": sequences,
                "idempotent_retry_verified": True,
                "idempotency_conflict_verified": True,
            },
            "sse": {
                "collector_sequences": collector_sequences,
                "maximum_propagation_ms": round(maximum_propagation_ms, 3),
            },
            "pairwise_visibility": visibility,
            "completed_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return evidence
    finally:
        for collector in collectors:
            collector.stop()

