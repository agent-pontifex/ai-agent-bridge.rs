#!/usr/bin/env python3
"""Dependency-free regression tests for GHCR publication ownership.

The repository moved from ORESoftware to agent-pontifex. A workflow that keeps a
literal former owner can build and scan successfully on pull requests, then fail
only after merge when it attempts to publish. These checks keep image names and
the requested GHCR token scope derived from the repository's current owner.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container-images.yml"


class ContainerImagesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_package_write_permission_is_explicit(self) -> None:
        self.assertRegex(
            self.text,
            r"(?ms)^permissions:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+packages:[ \t]+write\s*$",
        )

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
        self.assertNotRegex(self.text.lower(), r"ghcr\.io/(?:oresoftware|fiducia-cloud)/")
        self.assertNotRegex(
            self.text.lower(),
            r"scope:\s*(?:oresoftware|fiducia-cloud)/",
        )

    def test_publish_and_login_remain_push_only(self) -> None:
        guarded_steps = re.findall(
            r"(?ms)^      - name: (Log in to GitHub Container Registry|Publish digest-addressable image with SBOM and provenance)\n(.*?)(?=^      - name:|\Z)",
            self.text,
        )
        self.assertEqual(len(guarded_steps), 2)
        for name, body in guarded_steps:
            with self.subTest(step=name):
                self.assertIn("if: github.event_name == 'push'", body)

    def test_pull_requests_still_build_and_scan_without_publishing(self) -> None:
        self.assertIn("push: false", self.text)
        self.assertIn("Scan image for high and critical vulnerabilities", self.text)
        self.assertIn("severity: HIGH,CRITICAL", self.text)

    def test_workflow_retriggers_when_this_regression_test_changes(self) -> None:
        self.assertIn("- scripts/test-container-images-workflow.py", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
