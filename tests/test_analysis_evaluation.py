import json
from pathlib import Path

import pytest

from blue_wren.application.analysis_evaluation import (
    AnalysisFixtureError,
    discover_analysis_cases,
    run_analysis_evaluation,
    run_analysis_suite,
)
from blue_wren.cli.eval_smoke import main

FIXTURES = Path(__file__).parent / "fixtures"
ANALYSIS = FIXTURES / "analysis"


def test_analysis_suite_passes_every_shipped_case() -> None:
    suite = run_analysis_suite(ANALYSIS)

    assert suite.passed is True
    assert sorted(result.case_id for result in suite.cases) == [
        "budget_exhausted",
        "coverage_gap",
        "golden_complete",
        "injected_instruction",
        "missing_basis",
        "non_verbatim_value",
        "post_cutoff_source",
    ]
    by_id = {result.case_id: result.report for result in suite.cases}
    assert by_id["golden_complete"].coverage == 1
    assert by_id["coverage_gap"].coverage == 0.5
    assert by_id["injected_instruction"].rejection_recall == 1
    assert by_id["post_cutoff_source"].status is None


def test_wrong_expected_status_is_a_critical_error(tmp_path: Path) -> None:
    for suffix in (".scope.json", ".provider.json", ".expected.json"):
        (tmp_path / f"golden_complete{suffix}").write_text(
            (ANALYSIS / f"golden_complete{suffix}").read_text(encoding="utf-8")
        )
    expected = json.loads((tmp_path / "golden_complete.expected.json").read_text())
    expected["status"] = "partial"
    expected["observations"] = expected["observations"][:1]
    (tmp_path / "golden_complete.expected.json").write_text(json.dumps(expected))

    report = run_analysis_evaluation(tmp_path, "golden_complete")

    assert report.passed is False
    assert any(error.startswith("status mismatch") for error in report.critical_errors)
    assert any(error.startswith("unexpected observation") for error in report.critical_errors)


def test_missing_rejection_is_a_critical_error(tmp_path: Path) -> None:
    for suffix in (".scope.json", ".provider.json", ".expected.json"):
        (tmp_path / f"injected_instruction{suffix}").write_text(
            (ANALYSIS / f"injected_instruction{suffix}").read_text(encoding="utf-8")
        )
    expected = json.loads((tmp_path / "injected_instruction.expected.json").read_text())
    expected["rejections"] = ["value_not_numeric"]
    (tmp_path / "injected_instruction.expected.json").write_text(json.dumps(expected))

    report = run_analysis_evaluation(tmp_path, "injected_instruction")

    assert report.passed is False
    assert "missing rejection: value_not_numeric" in report.critical_errors
    assert report.rejection_recall == 0


def test_discovery_requires_companions_and_cases(tmp_path: Path) -> None:
    with pytest.raises(AnalysisFixtureError, match="no analysis cases"):
        discover_analysis_cases(tmp_path)
    (tmp_path / "orphan.expected.json").write_text("{}")
    with pytest.raises(AnalysisFixtureError, match="missing orphan.scope.json"):
        discover_analysis_cases(tmp_path)


def test_cli_reports_both_suites(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(FIXTURES), "--analysis", str(ANALYSIS)])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert len(output["analysis_cases"]) == 7
    assert output["analysis_cases"]["budget_exhausted"]["status"] == "failed"
