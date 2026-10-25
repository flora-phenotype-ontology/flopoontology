from __future__ import annotations

import subprocess
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks" / "pre-push"


def test_pre_push_hook_is_valid_and_tests_outgoing_git_objects():
    subprocess.run(["bash", "-n", HOOK], check=True)
    text = HOOK.read_text(encoding="utf-8")

    assert 'git archive "$commit"' in text
    assert "ontology/flopo.owl" in text
    assert "config/obo_dashboard.yml" in text
    assert "tools/obo_dashboard_gate.py" in text
    assert 'python3 "$candidate/tools/obo_dashboard_gate.py"' in text
    assert 'check_commit "$(git rev-parse HEAD)" "HEAD"' in text


def test_pending_release_cannot_update_master():
    result = subprocess.run(
        ["bash", str(HOOK)],
        cwd=ROOT,
        input="refs/heads/feature unused refs/heads/master unused\n",
        env={**os.environ, "FLOPO_PENDING_RELEASE_VERSION": "2026-10-25"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Release staging cannot update master" in result.stderr
    assert "Running the official" not in result.stdout
