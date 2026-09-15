import json
from decimal import Decimal
from pathlib import Path

import pytest

from blue_wren.application.eval_runner import (
    load_expected_findings,
    run_replay_evaluation,
)
from blue_wren.cli.eval_smoke import main
from blue_wren.domain.findings import FindingStatus

FIXTURES = Path(__file__).parent / "fixtures"
EVENT = FIXTURES / "acme_q2_2026.json"
EXPECTED = FIXTURES / "acme_q2_2026.expected.json"


def test_load_expected_findings_preserves_financial_values() -> None:
    findings = load_expected_findings(EXPECTED)

    assert len(findings) == 1
    assert findings[0].actual == Decimal("125.0")
    assert findings[0].delta == Decimal("5.0")
    assert findings[0].status is FindingStatus.PROPOSED


def test_run_replay_evaluation_passes_a_golden_case() -> None:
    report = run_replay_evaluation(event_path=EVENT, expected_path=EXPECTED)

    assert report.passed is True
    assert report.true_positives == 1
    assert report.critical_errors == ()


def test_run_replay_evaluation_fails_a_changed_expectation(tmp_path: Path) -> None:
    expected_path = tmp_path / "wrong.expected.json"
    payload = json.loads(EXPECTED.read_text(encoding="utf-8"))
    payload["findings"][0]["delta"] = "50.0"
    expected_path.write_text(json.dumps(payload), encoding="utf-8")

    report = run_replay_evaluation(event_path=EVENT, expected_path=expected_path)

    assert report.passed is False
    assert report.critical_errors == ("revenue: delta mismatch",)


def test_eval_smoke_cli_returns_success_and_machine_readable_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(EVENT), str(EXPECTED)])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "critical_errors": [],
        "false_negatives": 0,
        "false_positives": 0,
        "passed": True,
        "precision": 1.0,
        "recall": 1.0,
        "true_positives": 1,
    }


def test_eval_smoke_cli_returns_failure_for_a_regression(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_path = tmp_path / "wrong.expected.json"
    payload = json.loads(EXPECTED.read_text(encoding="utf-8"))
    payload["findings"][0]["actual"] = "999.0"
    expected_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main([str(EVENT), str(expected_path)])

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is False
    assert output["critical_errors"] == ["revenue: actual mismatch"]
