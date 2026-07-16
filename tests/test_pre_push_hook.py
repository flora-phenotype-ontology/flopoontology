from __future__ import annotations

import subprocess
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
