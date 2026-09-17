import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from blue_wren.application.eval_runner import run_evaluation_suite
from blue_wren.domain.evaluation import EvaluationReport


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    args = parser.parse_args(argv)
    suite = run_evaluation_suite(args.cases)
    print(
        json.dumps(
            {
                "passed": suite.passed,
                "cases": {result.case_id: _report(result.report) for result in suite.cases},
            },
            sort_keys=True,
        )
    )
    return 0 if suite.passed else 1


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


if __name__ == "__main__":
    raise SystemExit(main())
