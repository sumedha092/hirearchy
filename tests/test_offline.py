"""Offline tests: fake the four job board APIs and run every command.
Run:  python3 tests/test_offline.py
"""
import io
import json
import os
import sys
import tempfile
import contextlib
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["SKILL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import jobs_core as jc  # noqa
import jobs  # noqa

now = dt.datetime.now(dt.timezone.utc)
ago = lambda h: (now - dt.timedelta(hours=h)).isoformat()

BOARDS = [
    {"provider": "greenhouse", "name": "stripe", "board": "stripe"},
    {"provider": "ashby", "name": "ramp", "board": "ramp"},
    {"provider": "lever", "name": "palantir", "board": "palantir"},
    {"provider": "ashby", "name": "quietco", "board": "quietco"},      # empty at first
]
STATE = {"quiet_jobs": [], "ramp_extra": []}


def fake_get_json(url, params=None, **kw):
    if "greenhouse" in url and url.rstrip("/").endswith("/jobs"):
        return {"jobs": [
            {"id": 1, "title": "Software Engineer Intern, Summer 2027", "location": {"name": "San Francisco, CA"},
             "absolute_url": "https://stripe.com/jobs/1", "first_published": ago(5)},
            {"id": 2, "title": "Senior Software Engineer", "location": {"name": "Seattle, WA"},
             "absolute_url": "https://stripe.com/jobs/2", "first_published": ago(5)},
            {"id": 3, "title": "Software Engineer, New Grad", "location": {"name": "Dublin, Ireland"},
             "absolute_url": "https://stripe.com/jobs/3", "first_published": ago(5)},
        ]}
    if "greenhouse" in url:
        return {"content": "&lt;p&gt;Build payments APIs in Python and Go.&lt;/p&gt;"}
    if "ashbyhq" in url and url.endswith("/ramp"):
        return {"jobs": [
            {"id": "r1", "title": "Software Engineer - New Grad", "location": "New York, NY",
             "jobUrl": "https://jobs.ashbyhq.com/ramp/r1", "publishedAt": ago(30),
             "descriptionPlain": "React, TypeScript, Python. 0-2 years of experience."},
            {"id": "r2", "title": "Software Engineer Intern", "location": "New York, NY",
             "jobUrl": "https://jobs.ashbyhq.com/ramp/r2", "publishedAt": ago(2),
             "descriptionPlain": "Must be a U.S. citizen due to export control."},
        ] + STATE["ramp_extra"]}
    if "ashbyhq" in url and url.endswith("/quietco"):
        return {"jobs": STATE["quiet_jobs"]}
    if "lever" in url:
        return [{"id": "p1", "text": "Data Engineer Intern", "categories": {"location": "Denver, CO"},
                 "country": "US", "hostedUrl": "https://jobs.lever.co/palantir/p1",
                 "createdAt": int((now - dt.timedelta(days=3)).timestamp() * 1000),
                 "descriptionPlain": "Spark and SQL pipelines."}]
    raise RuntimeError("unexpected url " + url)


jc.get_json = fake_get_json
jc.load_boards = lambda companies=None: [b for b in BOARDS if not companies or
                                         any(c.lower() in b["name"] for c in companies)]


def run(argv):
    sys.argv = ["jobs.py"] + argv
    buf = io.StringIO()
    exits = []
    real_exit = os._exit
    os._exit = lambda code: exits.append(code)
    try:
        with contextlib.redirect_stdout(buf):
            jobs.main()
    finally:
        os._exit = real_exit
    return json.loads(buf.getvalue())


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        global failed
        failed += 1


failed = 0

# profile
r = run(["profile", "--roles", "software engineer, data engineer", "--level", "both", "--sponsorship", "yes"])
check(r["saved"] and r["profile"]["sponsorship"] is True, "profile saves")

# search
r = run(["search", "--limit", "5"])
titles = [x["title"] for x in r["results"]]
check("Senior Software Engineer" not in titles, "senior roles filtered")
check("Software Engineer, New Grad" not in titles, "Dublin-only job filtered as outside US")
check("Software Engineer Intern" not in titles, "citizenship-required job hidden for sponsorship students")
check("Software Engineer Intern, Summer 2027" in titles, "Stripe intern found")
check("Data Engineer Intern" in titles, "Lever data intern found")
check(r["filtered_out"].get("no sponsorship / citizenship required") == 1, "visa filter counted")
check(not r["searched"]["from_cache"], "first search hits network")
r2 = run(["search", "--limit", "5"])
check(r2["searched"]["from_cache"], "second search uses cache")
r3 = run(["search", "--companies", "palantir"])
check([x["company"] for x in r3["results"]] == ["Palantir"], "company filter works")

# details (greenhouse job needs detail fetch)
r = run(["search", "--limit", "5"])
n = titles.index("Software Engineer Intern, Summer 2027") + 1
d = run(["details", "--n", str(n)])
check("payments APIs" in d.get("description", ""), "details fetches full Greenhouse description")
check("error" in run(["details", "--n", "99"]), "details out of range -> error")

# poll: first run baselines, nothing alerted
p1 = run(["poll"])
check(p1["status"] == "BASELINE_SAVED" and not p1["new_matches"], "first poll only baselines")
p2 = run(["poll"])
check(p2["status"] == "NOTHING_NEW", "second poll with no changes -> NOTHING_NEW")

# new jobs: one at an EMPTY board (the bug), one at ramp, one old repost, one senior
STATE["quiet_jobs"] = [{"id": "q1", "title": "Software Engineer Intern", "location": "Remote (US)",
                        "jobUrl": "https://jobs.ashbyhq.com/quietco/q1", "publishedAt": ago(1),
                        "descriptionPlain": "Python."}]
STATE["ramp_extra"] = [
    {"id": "r3", "title": "Data Engineer, New Grad", "location": "New York, NY",
     "jobUrl": "https://jobs.ashbyhq.com/ramp/r3", "publishedAt": ago(1), "descriptionPlain": "SQL."},
    {"id": "r4", "title": "Software Engineer Intern", "location": "New York, NY",
     "jobUrl": "https://jobs.ashbyhq.com/ramp/r4", "publishedAt": ago(24 * 200), "descriptionPlain": "x"},
    {"id": "r5", "title": "Staff Data Engineer", "location": "New York, NY",
     "jobUrl": "https://jobs.ashbyhq.com/ramp/r5", "publishedAt": ago(1), "descriptionPlain": "x"},
]
p3 = run(["poll"])
new_titles = {(x["company"], x["title"]) for x in p3["new_matches"]}
check(p3["status"] == "NEW_JOBS", "poll reports NEW_JOBS")
check(("Quietco", "Software Engineer Intern") in new_titles, "first job at a previously EMPTY board is NEW")
check(("Ramp", "Data Engineer, New Grad") in new_titles, "new ramp job alerted")
check(p3["skipped_old_reposts"] == 1, "200-day-old 'new' id treated as repost")
check(len(new_titles) == 2, "senior new job not alerted")
p4 = run(["poll"])
check(p4["status"] == "NOTHING_NEW", "same jobs not alerted twice")

# tracker
t = run(["track", "--n", "1", "--status", "applied"])
check(t["saved"], "track saves")
tr = run(["tracker"])
check(tr["count"] == 1 and tr["rows"][0]["status"] == "applied", "tracker shows row")

print("\nALL PASSED" if not failed else f"\n{failed} FAILED")
sys.exit(1 if failed else 0)
