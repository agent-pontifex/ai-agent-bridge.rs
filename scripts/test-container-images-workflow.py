#!/usr/bin/env python3
"""Dependency-free regression tests for GHCR publication ownership.

The repository moved from ORESoftware to agent-pontifex. A workflow that keeps a
literal former owner can build and scan successfully on pull requests, then fail
only after merge when it attempts to publish. These checks keep image names and
the requested GHCR token scope derived from the repository's current owner.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container-images.yml"


class ContainerImagesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def named_step(self, name: str) -> str:
        marker = f"      - name: {name}\n"
        self.assertIn(marker, self.text)
        remainder = self.text.split(marker, 1)[1]
        boundaries = [
            position
            for position in (
                remainder.find("\n      - name:"),
                remainder.find("\n      - uses:"),
            )
            if position >= 0
        ]
        return remainder[: min(boundaries)] if boundaries else remainder

    def test_package_write_permission_is_explicit(self) -> None:
        marker = "\npermissions:\n"
        self.assertIn(marker, self.text)
        permissions = self.text.split(marker, 1)[1].split("\n\n", 1)[0]
        permission_lines = {
            line.strip() for line in permissions.splitlines() if line.strip()
        }
        self.assertIn("contents: read", permission_lines)
        self.assertIn("packages: write", permission_lines)

    def test_image_namespace_tracks_current_repository_owner(self) -> None:
        self.assertIn(
            "images: ghcr.io/${{ github.repository_owner }}/${{ matrix.image }}",
            self.text,
        )

    def test_login_scope_tracks_the_same_repository_owner(self) -> None:
        self.assertIn(
            "scope: ${{ github.repository_owner }}/${{ matrix.image }}@push",
            self.text,
        )

    def test_no_legacy_ghcr_owner_is_hard_coded(self) -> None:
        lowered = self.text.lower()
        for former_owner in ("oresoftware", "fiducia-cloud"):
            with self.subTest(former_owner=former_owner):
                self.assertNotIn(f"ghcr.io/{former_owner}/", lowered)
                self.assertNotIn(f"scope: {former_owner}/", lowered)

    def test_publish_and_login_remain_push_only(self) -> None:
        for name in (
            "Log in to GitHub Container Registry",
            "Publish digest-addressable image with SBOM and provenance",
        ):
            with self.subTest(step=name):
                self.assertIn(
                    "if: github.event_name == 'push'", self.named_step(name)
                )

    def test_pull_requests_still_build_and_scan_without_publishing(self) -> None:
        self.assertIn("push: false", self.text)
        self.assertIn("Scan image for high and critical vulnerabilities", self.text)
        self.assertIn("severity: HIGH,CRITICAL", self.text)

    def test_workflow_retriggers_when_this_regression_test_changes(self) -> None:
        self.assertIn("- scripts/test-container-images-workflow.py", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
