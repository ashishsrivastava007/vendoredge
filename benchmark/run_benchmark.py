"""
VendorEdge Benchmark Harness

HONEST NOTE, READ THIS FIRST: this script requires a real ANTHROPIC_API_KEY
and a real running instance of VendorEdge (local or deployed). It cannot be
run by Claude in this build session -- no live key is available here. This
is the tool; you are the one who runs it, going forward, before any future
prompt change, to catch regressions across the growing set of Hard Rules.

Usage:
    export ANTHROPIC_API_KEY=your-real-key
    export VENDOREDGE_BASE_URL=http://localhost:8000   # or your deployed URL
    python3 benchmark/run_benchmark.py

What it does:
    1. Creates a fresh workspace.
    2. Runs each curated case in cases.py through the real, live system.
    3. Checks the real response against that case's checklist.
    4. Prints a pass/fail summary -- does NOT judge reasoning quality,
       only structural correctness (did the guaranteed fields show up
       when they should, stay absent when they shouldn't).

This deliberately does NOT try to judge whether the reasoning is GOOD --
that's a human judgment call, the same one you've made all night reading
real responses. This only checks the things that are supposed to be
guaranteed or reliably triggered, so a future prompt change can't silently
break something that used to work.
"""
import os
import sys
import time
import requests

from cases import BENCHMARK_CASES

BASE_URL = os.environ.get("VENDOREDGE_BASE_URL", "http://localhost:8000")


def run_case(session_headers, case):
    """Submits one case, follows the evidence-gathering flow if needed,
    and returns the final completed decision -- or None if it never
    completed, which is itself a real finding worth reporting."""
    res = requests.post(
        f"{BASE_URL}/api/v1/commercial-decisions",
        headers=session_headers,
        json={"raw_question": case["question"]},
    )
    if res.status_code != 200:
        return None, f"Initial request failed: {res.status_code} {res.text[:200]}"

    data = res.json()

    # If evidence is missing, supply the case's pre-filled answers and
    # continue -- a real benchmark case should specify what a real user
    # would have answered, not leave the harness guessing.
    if data["status"] == "awaiting_user_input":
        answers = case.get("evidence_answers", {})
        res2 = requests.post(
            f"{BASE_URL}/api/v1/commercial-decisions/{data['id']}/respond",
            headers=session_headers,
            json={"user_supplied_inputs": answers},
        )
        if res2.status_code != 200:
            return None, f"Respond step failed: {res2.status_code} {res2.text[:200]}"
        data = res2.json()

    if data["status"] != "completed":
        return None, f"Never reached completed status (ended at: {data['status']})"

    return data, None


def check_case(case, result):
    """Runs the case's checklist against the real response. Returns a
    list of (passed: bool, description: str) tuples."""
    checks = []
    position = result.get("commercial_position", {})
    for check_fn, description in case["checklist"]:
        try:
            passed = check_fn(position)
        except Exception as e:
            passed = False
            description = f"{description} (checklist itself errored: {e})"
        checks.append((passed, description))
    return checks


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set. This must be run with a real key.")
        sys.exit(1)

    print(f"Running benchmark against {BASE_URL}\n")

    ws_res = requests.post(f"{BASE_URL}/api/v1/workspaces")
    ws = ws_res.json()
    headers = {"x-org-id": ws["organisation_id"], "x-user-id": ws["user_id"], "Content-Type": "application/json"}
    print(f"Created benchmark workspace: {ws['organisation_id']}\n")

    total_passed, total_failed = 0, 0

    for case in BENCHMARK_CASES:
        print(f"--- {case['name']} ---")
        result, error = run_case(headers, case)
        if error:
            print(f"  FAILED TO COMPLETE: {error}\n")
            total_failed += 1
            continue

        checks = check_case(case, result)
        for passed, description in checks:
            symbol = "PASS" if passed else "FAIL"
            print(f"  [{symbol}] {description}")
            if passed:
                total_passed += 1
            else:
                total_failed += 1
        print()
        time.sleep(1)  # be polite to the API, this costs real money per case

    print(f"\n=== SUMMARY: {total_passed} passed, {total_failed} failed ===")
    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
