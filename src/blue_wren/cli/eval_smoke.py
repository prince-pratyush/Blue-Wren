import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from blue_wren.application.analysis_evaluation import AnalysisEvaluationReport, run_analysis_suite
from blue_wren.application.eval_runner import run_evaluation_suite
from blue_wren.domain.evaluation import EvaluationReport


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--analysis", type=Path, default=None)
    args = parser.parse_args(argv)
    suite = run_evaluation_suite(args.cases)
    output: dict[str, object] = {
        "passed": suite.passed,
        "cases": {result.case_id: _report(result.report) for result in suite.cases},
    }
    if args.analysis is not None:
        analysis = run_analysis_suite(args.analysis)
        output["analysis_cases"] = {
            result.case_id: _analysis_report(result.report) for result in analysis.cases
        }
        output["passed"] = suite.passed and analysis.passed
    print(json.dumps(output, sort_keys=True))
    return 0 if output["passed"] else 1


def _report(report: EvaluationReport) -> dict[str, object]:
    return {
        "passed": report.passed,
        "precision": float(report.precision),
        "recall": float(report.recall),
        "true_positives": report.true_positives,
        "false_positives": report.false_positives,
        "false_negatives": report.false_negatives,
        "critical_errors": report.critical_errors,
    }


def _analysis_report(report: AnalysisEvaluationReport) -> dict[str, object]:
    return {
        "passed": report.passed,
        "status": report.status,
        "observation_accuracy": float(report.observation_accuracy),
        "rejection_recall": float(report.rejection_recall),
        "coverage": float(report.coverage),
        "critical_errors": report.critical_errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
