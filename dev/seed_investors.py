"""Demo seed script — populate test investors per Cluster 1 Demo-Stage Addendum §3.1.

Creates a representative spread of investors across the four demo users +
the four life stages + a mix of risk/horizon profiles. Uses the API path
(POST /api/v2/auth/dev-login → POST /api/v2/investors) so the records go
through the same validation + I0 enrichment as real onboarding.

Usage:

    # Backend must be running:
    uvicorn artha.app:app --port 8000

    # Then in another terminal:
    .venv/bin/python dev/seed_investors.py

If --reset is passed, delete artha.db before seeding (clean demo state).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://localhost:8000"

# Recommended test population per Cluster 1 Demo-Stage Addendum §3.1:
# - 3-5 investors per advisor; mix of life stages; plausible Indian names;
#   PAN values that match the format but are obviously test (DEMO12345A-style).
SEED_INVESTORS: list[tuple[str, dict]] = [
    # advisor1 (Anjali Mehta) — mix of life stages.
    # Emails use @example.com (RFC 2606 reserved-for-examples; passes
    # email-validator's strict mode). PANs use ZZZZX1234X shape — five
    # letters + four digits + one letter as PAN format requires, all
    # visually-identifiable as test data per addendum §3.1.
    ("advisor1", {
        "name": "Arjun Reddy", "email": "arjun.reddy@example.com",
        "phone": "9811111111", "pan": "TESTA1234A", "age": 32,
        "household_name": "Reddy Household",
        "risk_appetite": "aggressive", "time_horizon": "over_5_years",
    }),
    ("advisor1", {
        "name": "Priya Singh", "email": "priya.singh@example.com",
        "phone": "9811111112", "pan": "TESTB1234B", "age": 38,
        "household_name": "Singh Household",
        "risk_appetite": "moderate", "time_horizon": "over_5_years",
    }),
    ("advisor1", {
        "name": "Vikram Joshi", "email": "vikram.joshi@example.com",
        "phone": "9811111113", "pan": "TESTC1234C", "age": 51,
        "household_name": "Joshi Household",
        "risk_appetite": "moderate", "time_horizon": "3_to_5_years",
    }),
    ("advisor1", {
        "name": "Meera Iyer", "email": "meera.iyer@example.com",
        "phone": "9811111114", "pan": "TESTD1234D", "age": 64,
        "household_name": "Iyer Household",
        "risk_appetite": "conservative", "time_horizon": "under_3_years",
    }),
    # CIO/compliance/audit have firm_scope read in cluster 1 — they see
    # advisor1's book without needing their own seeded investors.
]


def _http_post(path: str, *, body: dict, token: str | None = None) -> tuple[int, dict | str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body_text)
        except json.JSONDecodeError:
            return exc.code, body_text


def _login(user_id: str) -> str:
    status, body = _http_post("/api/v2/auth/dev-login", body={"user_id": user_id})
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"login failed for {user_id}: {status} {body}")
    return body["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Delete artha.db first")
    args = parser.parse_args()

    if args.reset:
        db = Path("artha.db")
        if db.exists():
            print(f"Deleting {db.resolve()}")
            db.unlink()
        print("NOTE: backend must be restarted (or run alembic upgrade head) for the empty DB to take effect.")
        sys.exit(0)

    print("Seeding test investors via /api/v2/investors ...")
    print()

    tokens: dict[str, str] = {}
    created = 0
    skipped = 0

    for user_id, payload in SEED_INVESTORS:
        if user_id not in tokens:
            tokens[user_id] = _login(user_id)
        token = tokens[user_id]
        status, body = _http_post("/api/v2/investors", body=payload, token=token)
        if status == 201 and isinstance(body, dict):
            print(
                f"  ✓ created {body['name']:<20} pan={body['pan']} "
                f"life_stage={body['life_stage']:<13} liquidity={body['liquidity_tier']}"
            )
            created += 1
        elif status == 409:
            print(f"  · skipped {payload['name']} (PAN {payload['pan']} already exists)")
            skipped += 1
        else:
            print(f"  ✗ FAILED {payload['name']}: HTTP {status} {body}")

    print()
    print(f"Done. Created {created}, skipped {skipped} (already existed).")


if __name__ == "__main__":
    main()
