#!/usr/bin/env python3
"""Validate the fail-closed bridge lineage decision without network access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

EXPECTED_TOP_LEVEL = {
    "schemaVersion",
    "repository",
    "status",
    "deprecationAllowed",
    "peerRepository",
    "artifactIdentity",
    "capabilitiesToPreserveHere",
    "peerCapabilitiesToPreserve",
    "canonicalizationGates",
}
EXPECTED_ARTIFACT_FIELDS = {"status", "cargoPackage", "cargoRepository"}
EXPECTED_LOCAL_CAPABILITIES = [
    "agent-pontifex-persistence",
    "four-provider-roundtable",
    "replay-safe-live-session",
    "slack-ingress-security",
]
EXPECTED_PEER_CAPABILITIES = [
    "bounded-activation-canary",
    "fleet-runtime-activation",
]
EXPECTED_GATES = [
    "inventory-active-deployments-and-release-authorities",
    "compare-divergent-history-and-public-contracts",
    "choose-and-reserve-final-artifact-identities",
    "preserve-unique-capabilities-with-cross-repository-tests",
    "update-all-consumers-manifests-and-package-references",
    "prove-cutover-rollback-and-no-dual-writer-window",
    "freeze-retired-line-before-publishing-deprecation-notice",
]
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ValidationError(RuntimeError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def cargo_package_fields(cargo: str) -> tuple[str, str]:
    package_match = re.search(r'(?m)^name\s*=\s*"([^"]+)"\s*$', cargo)
    repository_match = re.search(r'(?m)^repository\s*=\s*"([^"]+)"\s*$', cargo)
    require(package_match is not None, "Cargo.toml package name is missing")
    require(repository_match is not None, "Cargo.toml repository metadata is missing")
    return package_match.group(1), repository_match.group(1)


def validate(root: Path) -> None:
    lineage_path = root / "repository-lineage.json"
    require(lineage_path.is_file() and not lineage_path.is_symlink(),
            "repository-lineage.json must be a regular file")
    try:
        data = json.loads(
            lineage_path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValidationError) as error:
        raise ValidationError(f"invalid repository-lineage.json: {error}") from error

    require(isinstance(data, dict), "lineage root must be an object")
    require(set(data) == EXPECTED_TOP_LEVEL, "lineage top-level fields drifted")
    require(data["schemaVersion"] == "agent-pontifex.repository-lineage.v1",
            "unsupported lineage schemaVersion")
    require(data["repository"] == "agent-pontifex/ai-agent-bridge.rs",
            "lineage repository must match this repository")
    require(data["status"] == "active-divergent",
            "status must remain active-divergent until a reviewed cutover")
    require(data["deprecationAllowed"] is False,
            "deprecation must remain fail-closed")

    peer = data["peerRepository"]
    require(isinstance(peer, str) and REPOSITORY_RE.fullmatch(peer) is not None,
            "peerRepository is invalid")
    require(peer == "ORESoftware/ai-agent-bridge.rs",
            "peerRepository must identify the active ORESoftware line")
    require(peer != data["repository"], "peerRepository must differ")

    artifact = data["artifactIdentity"]
    require(isinstance(artifact, dict) and set(artifact) == EXPECTED_ARTIFACT_FIELDS,
            "artifactIdentity fields drifted")
    require(artifact["status"] == "unresolved-legacy",
            "legacy artifact identity must remain explicitly unresolved")
    require(isinstance(artifact["cargoPackage"], str) and artifact["cargoPackage"],
            "cargoPackage must be non-empty")
    require(isinstance(artifact["cargoRepository"], str)
            and artifact["cargoRepository"].startswith("https://github.com/"),
            "cargoRepository must be a GitHub HTTPS URL")

    require(data["capabilitiesToPreserveHere"] == EXPECTED_LOCAL_CAPABILITIES,
            "local capability preservation list drifted")
    require(data["peerCapabilitiesToPreserve"] == EXPECTED_PEER_CAPABILITIES,
            "peer capability preservation list drifted")
    require(data["canonicalizationGates"] == EXPECTED_GATES,
            "canonicalization gates are incomplete or reordered")
    for field in (
        "capabilitiesToPreserveHere",
        "peerCapabilitiesToPreserve",
        "canonicalizationGates",
    ):
        values = data[field]
        require(len(values) == len(set(values)), f"{field} contains duplicates")

    cargo_name, cargo_repository = cargo_package_fields(
        (root / "Cargo.toml").read_text(encoding="utf-8")
    )
    require(cargo_name == artifact["cargoPackage"],
            "Cargo package identity changed without a lineage decision")
    require(cargo_repository == artifact["cargoRepository"],
            "Cargo repository identity changed without a lineage decision")

    agents = (root / "agents.md").read_text(encoding="utf-8")
    require(
        "These instructions apply to `agent-pontifex/ai-agent-bridge.rs`" in agents,
        "agents.md scopes the wrong repository",
    )
    require(
        "These instructions apply to `ORESoftware/ai-agent-bridge.rs`" not in agents,
        "agents.md still claims the ORESoftware repository",
    )
    require("Neither repository is an authorized deprecation target" in agents,
            "agents.md is missing the fail-closed deprecation rule")
    require("repository-lineage.json" in agents,
            "agents.md must route canonicalization through the lineage record")

    uppercase = (root / "AGENTS.md").read_text(encoding="utf-8")
    require("agents.md" in uppercase and "Compatibility pointer" in uppercase,
            "AGENTS.md must be a compatibility pointer to lowercase agents.md")
    require(len(uppercase.splitlines()) <= 8,
            "AGENTS.md must not become a second drifting policy copy")

    readme_head = "\n".join(
        (root / "README.md").read_text(encoding="utf-8").splitlines()[:12]
    ).upper()
    require("DEPRECATED" not in readme_head,
            "README must not deprecate an active divergent repository")
    require(not (root / "DEPRECATED.md").exists(),
            "DEPRECATED.md is forbidden while deprecationAllowed is false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        validate(args.root.resolve())
    except (OSError, ValidationError) as error:
        print(f"repository lineage: FAIL: {error}", file=sys.stderr)
        return 1
    print("repository lineage: PASS (active-divergent; deprecation blocked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
