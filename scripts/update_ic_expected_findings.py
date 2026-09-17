#!/usr/bin/env python3
import json
from pathlib import Path

UPDATES = {
    "ic-unsigned": ["EVAL_UNSIGNED", "EVAL_UNSTAMPED"],
    "ic-weekend-pad": ["DAYS_SHORT", "TOTAL_DAYS_MISMATCH", "WEEKEND_DAYS"],
    "ic-future-dates": ["FUTURE_DATES", "DAYS_SHORT", "TOTAL_DAYS_MISMATCH"],
    "ic-scan": ["ATTACHMENT_NOT_TEXT", "DOCUMENT_MISSING", "DOCUMENT_UNRECOGNISED"],
}

def main():
    src = Path("datasets/internship-coordinator/v2.jsonl")
    dst = Path("datasets/internship-coordinator/v3.jsonl")
    lines_out = []
    seen = set()
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            case_id = obj["id"]
            if case_id in UPDATES:
                obj["expected_output"]["must_include_finding_codes"] = UPDATES[case_id]
                seen.add(case_id)
            lines_out.append(obj)
    missing = set(UPDATES) - seen
    if missing:
        raise SystemExit(f"v2.jsonl is missing case ids: {missing}")
    with dst.open("w", encoding="utf-8") as f:
        for obj in lines_out:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(f"Wrote {dst}, updated expected findings for {sorted(seen)}")

if __name__ == "__main__":
    main()