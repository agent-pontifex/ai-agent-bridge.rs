"""Command-line entry point for the Agent Pontifex roundtable harness."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .common import ConformanceError, load_matrix
from .runner import run_roundtable

ROOT = Path(__file__).resolve().parents[2]


def _positive_timeout(value: str) -> float:
    parsed = float(value)
    if not 1.0 <= parsed <= 600.0:
        raise argparse.ArgumentTypeError("timeout must be between 1 and 600 seconds")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a four-provider, turn-level SSE conformance roundtable against "
            "a loopback Agent Pontifex bridge. Credentials are read only from "
            "environment variables declared by the model matrix."
        )
    )
    parser.add_argument(
        "--bridge-url",
        default="http://127.0.0.1:18142",
        help="Loopback HTTP origin for the bridge",
    )
    parser.add_argument(
        "--bridge-bearer-env",
        default="AGENT_PONTIFEX_BRIDGE_BEARER",
        help="Environment variable containing the loopback bridge bearer",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "four-provider-models.json",
    )
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument(
        "--acknowledge-model-substitutions",
        action="store_true",
        help="Required in live mode when a requested label maps to another API model",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "target" / "agent-pontifex-roundtable-evidence.json",
    )
    parser.add_argument("--timeout-seconds", type=_positive_timeout, default=45.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bridge_bearer = os.environ.get(args.bridge_bearer_env, "")
    if not bridge_bearer:
        print(
            f"missing loopback bridge bearer environment variable {args.bridge_bearer_env}",
            file=sys.stderr,
        )
        return 2
    if args.mode == "live" and os.environ.get(
        "AGENT_PONTIFEX_ALLOW_LIVE_PROVIDER_CALLS"
    ) != "1":
        print(
            "live provider calls require AGENT_PONTIFEX_ALLOW_LIVE_PROVIDER_CALLS=1",
            file=sys.stderr,
        )
        return 2

    try:
        matrix = load_matrix(args.matrix)
        evidence = run_roundtable(
            bridge_url=args.bridge_url,
            bridge_bearer=bridge_bearer,
            matrix=matrix,
            mode=args.mode,
            evidence_path=args.evidence,
            timeout_seconds=args.timeout_seconds,
            acknowledge_substitutions=args.acknowledge_model_substitutions,
        )
    except (ConformanceError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"roundtable conformance failed: {error}", file=sys.stderr)
        return 1

    summary = {
        "ok": evidence["ok"],
        "mode": evidence["mode"],
        "session_id": evidence["session_id"],
        "provider_calls": evidence["provider_calls"],
        "event_count": evidence["replay"]["event_count"],
        "maximum_propagation_ms": evidence["sse"]["maximum_propagation_ms"],
        "evidence_path": str(args.evidence),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
