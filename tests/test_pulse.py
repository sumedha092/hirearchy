"""Pulse end-to-end test against a real local Postgres loaded with supabase/schema.sql.
Each simulated student has their own data dir (like separate Cubbie sandboxes).
Run: python3 tests/test_pulse.py   (needs PG at /tmp/pg:5433 with the schema loaded)
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

import shutil

# This test needs a developer's local Postgres (socket /tmp/pg, port 5433) with
# supabase/schema.sql loaded. Anywhere else (e.g. a Cubbie sandbox) it skips.
if not shutil.which("psql") or not os.path.exists("/tmp/pg/.s.PGSQL.5433"):
    print("SKIPPED: test_pulse.py needs a local Postgres with supabase/schema.sql "
          "(developer-only). Use tests/test_offline.py instead.")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import pulse  # noqa

TYPES = {"p_since": "timestamptz", "p_intro": "uuid", "p_paused": "boolean"}


def sql_lit(k, v):
    if v is None:
        return f"null::{TYPES.get(k, 'text')}"
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'::" + TYPES.get(k, "text")


def fake_rpc(fn, **params):
    args = ", ".join(f"{k} => {sql_lit(k, v)}" for k, v in params.items())
    q = f"set role anon; select {fn}({args})::text;"
    r = subprocess.run(["psql", "-h", "/tmp/pg", "-p", "5433", "-U", "postgres", "-d", "postgres",
                        "-tA", "-v", "ON_ERROR_STOP=1", "-c", q], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip().splitlines()[-1])
    text = "\n".join(l for l in r.stdout.splitlines() if l.strip() != "SET").strip()
    try:
        return json.loads(text)
    except ValueError:
        return text               # e.g. a uuid (PostgREST returns it as a JSON string)


pulse.rpc = fake_rpc
DIRS = {name: tempfile.mkdtemp() for name in ["priya", "alex", "sam", "jo"]}


def run(who, *argv):
    pulse.DATA_DIR = DIRS[who]
    sys.argv = ["pulse.py", *argv]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pulse.main()
    return json.loads(buf.getvalue())


failed = 0


def check(cond, msg):
    global failed
    print(("PASS " if cond else "FAIL ") + msg)
    failed += not cond


subprocess.run(["psql", "-h", "/tmp/pg", "-p", "5433", "-U", "postgres", "-d", "postgres", "-q", "-c",
                "truncate intros, reports, applications, students cascade"], check=True)

r = run("priya", "join", "--grad", "May 2027", "--major", "CS", "--contact", "priya@asu.edu")
check(r["ok"], "priya joins with contact")
run("alex", "join", "--grad", "May 2026", "--major", "CS", "--contact", "linkedin.com/in/alex")
run("sam", "join", "--grad", "May 2027", "--major", "Data Science")

r = run("priya", "apply", "--company", "Stripe", "--role", "SWE Intern")
check(r["ok"] and r["pulse"]["note"].startswith("not enough"), "stats hidden with <3 others")
run("alex", "apply", "--company", "stripe", "--role", "swe intern", "--status", "offer")
run("sam", "apply", "--company", "Stripe", "--role", "SWE Intern", "--status", "oa")
run("jo", "apply", "--company", "Stripe", "--role", "SWE Intern", "--status", "rejected")  # auto-joins

r = run("alex", "report", "--company", "Stripe", "--role", "SWE Intern", "--stage", "interview",
        "--body", "Design a rate limiter, then BFS on a grid. Friendly interviewers.")
check(r["students_waiting_on_this_company"] == 2, "report reaches 2 waiting students (priya, sam)")

s = run("priya", "status", "--company", "Stripe")
check(s["others_applied"] == 3 and "others_status_counts" in s, "stats shown once 3 others applied")
check(s["locked_reports"] == 1 and "reports" not in s, "reports locked before contributing (give-to-get)")

c = run("priya", "check")
check(c["status"] == "UPDATES" and c["new_reports"][0]["body"] is None, "feed shows new report, body locked")
check(run("priya", "check")["status"] == "NOTHING_NEW", "second check: nothing new (no spam)")

run("priya", "report", "--company", "Stripe", "--stage", "tip", "--body", "Auto-reply came 2 days after applying.")
s = run("priya", "status", "--company", "Stripe")
check(len(s["reports"]) == 1 and "rate limiter" in s["reports"][0]["body"], "contributing unlocks reports")

r = run("priya", "ask", "--company", "Stripe", "--question", "How did you prep for system design?")
check(r["ok"], "intro request created")
c = run("alex", "check")
req = c["intro_requests_to_answer"]
check(len(req) == 1 and req[0]["from_major"] == "CS" and "priya" not in json.dumps(req), "alex sees request, no identity")
r = run("alex", "respond", "--id", req[0]["id"], "--action", "accept")
check(r["requester_contact"] == "priya@asu.edu", "on accept, alex gets priya's contact")
c = run("priya", "check")
check(c["my_request_updates"][0]["contact"] == "linkedin.com/in/alex", "priya gets alex's contact")
check(run("priya", "check")["my_request_updates"] == [], "update not repeated")

r = run("priya", "ask", "--company", "Stripe", "--question", "Anything else?")
check(r["ok"], "second request goes to next person (sam, OA)")
req = run("sam", "check")["intro_requests_to_answer"]
run("sam", "respond", "--id", req[0]["id"], "--action", "answer", "--answer", "Do LeetCode mediums on graphs.")
u = run("priya", "check")["my_request_updates"][0]
check(u["status"] == "answered" and u["contact"] is None and "graphs" in u["answer"], "anonymous answer, no contact shared")

run("priya", "ask", "--company", "Stripe")
r = run("priya", "ask", "--company", "Stripe")
check(r["ok"] is False, "no one left / limits respected")

run("alex", "pause")
check(run("jo", "ask", "--company", "Stripe")["ok"] in (True, False), "pause runs")

print("\nALL PASSED" if not failed else f"\n{failed} FAILED")
sys.exit(1 if failed else 0)
