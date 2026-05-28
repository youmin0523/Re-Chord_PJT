"""Run the full accuracy suite and gate against tests/fixtures/accuracy_thresholds.json.

Usage:
    uv run python scripts/run_accuracy_suite.py [--quick] [--no-real]

Subcommands run in order:
    1. measure_accuracy.py        — synth signals (key/BPM/onset/chord)
    2. measure_real_accuracy_v4.py — real-world worship URLs (requires live backend)
    3. pytest tests/test_accuracy_thresholds.py — gate report against thresholds

This is the single command CI / pre-release should call. Exits non-zero if
any hard threshold is missed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
THRESHOLDS = ROOT / "tests" / "fixtures" / "accuracy_thresholds.json"


def run(cmd: list[str], label: str) -> int:
    print(f"\n=== {label} ===")
    print(f"  $ {' '.join(cmd)}")
    p = subprocess.run(cmd, cwd=str(ROOT))
    print(f"  → exit {p.returncode}")
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="skip the real-world URL benchmark (slow)")
    ap.add_argument("--no-real", action="store_true",
                    help="skip the real-world URL benchmark (alias)")
    ap.add_argument("--skip-synth", action="store_true",
                    help="skip the synth signal benchmark")
    args = ap.parse_args()

    if not THRESHOLDS.exists():
        print(f"[fatal] thresholds missing: {THRESHOLDS}", file=sys.stderr)
        return 1

    print(f"[info] thresholds source: {THRESHOLDS}")
    spec = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    print(f"[info] threshold groups: {sorted(spec.keys())}")

    if not args.skip_synth:
        rc = run([sys.executable, str(ROOT / "scripts" / "measure_accuracy.py")],
                 "1/3 synth accuracy")
        if rc != 0:
            print("[warn] synth measurement returned non-zero — continuing to gate check")

    if not (args.quick or args.no_real):
        rc = run([sys.executable, str(ROOT / "scripts" / "measure_real_accuracy_v4.py")],
                 "2/3 real-world accuracy")
        if rc != 0:
            print("[warn] real-world measurement failed — gate may report no-data")

    rc = run([sys.executable, "-m", "pytest", "-v",
              str(ROOT / "tests" / "test_accuracy_thresholds.py")],
             "3/3 accuracy gate (vs thresholds)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
