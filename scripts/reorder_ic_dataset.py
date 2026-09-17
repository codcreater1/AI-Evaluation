#!/usr/bin/env python3
import json
from pathlib import Path

ORDER = [
    "ic-short-days",
    "ic-name-mismatch",
    "ic-unsigned",
    "ic-thin-report",
    "ic-weekend-pad",
    "ic-future-dates",
    "ic-scan",
    "ic-clean",
    "ic-copied",
]

def main():
    src = Path("datasets/internship-coordinator/v1.jsonl")
    dst = Path("datasets/internship-coordinator/v2.jsonl")
    cases = {}
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                obj = json.loads(line)
                cases[obj["id"]] = obj
    missing = [cid for cid in ORDER if cid not in cases]
    if missing:
        raise SystemExit(f"v1.jsonl is missing case ids: {missing}")
    with dst.open("w", encoding="utf-8") as f:
        for case_id in ORDER:
            f.write(json.dumps(cases[case_id], ensure_ascii=False) + "\n")
    print(f"Wrote {dst} with {len(ORDER)} cases in the new order.")

if __name__ == "__main__":
    main()