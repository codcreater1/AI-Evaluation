#!/usr/bin/env python3
"""Build datasets/internship-coordinator/v1.jsonl from real, verified runs.

Why this exists instead of hand-written fixtures (PROJECT_PLAN.md §4.7): the
Internship Coordinator repo already ships its own synthetic-document
generator with 9 scenarios (testdocs/tool/completion_docs.py) and its own
`EXPECTED` outcomes. Rather than re-guess golden cases, this script drives
that real generator, runs each package through a *freshly started, isolated*
instance of the real service, and records what actually came back as the
case's expected_output — so the dataset is verified ground truth, not a
guess about what the system should do.

IMPORTANT — the shared-corpus finding (PROJECT_PLAN.md §4.7 / §7): the
originality/plagiarism check keeps mutable state (SQLite + an in-memory
TF-IDF corpus) across submissions. Running all 9 scenarios against one
long-lived instance makes every one of them (not just "copied") trip
REPORT_NOT_ORIGINAL, because they share nearly identical report boilerplate
text. To get each scenario's *intended*, isolated outcome:
  - 7 single-issue scenarios each run against their own fresh instance.
  - "clean" and "copied" run together against one shared fresh instance,
    "clean" first — "copied" is only meaningful once something is in the
    corpus for it to copy.

Usage:
    python scripts/build_internship_coordinator_dataset.py \\
        --source-repo /path/to/Internship-report-reviewer \\
        --out datasets/internship-coordinator/v1.jsonl

Requires the source repo's backend venv to already have its dependencies
installed (see that repo's README) and `httpx` available.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

SCENARIOS = [
    "clean",
    "short-days",
    "name-mismatch",
    "unsigned",
    "thin-report",
    "weekend-pad",
    "future-dates",
    "scan",
    "copied",
]

# scenario -> (expected status, finding codes that must appear)
EXPECTED_FINDINGS = {
    "clean": ("approved", []),
    "short-days": ("request_clarification", ["DAYS_SHORT"]),
    "name-mismatch": ("request_clarification", ["NAME_MISMATCH"]),
    "unsigned": ("request_clarification", ["EVAL_UNSIGNED"]),
    "thin-report": ("request_clarification", ["REPORT_SHORT"]),
    "weekend-pad": ("request_clarification", ["DAYS_SHORT"]),
    "future-dates": ("request_clarification", ["FUTURE_DATES"]),
    "scan": ("request_clarification", ["ATTACHMENT_NOT_TEXT"]),
    "copied": ("rejected", ["REPORT_NOT_ORIGINAL"]),
}

CATEGORY = {
    "clean": "valid_application",
    "short-days": "incomplete_information",
    "name-mismatch": "conflicting_information",
    "unsigned": "missing_documents",
    "thin-report": "incomplete_information",
    "weekend-pad": "edge_case",
    "future-dates": "edge_case",
    "scan": "unreadable_document",
    "copied": "originality_violation",
}


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _wait_healthy(port: int, timeout_s: float = 15) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).raise_for_status()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise RuntimeError(f"Service on port {port} never became healthy")


def _start_service(source_repo: Path, port: int, db_path: Path, storage_root: Path):
    venv_uvicorn = source_repo / "backend" / ".venv" / "bin" / "uvicorn"
    uvicorn_bin = str(venv_uvicorn) if venv_uvicorn.exists() else "uvicorn"
    proc = subprocess.Popen(
        [uvicorn_bin, "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(source_repo / "backend"),
        env={
            "PATH": "/usr/bin:/bin",
            "REVIEW_DB_PATH": str(db_path),
            "REVIEW_STORAGE_ROOT": str(storage_root),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_healthy(port)
    return proc


def _submit(port: int, doc_dir: Path, application_id: str) -> dict:
    files = [
        (
            "files",
            (
                name,
                (doc_dir / name).read_bytes(),
                "application/pdf",
            ),
        )
        for name in ("internship_report.pdf", "evaluation_form.pdf", "attendance_record.pdf")
    ]
    data = {"intern_email": "student@example.edu", "application_id": application_id}
    with httpx.Client(timeout=60) as client:
        resp = client.post(f"http://127.0.0.1:{port}/reports/", data=data, files=files)
        resp.raise_for_status()
        return resp.json()


def _to_case(scenario: str, doc_dir: Path, response: dict) -> dict:
    expected_status, must_include = EXPECTED_FINDINGS[scenario]
    attachments = [
        {
            "filename": name,
            "content_base64": base64.b64encode((doc_dir / name).read_bytes()).decode("ascii"),
        }
        for name in ("internship_report.pdf", "evaluation_form.pdf", "attendance_record.pdf")
    ]
    return {
        "id": f"ic-{scenario}",
        "system": "internship-coordinator",
        "input": {
            "intern_email": "student@example.edu",
            "application_id": f"scenario-{scenario}",
            "attachments": attachments,
        },
        "expected_output": {
            "status": expected_status,
            "must_include_finding_codes": must_include,
            # Verified structured facts actually returned for THIS run — used
            # by document_field_accuracy. Captured from the real response
            # rather than guessed.
            "student_name": response.get("student_name"),
            "student_id": response.get("student_id"),
            "company": response.get("company"),
        },
        "metadata": {
            "scenario": scenario,
            "category": CATEGORY[scenario],
            "source": "generated by Internship-report-reviewer's own "
            "testdocs/tool/completion_docs.py, run against a real instance",
            "requires_fresh_instance": scenario not in ("clean", "copied"),
            "corpus_group": "originality-pair" if scenario in ("clean", "copied") else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, default=Path("datasets/internship-coordinator/v1.jsonl")
    )
    parser.add_argument("--samples-dir", type=Path, default=Path("/tmp/ic-samples"))
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    if not (args.source_repo / "backend" / "app" / "main.py").exists():
        sys.exit(f"{args.source_repo} doesn't look like an Internship-report-reviewer checkout")

    # 1. Generate all 9 scenarios' documents using the real repo's own tool.
    subprocess.run(
        [
            sys.executable,
            str(args.source_repo / "testdocs" / "tool" / "completion_docs.py"),
            "--all",
            "--out",
            str(args.samples_dir),
        ],
        check=True,
    )

    cases: dict[str, dict] = {}

    # 2. The 7 single-issue scenarios: each against its own fresh instance.
    for scenario in SCENARIOS:
        if scenario in ("clean", "copied"):
            continue
        db_path = args.source_repo / "backend" / f"_ds_{scenario}.db"
        storage = args.source_repo / "backend" / f"_ds_{scenario}_tmp"
        db_path.unlink(missing_ok=True)
        proc = _start_service(args.source_repo, args.port, db_path, storage)
        try:
            response = _submit(args.port, args.samples_dir / scenario, f"scenario-{scenario}")
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            db_path.unlink(missing_ok=True)
        cases[scenario] = _to_case(scenario, args.samples_dir / scenario, response)
        print(f"{scenario:15s} -> status={response['status']}")

    # 3. clean + copied: one shared fresh instance, clean submitted first.
    db_path = args.source_repo / "backend" / "_ds_pair.db"
    storage = args.source_repo / "backend" / "_ds_pair_tmp"
    db_path.unlink(missing_ok=True)
    proc = _start_service(args.source_repo, args.port, db_path, storage)
    try:
        clean_response = _submit(args.port, args.samples_dir / "clean", "scenario-clean")
        copied_response = _submit(args.port, args.samples_dir / "copied", "scenario-copied")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        db_path.unlink(missing_ok=True)
    cases["clean"] = _to_case("clean", args.samples_dir / "clean", clean_response)
    cases["copied"] = _to_case("copied", args.samples_dir / "copied", copied_response)
    print(f"{'clean':15s} -> status={clean_response['status']}")
    print(f"{'copied':15s} -> status={copied_response['status']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for scenario in SCENARIOS:
            f.write(json.dumps(cases[scenario]) + "\n")

    print(f"\nWrote {len(cases)} verified cases to {args.out}")


if __name__ == "__main__":
    main()
