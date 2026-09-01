#!/usr/bin/env python3
"""Run four-provider, turn-level Agent Pontifex bridge conformance.

Credential-free mode exercises the exact provider adapters with synthetic
responses through the real Rust bridge. Live mode calls only fixed official
HTTPS endpoints from an environment-protected manual GitHub Actions workflow.
Evidence is metadata-only: prompts, response bodies, private traces, and
credentials are never written to the evidence artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_pontifex_roundtable import (  # noqa: E402
    ConformanceError,
    HttpJsonError,
    load_matrix,
    run_roundtable,
)


def bounded_timeout(value: str) -> float:
    parsed = float(value)
    if not 1.0 <= parsed <= 600.0:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 600 seconds")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-url", default="http://127.0.0.1:18142")
    parser.add_argument(
        "--bridge-bearer-env",
        default="AGENT_PONTIFEX_BRIDGE_BEARER",
        help=(
            "environment variable containing the loopback bridge bearer; "
            "the bearer is never accepted on the command line"
        ),
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("tests/fixtures/four-provider-models.json"),
    )
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--acknowledge-substitutions", action="store_true")
    parser.add_argument(
        "--evidence-out",
        type=Path,
        default=Path("artifacts/four-provider-roundtable.json"),
    )
    parser.add_argument(
        "--timeout-seconds", type=bounded_timeout, default=30.0
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    bridge_bearer = os.environ.get(args.bridge_bearer_env, "")
    if not bridge_bearer:
        raise ConformanceError(
            f"bridge bearer environment variable {args.bridge_bearer_env!r} is required"
        )
    if args.mode == "live" and os.environ.get(
        "AGENT_PONTIFEX_ALLOW_LIVE_PROVIDER_CALLS"
    ) != "1":
        raise ConformanceError(
            "live provider calls require AGENT_PONTIFEX_ALLOW_LIVE_PROVIDER_CALLS=1"
        )

    matrix = load_matrix(args.matrix)
    evidence = run_roundtable(
        bridge_url=args.bridge_url,
        bridge_bearer=bridge_bearer,
        matrix=matrix,
        mode=args.mode,
        evidence_path=args.evidence_out,
        timeout_seconds=args.timeout_seconds,
        acknowledge_substitutions=args.acknowledge_substitutions,
    )
    print(
        json.dumps(
            {
                "ok": evidence["ok"],
                "mode": evidence["mode"],
                "session_id": evidence["session_id"],
                "provider_calls": evidence["provider_calls"],
                "events": evidence["replay"]["event_count"],
                "maximum_propagation_ms": evidence["sse"][
                    "maximum_propagation_ms"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        ConformanceError,
        HttpJsonError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"four-provider roundtable: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
