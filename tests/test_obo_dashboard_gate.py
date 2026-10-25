from __future__ import annotations

from copy import deepcopy
import hashlib
import pytest

from tools.obo_dashboard_gate import (
    DEFAULT_CONFIG,
    DEFAULT_IMAGE,
    EXPECTED_RESULTS,
    OBO_DASHBOARD_COMMIT,
    PUBLIC_DASHBOARD_URL,
    ROBOT_GATEWAY_SHA256,
    ROBOT_GATEWAY_VERSION,
    ROBOT_VERSION,
    assess_dashboard,
    assess_public_dashboard_version,
    assess_pending_release,
)


def _pending_release(tmp_path):
    version = "2026-10-25"
    iri = f"http://purl.obolibrary.org/obo/flopo/releases/{version}/flopo.owl"
    ontology = tmp_path / "flopo.owl"
    ontology.write_text(f'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns:owl="http://www.w3.org/2002/07/owl#">
      <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">
      <owl:versionIRI rdf:resource="{iri}"/><owl:versionInfo>{version}</owl:versionInfo>
      </owl:Ontology></rdf:RDF>''')
    data = _passing_dashboard()
    data["version"] = iri
    data["sha256_hash"] = hashlib.sha256(ontology.read_bytes()).hexdigest()
    data["results"]["FP04 Versioning"] = {
        "status": "ERROR",
        "comment": "Version IRI does not resolve",
    }
    data["summary"] = {"status": "ERROR", "summary_count": {"ERROR": 1}}
    return data, ontology, version


def test_pending_release_defers_only_publication_and_preserves_real_report(tmp_path):
    data, ontology, version = _pending_release(tmp_path)
    original = deepcopy(data)
    assert not assess_dashboard(data).passed
    assert assess_pending_release(data, ontology, version).passed
    assert data == original
    assert not assess_dashboard(data).passed


@pytest.mark.parametrize(
    "kind", ["robot", "other", "missing", "unsatisfiable", "bad_versioning", "extra_summary_error"]
)
def test_pending_release_keeps_other_failures_closed(tmp_path, kind):
    data, ontology, version = _pending_release(tmp_path)
    if kind == "robot":
        data["results"]["ROBOT Report"]["results"]["ERROR"] = 1
    elif kind == "other":
        data["results"]["FP06 Textual Definitions"]["status"] = "ERROR"
    elif kind == "missing":
        del data["results"]["FP20 Responsiveness"]
    elif kind == "unsatisfiable":
        data["metrics"]["Entities: Number of unsatisfiable classes"] = 1
    elif kind == "bad_versioning":
        data["results"]["FP04 Versioning"]["comment"] = "Missing version IRI"
    else:
        data["summary"]["summary_count"]["ERROR"] = 2
    assert not assess_pending_release(data, ontology, version).passed


def test_pending_release_cannot_approve_another_version(tmp_path):
    data, ontology, version = _pending_release(tmp_path)
    with pytest.raises(ValueError, match="metadata"):
        assess_pending_release(data, ontology, "2026-10-26")
    data["version"] = "wrong"
    with pytest.raises(ValueError, match="different release"):
        assess_pending_release(data, ontology, version)


def test_pending_release_checks_exact_artifact_hash(tmp_path):
    data, ontology, version = _pending_release(tmp_path)
    data["sha256_hash"] = "wrong"
    with pytest.raises(ValueError, match="exact artifact bytes"):
        assess_pending_release(data, ontology, version)


def _passing_dashboard() -> dict:
    data = {
        "results": {name: {"status": "PASS"} for name in EXPECTED_RESULTS},
        "summary": {"status": "PASS", "summary_count": {"ERROR": 0}},
        "metrics": {
            "Info: Logical consistency": True,
            "Entities: Number of unsatisfiable classes": 0,
            "Info: Syntax": "RDF/XML Syntax",
        },
    }
    data["results"]["ROBOT Report"]["results"] = {
        "ERROR": 0,
        "WARN": 0,
        "INFO": 0,
    }
    return data


def test_dashboard_gate_covers_every_current_official_check():
    assert EXPECTED_RESULTS == {
        "FP01 Open",
        "FP02 Common Format",
        "FP03 URIs",
        "FP04 Versioning",
        "FP05 Scope",
        "FP06 Textual Definitions",
        "FP07 Relations",
        "FP08 Documented",
        "FP09 Plurality of Users",
        "FP11 Locus of Authority",
        "FP12 Naming Conventions",
        "FP16 Maintenance",
        "FP20 Responsiveness",
        "ROBOT Report",
    }
    assert OBO_DASHBOARD_COMMIT == "c3601a04810d5298643bcc6468acd2a5c3d0f08e"
    assert ROBOT_VERSION == "1.9.8"
    assert ROBOT_GATEWAY_VERSION == "1.9.5"
    assert len(ROBOT_GATEWAY_SHA256) == 64
    assert "@sha256:" in DEFAULT_IMAGE
    config = DEFAULT_CONFIG.read_text(encoding="utf-8")
    assert "v1.9.8" in config
    assert "id: flopo" in config
    assert PUBLIC_DASHBOARD_URL == "https://dashboard.obofoundry.org/dashboard/index.html"


def test_public_dashboard_pin_check_fails_closed_on_upstream_change():
    current = (
        '<a href="https://github.com/OBOFoundry/OBO-Dashboard/commit/'
        f'{OBO_DASHBOARD_COMMIT}">source</a> ROBOT version {ROBOT_VERSION}'
    )
    assert assess_public_dashboard_version(current).passed

    changed = current.replace(OBO_DASHBOARD_COMMIT, "a" * 40).replace(
        f"ROBOT version {ROBOT_VERSION}", "ROBOT version 2.0.0"
    )
    assessment = assess_public_dashboard_version(changed)
    assert not assessment.passed
    assert any("commit" in failure for failure in assessment.failures)
    assert any("ROBOT 2.0.0" in failure for failure in assessment.failures)


def test_public_dashboard_pin_check_rejects_unparseable_page():
    assessment = assess_public_dashboard_version("maintenance")
    assert not assessment.passed
    assert len(assessment.failures) == 2


def test_dashboard_pass_policy_accepts_non_error_notices():
    data = _passing_dashboard()
    data["results"]["FP06 Textual Definitions"] = {
        "status": "WARN",
        "comment": "one missing definition",
    }
    data["summary"]["status"] = "WARN"
    assessment = assess_dashboard(data)
    assert assessment.passed
    assert assessment.notices == ("FP06 Textual Definitions = WARN: one missing definition",)


def test_dashboard_gate_rejects_any_error_result():
    data = _passing_dashboard()
    data["results"]["FP04 Versioning"] = {
        "status": "ERROR",
        "comment": "Version IRI does not resolve",
    }
    data["summary"] = {"status": "ERROR", "comment": "1 error"}
    assessment = assess_dashboard(data)
    assert not assessment.passed
    assert any("FP04 Versioning = ERROR" in failure for failure in assessment.failures)
    assert any("summary = ERROR" in failure for failure in assessment.failures)


def test_dashboard_gate_rejects_missing_or_new_unreviewed_checks():
    data = _passing_dashboard()
    del data["results"]["FP20 Responsiveness"]
    data["results"]["FP99 Future Check"] = {"status": "PASS"}
    assessment = assess_dashboard(data)
    assert not assessment.passed
    assert any("did not run checks" in failure for failure in assessment.failures)
    assert any("Unreviewed Dashboard checks" in failure for failure in assessment.failures)


def test_dashboard_gate_rejects_reasoning_or_format_failure():
    data = _passing_dashboard()
    data["metrics"]["Info: Logical consistency"] = False
    data["metrics"]["Entities: Number of unsatisfiable classes"] = 3
    data["metrics"]["Info: Syntax"] = "Turtle Syntax"
    assessment = assess_dashboard(data)
    assert not assessment.passed
    assert len(assessment.failures) == 3


def test_dashboard_gate_rejects_missing_summary_or_robot_counts():
    data = _passing_dashboard()
    del data["summary"]
    del data["results"]["ROBOT Report"]["results"]
    assessment = assess_dashboard(data)
    assert not assessment.passed
    assert any("summary status" in failure for failure in assessment.failures)
    assert any("ROBOT Report error count" in failure for failure in assessment.failures)


def test_dashboard_gate_rejects_hidden_robot_errors():
    data = _passing_dashboard()
    data["results"]["ROBOT Report"] = {
        "status": "WARN",
        "results": {"ERROR": 2, "WARN": 1, "INFO": 0},
    }
    assessment = assess_dashboard(data)
    assert not assessment.passed
    assert "ROBOT Report contains 2 errors" in assessment.failures


def test_all_pass_mode_is_stricter_than_dashboard_pass_policy():
    data = _passing_dashboard()
    data["results"]["FP07 Relations"] = {"status": "INFO"}
    data["summary"]["status"] = "INFO"
    assert assess_dashboard(deepcopy(data)).passed
    assert not assess_dashboard(data, require_all_pass=True).passed
