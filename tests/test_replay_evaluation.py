import json
from decimal import Decimal
from pathlib import Path

import pytest

from blue_wren.application.eval_runner import (
    EvaluationFixtureError,
    discover_cases,
    load_expected_findings,
    run_replay_evaluation,
)
from blue_wren.cli.eval_smoke import main
from blue_wren.domain.findings import FindingStatus

FIXTURES = Path(__file__).parent / "fixtures"
EVENT = FIXTURES / "acme_q2_2026.json"
EXPECTED = FIXTURES / "acme_q2_2026.expected.json"
SOURCES = FIXTURES / "acme_q2_2026.sources.json"


def test_load_expected_findings_preserves_financial_values() -> None:
    findings = load_expected_findings(EXPECTED)

    assert len(findings) == 1
    assert findings[0].actual == Decimal("125.0")
    assert findings[0].delta == Decimal("5.0")
    assert findings[0].status is FindingStatus.PROPOSED


def test_run_replay_evaluation_passes_a_golden_case() -> None:
    report = run_replay_evaluation(
        event_path=EVENT,
        expected_path=EXPECTED,
        source_manifest_path=SOURCES,
    )

    assert report.passed is True
    assert report.true_positives == 1
    assert report.critical_errors == ()


def test_run_replay_evaluation_fails_a_changed_expectation(tmp_path: Path) -> None:
    expected_path = tmp_path / "wrong.expected.json"
    payload = json.loads(EXPECTED.read_text(encoding="utf-8"))
    payload["findings"][0]["delta"] = "50.0"
    expected_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_replay_evaluation(
        event_path=EVENT,
        expected_path=expected_path,
        source_manifest_path=SOURCES,
    )

    assert report.passed is False
    assert report.critical_errors == ("revenue: delta mismatch",)


def test_eval_smoke_cli_runs_every_case_in_the_directory(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(FIXTURES)])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert sorted(output["cases"]) == [
        "acme_q2_2026",
        "acme_q2_2026_basis_mismatch",
        "acme_q2_2026_no_change",
        "acme_q2_2026_period_mismatch",
        "acme_q2_2026_restated",
        "acme_q2_2026_unit_scale",
    ]
    assert all(case["passed"] for case in output["cases"].values())
    assert output["cases"]["acme_q2_2026"] == {
        "critical_errors": [],
        "false_negatives": 0,
        "false_positives": 0,
        "passed": True,
        "precision": 1.0,
        "recall": 1.0,
        "true_positives": 1,
    }
    assert output["cases"]["acme_q2_2026_period_mismatch"]["passed"] is True


def test_eval_smoke_cli_returns_failure_for_a_regression(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("acme_q2_2026.json", "acme_q2_2026.sources.json"):
        (tmp_path / name).write_text((FIXTURES / name).read_text(encoding="utf-8"))
    payload = json.loads(EXPECTED.read_text(encoding="utf-8"))
    payload["findings"][0]["actual"] = "999.0"
    (tmp_path / "acme_q2_2026.expected.json").write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main([str(tmp_path)])

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is False
    assert output["cases"]["acme_q2_2026"]["critical_errors"] == ["revenue: actual mismatch"]


RESTATED = FIXTURES / "acme_q2_2026_restated"


def test_restatement_marks_the_cited_finding_stale() -> None:
    report = run_replay_evaluation(
        event_path=RESTATED.with_suffix(".json"),
        expected_path=RESTATED.with_suffix(".expected.json"),
        source_manifest_path=RESTATED.with_suffix(".sources.json"),
        restatement_path=RESTATED.with_suffix(".restatement.json"),
    )

    assert report.passed is True
    assert report.critical_errors == ()


def test_expected_stale_outcome_fails_without_a_restatement() -> None:
    report = run_replay_evaluation(
        event_path=RESTATED.with_suffix(".json"),
        expected_path=RESTATED.with_suffix(".expected.json"),
        source_manifest_path=RESTATED.with_suffix(".sources.json"),
    )

    assert report.passed is False
    assert report.critical_errors == ("revenue: review outcome mismatch",)


def test_restatement_of_another_document_leaves_the_finding_pending(tmp_path: Path) -> None:
    restatement_path = tmp_path / "other.restatement.json"
    payload = json.loads(RESTATED.with_suffix(".restatement.json").read_text(encoding="utf-8"))
    payload["document_id"] = "unrelated-document"
    restatement_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_replay_evaluation(
        event_path=RESTATED.with_suffix(".json"),
        expected_path=RESTATED.with_suffix(".expected.json"),
        source_manifest_path=RESTATED.with_suffix(".sources.json"),
        restatement_path=restatement_path,
    )

    assert report.passed is False
    assert report.critical_errors == ("revenue: review outcome mismatch",)


def test_suite_discovery_rejects_an_incomplete_case(tmp_path: Path) -> None:
    (tmp_path / "orphan.expected.json").write_text("{}", encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="missing orphan.json"):
        discover_cases(tmp_path)


def test_suite_discovery_rejects_an_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(EvaluationFixtureError, match="no evaluation cases"):
        discover_cases(tmp_path)


def test_evaluation_rejects_evidence_unavailable_at_the_cutoff(tmp_path: Path) -> None:
    manifest_path = tmp_path / "future.sources.json"
    payload = json.loads(SOURCES.read_text(encoding="utf-8"))
    payload["sources"][0]["available_at"] = "2026-08-20T00:00:01+00:00"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="source was unavailable at cutoff"):
        run_replay_evaluation(
            event_path=EVENT,
            expected_path=EXPECTED,
            source_manifest_path=manifest_path,
        )


def test_evaluation_rejects_expected_evidence_outside_manifest(tmp_path: Path) -> None:
    expected_path = tmp_path / "unknown-source.expected.json"
    payload = json.loads(EXPECTED.read_text(encoding="utf-8"))
    payload["findings"][0]["evidence_document_version_id"] = (
        "acme-q2-results:unlisted-version"
    )
    expected_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="expected evidence is not in source manifest"):
        run_replay_evaluation(
            event_path=EVENT,
            expected_path=expected_path,
            source_manifest_path=SOURCES,
        )


def test_evaluation_rejects_emitted_evidence_outside_manifest(tmp_path: Path) -> None:
    event_path = tmp_path / "unknown-source.json"
    payload = json.loads(EVENT.read_text(encoding="utf-8"))
    payload["comparisons"][0]["actual"]["evidence"]["document_version_id"] = "unlisted-version"
    event_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="emitted evidence is not in source manifest"):
        run_replay_evaluation(
            event_path=event_path,
            expected_path=EXPECTED,
            source_manifest_path=SOURCES,
        )


def test_evaluation_rejects_manifest_for_a_different_event(tmp_path: Path) -> None:
    manifest_path = tmp_path / "different-event.sources.json"
    payload = json.loads(SOURCES.read_text(encoding="utf-8"))
    payload["event_id"] = "different-event"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="manifest event does not match"):
        run_replay_evaluation(
            event_path=EVENT,
            expected_path=EXPECTED,
            source_manifest_path=manifest_path,
        )


def test_evaluation_rejects_duplicate_source_versions(tmp_path: Path) -> None:
    manifest_path = tmp_path / "duplicate.sources.json"
    payload = json.loads(SOURCES.read_text(encoding="utf-8"))
    payload["sources"].append(payload["sources"][0])
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="duplicate versions"):
        run_replay_evaluation(
            event_path=EVENT,
            expected_path=EXPECTED,
            source_manifest_path=manifest_path,
        )


def test_evaluation_requires_timezone_aware_cutoff(tmp_path: Path) -> None:
    manifest_path = tmp_path / "naive-cutoff.sources.json"
    payload = json.loads(SOURCES.read_text(encoding="utf-8"))
    payload["cutoff_at"] = "2026-08-20T00:00:00"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationFixtureError, match="timestamps require a timezone"):
        run_replay_evaluation(
            event_path=EVENT,
            expected_path=EXPECTED,
            source_manifest_path=manifest_path,
        )
