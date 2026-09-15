import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from blue_wren.application.eval_runner import run_replay_evaluation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("sources", type=Path)
    args = parser.parse_args(argv)
    report = run_replay_evaluation(
        event_path=args.event,
        expected_path=args.expected,
        source_manifest_path=args.sources,
    )
    print(
        json.dumps(
            {
                "passed": report.passed,
                "precision": float(report.precision),
                "recall": float(report.recall),
                "true_positives": report.true_positives,
                "false_positives": report.false_positives,
                "false_negatives": report.false_negatives,
                "critical_errors": report.critical_errors,
            },
            sort_keys=True,
        )
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
