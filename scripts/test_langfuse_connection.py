#!/usr/bin/env python3
"""Standalone Langfuse connectivity smoke test — no need to run the whole
platform first. Reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST
from .env (or the environment), sends one test trace + one score, and prints
a direct link to it so you can confirm it shows up in the Langfuse dashboard.

Written against the modern (v3+) Python SDK's observations-first API
(`start_as_current_observation`, `create_score`) — NOT the old v2 API
(`client.trace(...)`, `client.score(...)`), which `pip install langfuse`
no longer resolves to as of SDK v3 (mid-2025) onward. If you see
`AttributeError: 'Langfuse' object has no attribute 'trace'`, you're
running an older copy of this file against a new SDK — re-download it.

Usage:
    pip install langfuse python-dotenv
    python scripts/test_langfuse_connection.py
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        print("(python-dotenv not installed — reading only real environment variables)")

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        print("ERROR: LANGFUSE_PUBLIC_KEY and/or LANGFUSE_SECRET_KEY not set.")
        print("Make sure your .env file is in this same folder and has real values.")
        sys.exit(1)

    from langfuse import Langfuse

    client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    with client.start_as_current_observation(
        as_type="span",
        name="ai-eval-platform:connection-test",
        input={"note": "hello from ai-eval-platform"},
        metadata={"purpose": "manual smoke test from test_langfuse_connection.py"},
    ) as span:
        trace_id = span.trace_id
        span.update(output={"status": "ok"})
        client.create_score(
            trace_id=trace_id,
            name="smoke_test",
            value=1.0,
            comment="Connection test passed",
        )

    client.flush()

    print("Success! Trace sent.")
    print(f"  Trace ID: {trace_id}")
    print(f"  Check it in your Langfuse dashboard: {host.rstrip('/')}/trace/{trace_id}")


if __name__ == "__main__":
    main()
