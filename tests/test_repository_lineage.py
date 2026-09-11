from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_repository_lineage.py"
FIXTURE_FILES = [
    "repository-lineage.json",
    "Cargo.toml",
    "agents.md",
    "AGENTS.md",
    "README.md",
]


class RepositoryLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.fixture = Path(self.tempdir.name)
        for relative in FIXTURE_FILES:
            shutil.copy2(ROOT / relative, self.fixture / relative)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def validate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), "--root", str(self.fixture)],
            check=False,
            capture_output=True,
            text=True,
        )

    def write_lineage(self, mutate) -> None:
        path = self.fixture / "repository-lineage.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def assert_fails_with(self, expected: str) -> None:
        result = self.validate()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)

    def test_checked_in_lineage_passes(self) -> None:
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deprecation blocked", result.stdout)

    def test_deprecation_cannot_be_enabled_without_schema_transition(self) -> None:
        self.write_lineage(lambda data: data.__setitem__("deprecationAllowed", True))
        self.assert_fails_with("deprecation must remain fail-closed")

    def test_capability_preservation_gates_cannot_be_dropped(self) -> None:
        self.write_lineage(lambda data: data["peerCapabilitiesToPreserve"].pop())
        self.assert_fails_with("peer capability preservation list drifted")

    def test_wrong_repository_scope_is_rejected(self) -> None:
        path = self.fixture / "agents.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "agent-pontifex/ai-agent-bridge.rs",
                "ORESoftware/ai-agent-bridge.rs",
                1,
            ),
            encoding="utf-8",
        )
        self.assert_fails_with("agents.md scopes the wrong repository")

    def test_artifact_rename_requires_lineage_update(self) -> None:
        path = self.fixture / "Cargo.toml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                'name = "fiducia-ai-agent-bridge"',
                'name = "agent-pontifex-bridge"',
                1,
            ),
            encoding="utf-8",
        )
        self.assert_fails_with("Cargo package identity changed")

    def test_deprecated_marker_is_forbidden_while_active(self) -> None:
        (self.fixture / "DEPRECATED.md").write_text("deprecated\n", encoding="utf-8")
        self.assert_fails_with("DEPRECATED.md is forbidden")


if __name__ == "__main__":
    unittest.main()
