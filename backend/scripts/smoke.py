"""Smoke test a running deployment through its public origin (nginx → API → worker).

    uv run python scripts/smoke.py http://localhost:8080   # password in VERITA_DEMO_PASSWORD

Walks the demo path over HTTP: health, landing headline, sign-in, queue, evidence subgraph,
capacity plan, case creation, a narrative drafted by the worker, maker-checker approval and
server-side signature verification. Exits non-zero on the first failure.
"""

from __future__ import annotations

import os
import sys
import time

import httpx


def main(base: str) -> int:
    password = os.environ["VERITA_DEMO_PASSWORD"]
    api = f"{base}/api/v1"

    def session(user: str) -> tuple[httpx.Client, dict[str, str]]:
        c = httpx.Client(timeout=30)
        r = c.post(f"{api}/auth/login", json={"username": user, "password": password})
        r.raise_for_status()
        # Production cookies are Secure; browsers still send them to http://localhost, httpx does
        # not, so forward them explicitly when smoke-testing a local stack over plain HTTP.
        c.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in r.cookies.items())
        return c, {"X-CSRF-Token": r.json()["csrf_token"]}

    def check(label: str, ok: bool, detail: object = "") -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {label} {detail}")
        if not ok:
            raise SystemExit(1)

    started = time.perf_counter()
    check("live", httpx.get(f"{api}/health/live").status_code == 200)
    check("ready", httpx.get(f"{api}/health/ready").status_code == 200)
    headline = httpx.get(f"{api}/evidence-room/headline").json()
    check("public headline", len(headline["headline"]) > 0, f"{len(headline['headline'])} figures")
    web = httpx.get(base)
    check("SPA served", web.status_code == 200 and "<div id=\"root\"" in web.text)
    check("CSP header", "default-src 'self'" in web.headers.get("content-security-policy", ""))

    analyst, a_csrf = session("analyst")
    queue = analyst.get(f"{api}/alerts", params={"limit": 3, "status": "open"}).json()
    check("queue", queue["total"] > 0, f"{queue['total']} alerts")
    top = queue["items"][0]["id"]
    graph = analyst.get(f"{api}/alerts/{top}/subgraph")
    check("evidence subgraph (from pack)", graph.status_code == 200, f"{len(graph.json()['edges'])} edges")
    meta = analyst.get(f"{api}/capacity/meta").json()
    plan = analyst.get(f"{api}/capacity/plan", params={"date": meta["days"][0], "analysts": 6})
    check("capacity plan", plan.status_code == 200, plan.json().get("solver"))

    case = analyst.post(f"{api}/cases", json={"alert_ids": [top]}, headers=a_csrf)
    check("case created", case.status_code == 201, case.text[:120] if case.status_code != 201 else "")
    case_id = case.json()["id"]
    job = analyst.post(f"{api}/cases/{case_id}/narrative", json={"mode": "offline"}, headers=a_csrf).json()
    for _ in range(60):
        status = analyst.get(f"{api}/jobs/{job['id']}").json()
        if status["status"] in ("done", "failed"):
            break
        time.sleep(1)
    check("narrative drafted by the worker", status["status"] == "done", status.get("error") or "")
    detail = analyst.get(f"{api}/cases/{case_id}").json()
    check("verified", detail["state"] == "verified", detail["state"])
    check("submitted", analyst.post(f"{api}/cases/{case_id}/submit", headers=a_csrf).status_code == 200)

    mlro, m_csrf = session("mlro")
    signed = mlro.post(f"{api}/cases/{case_id}/approve", headers=m_csrf)
    check("signed by the MLRO", signed.status_code == 200 and signed.json()["state"] == "signed")
    verdict = mlro.get(f"{api}/cases/{case_id}/verify-signature").json()
    check("signature + ledger verify", verdict["valid"] and verdict["ledger"]["valid"])
    export = mlro.get(f"{api}/cases/{case_id}/export.json")
    check("signed export", export.status_code == 200, f"{len(export.content)} bytes")
    print(f"smoke passed in {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"))
