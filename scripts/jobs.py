#!/usr/bin/env python3
"""job-sniper command line. Every command prints one JSON object.

  python3 scripts/jobs.py profile [--roles ...] [--level ...] [--sponsorship yes|no] ...
  python3 scripts/jobs.py search  [--roles ...] [--level ...] [--days N] [--limit N] [--companies ...]
  python3 scripts/jobs.py details --n 2            # full description of result #2 from the last list
  python3 scripts/jobs.py poll    [--limit N]      # new matching jobs since the last poll
  python3 scripts/jobs.py track   --n 2 --status applied   # save to the student's tracker
  python3 scripts/jobs.py tracker                  # show the tracker
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs_core as jc  # noqa: E402

CACHE_TTL = 20 * 60          # seconds; repeat searches within 20 min are instant
DESC_CACHE_CHARS = 2500
DEFAULT_PROFILE = {"roles": ["software engineer"], "level": "both", "us_only": True,
                   "sponsorship": False, "hide_visa_risk": True, "days": 30, "max_years": 2,
                   "companies": []}


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1)[:7900])


def split_list(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def yes(s):
    return str(s).strip().lower() in ("y", "yes", "true", "1")


def get_profile(args=None):
    p = dict(DEFAULT_PROFILE)
    p.update(jc.load_json("profile.json", {}))
    if args is not None:
        if getattr(args, "roles", None):
            p["roles"] = split_list(args.roles)
        if getattr(args, "level", None):
            p["level"] = args.level
        if getattr(args, "days", None):
            p["days"] = args.days
        if getattr(args, "companies", None) is not None:
            p["companies"] = split_list(args.companies)
        if getattr(args, "sponsorship", None):
            p["sponsorship"] = yes(args.sponsorship)
        if getattr(args, "us_only", None):
            p["us_only"] = yes(args.us_only)
    return p


def resume_text():
    try:
        return open(jc.data_path("resume.txt"), encoding="utf-8", errors="ignore").read()
    except Exception:
        return ""


# ------------------------------------------------------------------ fetching with cache
def strip_for_cache(job):
    j = dict(job)
    if jc.SENIOR.search(j["title"]):
        j["description"] = ""
    else:
        j["description"] = (j.get("description") or "")[:DESC_CACHE_CHARS]
    return j


def fetch_jobs(boards, use_cache=True):
    """Returns (jobs, report, from_cache). Uses the cache when fresh and complete."""
    cache = jc.load_json("cache.json", {}) if use_cache else {}
    fresh = cache and time.time() - cache.get("ts", 0) < CACHE_TTL
    keys = {f"{b['provider']}:{b['board']}" for b in boards}
    if fresh and keys.issubset(cache.get("boards", {}).keys()):
        jobs = [j for k in keys for j in cache["boards"][k]]
        return jobs, {"ok": len(keys), "failed": 0, "timed_out": 0, "seconds": 0}, True
    by_board, report = jc.fetch_all(boards)
    for k, js in by_board.items():
        for j in js:
            j["_board"] = k
    write_cache(by_board, merge=fresh)
    jobs = [j for js in by_board.values() for j in js]
    return jobs, report, False


def write_cache(by_board, merge=False):
    cache = jc.load_json("cache.json", {}) if merge else {}
    boards = cache.get("boards", {})
    for k, js in by_board.items():
        boards[k] = [strip_for_cache(j) for j in js]
    jc.save_json("cache.json", {"ts": time.time(), "boards": boards})


def board_lookup():
    return {f"{b['provider']}:{b['board']}": b for b in jc.load_boards()}


def ensure_full_description(job):
    """Get the full description of one job (re-fetch its board if needed)."""
    if job.get("_detail"):
        job["description"] = ""
        jc.fill_descriptions([job])
        return job
    b = board_lookup().get(job.get("_board", ""))
    if b:
        try:
            for j in jc.FETCHERS[b["provider"]](b["board"], b["name"]):
                if j["id"] == job["id"]:
                    job["description"] = j["description"]
                    break
        except Exception:
            pass
    return job


def rank(jobs, p, limit, pool_factor=4):
    counts = {}
    first = []
    for j in jobs:
        why = jc.title_filter(j, p)
        if why:
            counts[why] = counts.get(why, 0) + 1
        else:
            first.append(j)
    # Freshest title matches first; only fetch descriptions for a manageable pool.
    first.sort(key=lambda j: j.get("posted") or "", reverse=True)
    pool = first[: max(limit * pool_factor, 20)]
    jc.fill_descriptions(pool)
    kept = []
    rt = resume_text()
    for j in pool:
        why, jj = jc.full_filter_and_score(j, p, rt)
        if why:
            counts[why] = counts.get(why, 0) + 1
        else:
            kept.append(jj)
    kept.sort(key=lambda j: -j["score"])
    return kept, len(first), counts


# ------------------------------------------------------------------ commands
def cmd_profile(a):
    p = get_profile()
    if a.roles:
        p["roles"] = split_list(a.roles)
    if a.level:
        p["level"] = a.level
    if a.sponsorship:
        p["sponsorship"] = yes(a.sponsorship)
    if a.us_only:
        p["us_only"] = yes(a.us_only)
    if a.days:
        p["days"] = a.days
    if a.companies is not None:
        p["companies"] = split_list(a.companies)
    if a.grad:
        p["grad"] = a.grad
    if a.resume_file:
        try:
            txt = open(a.resume_file, encoding="utf-8", errors="ignore").read()
            with open(jc.data_path("resume.txt"), "w") as f:
                f.write(txt)
            p["has_resume"] = True
        except Exception as e:
            out({"error": f"could not read resume file: {e}"})
            return
    jc.save_json("profile.json", p)
    out({"saved": True, "profile": p})


def cmd_search(a):
    p = get_profile(a)
    boards = jc.load_boards(p.get("companies"))
    if not boards:
        out({"error": "none of those companies are in the board list", "companies": p.get("companies"),
             "hint": "run without --companies, or add the company with: jobs.py add-board"})
        return
    jobs, report, cached = fetch_jobs(boards, use_cache=not a.fresh)
    kept, title_matches, counts = rank(jobs, p, a.limit)
    shown = kept[: a.limit]
    results = [jc.public(j, i + 1) for i, j in enumerate(shown)]
    jc.save_json("last_results.json", {"ts": time.time(), "jobs": kept[:50]})
    out({"searched": {"roles": p["roles"], "level": p["level"], "posted_within_days": p.get("days"),
                      "companies": len(boards), "jobs_read": len(jobs),
                      "boards_ok": report["ok"], "boards_failed": report["failed"] + report["timed_out"],
                      "seconds": report["seconds"], "from_cache": cached},
         "matches": len(kept), "results": results,
         "filtered_out": counts,
         "more_available": len(kept) > len(shown)})


def last_job(n):
    last = jc.load_json("last_results.json", {}).get("jobs", [])
    if not 1 <= n <= len(last):
        return None, len(last)
    return last[n - 1], len(last)


def cmd_details(a):
    job, total = last_job(a.n)
    if not job:
        out({"error": f"no result #{a.n}; the last list had {total} jobs. Run a search first."})
        return
    job = ensure_full_description(job)
    info = jc.public(job, a.n, desc_chars=6000)
    info["years_required"] = jc.required_years(job.get("description"))
    info["visa_or_citizenship_language"] = bool(jc.VISA_RISK.search(job.get("description") or ""))
    out(info)


def cmd_poll(a):
    """Compare current boards against what we saw last time.

    A board becomes 'baselined' after its first SUCCESSFUL fetch, even if it
    had 0 jobs, so its first real posting later is reported as NEW (fixes the
    empty-board baseline bug from the benchmark)."""
    p = get_profile()
    boards = jc.load_boards(p.get("companies"))
    state = jc.load_json("seen.json", {"boards": {}, "polls": 0})
    by_board, report = jc.fetch_all(boards)
    new_jobs, baselined_now = [], 0
    for k, js in by_board.items():
        for j in js:
            j["_board"] = k
        ids = {j["id"] for j in js}
        if k not in state["boards"]:
            state["boards"][k] = sorted(ids)
            baselined_now += 1
            continue
        seen = set(state["boards"][k])
        for j in js:
            if j["id"] not in seen:
                new_jobs.append(j)
        # Keep ids we have ever seen (bounded) so a re-listed id is not re-alerted.
        state["boards"][k] = sorted(seen | ids)[-3000:]
    state["polls"] = state.get("polls", 0) + 1
    state["last_poll"] = jc.iso(jc.NOW())
    jc.save_json("seen.json", state)
    write_cache(by_board, merge=True)

    # Only jobs that fit the student, and not old postings resurfacing.
    p_new = dict(p)
    p_new["days"] = None
    matched, reposts = [], 0
    for j in new_jobs:
        if jc.title_filter(j, p_new):
            continue
        d = jc.parse_date(j.get("posted"))
        if d and d < jc.NOW() - dt.timedelta(days=30):
            reposts += 1
            continue
        matched.append(j)
    jc.fill_descriptions(matched[:40])
    final = []
    for j in matched[:40]:
        why, jj = jc.full_filter_and_score(j, p_new, resume_text())
        if not why:
            final.append(jj)
    final.sort(key=lambda j: -j["score"])
    if final:
        prev = jc.load_json("last_results.json", {}).get("jobs", [])
        jc.save_json("last_results.json", {"ts": time.time(), "jobs": (final + prev)[:50]})
    first_run = baselined_now > 0 and state["polls"] == 1
    out({"first_run": first_run,
         "status": ("BASELINE_SAVED" if first_run else ("NEW_JOBS" if final else "NOTHING_NEW")),
         "boards_checked": report["ok"], "boards_failed": report["failed"] + report["timed_out"],
         "seconds": report["seconds"], "new_postings_any_role": len(new_jobs),
         "skipped_old_reposts": reposts,
         "new_matches": [jc.public(j, i + 1) for i, j in enumerate(final[: a.limit])],
         "more_new_matches": max(0, len(final) - a.limit)})


def cmd_track(a):
    job, total = last_job(a.n)
    if not job:
        out({"error": f"no result #{a.n} in the last list ({total} jobs)."})
        return
    tr = jc.load_json("tracker.json", [])
    row = next((r for r in tr if r["id"] == job["id"]), None)
    today = dt.date.today().isoformat()
    if row:
        row["status"], row["updated"] = a.status, today
    else:
        tr.append({"id": job["id"], "company": job["company"], "title": job["title"], "url": job["url"],
                   "status": a.status, "added": today, "updated": today, "note": a.note or ""})
    jc.save_json("tracker.json", tr)
    out({"saved": True, "tracker_size": len(tr), "job": f"{job['title']} at {job['company']}",
         "status": a.status})


def cmd_tracker(a):
    tr = jc.load_json("tracker.json", [])
    out({"count": len(tr), "rows": [{k: r[k] for k in ("company", "title", "status", "updated", "url")}
                                    for r in tr]})


def cmd_add_board(a):
    extra = jc.load_json("extra_boards.json", [])
    extra.append({"provider": a.provider, "name": a.name, "board": a.board})
    try:
        n = len(jc.FETCHERS[a.provider](a.board, a.name))
    except Exception as e:
        out({"error": f"could not read that board: {str(e)[:80]}"})
        return
    jc.save_json("extra_boards.json", extra)
    out({"added": a.name, "jobs_on_board": n})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(s):
        s.add_argument("--roles", help="comma separated, e.g. 'software engineer, data engineer'")
        s.add_argument("--level", choices=["intern", "newgrad", "both", "any"])
        s.add_argument("--days", type=int, help="posted within N days")
        s.add_argument("--companies", help="comma separated company names; empty string = all")
        s.add_argument("--sponsorship", help="yes if the student needs visa sponsorship")
        s.add_argument("--us-only", dest="us_only", help="yes/no")

    s = sub.add_parser("profile"); common(s)
    s.add_argument("--grad", help="graduation term, e.g. 'May 2027'")
    s.add_argument("--resume-file", help="path to a .txt/.md resume to use for ranking")
    s.set_defaults(f=cmd_profile)
    s = sub.add_parser("search"); common(s)
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--fresh", action="store_true", help="ignore the 20-minute cache")
    s.set_defaults(f=cmd_search)
    s = sub.add_parser("details"); s.add_argument("--n", type=int, required=True); s.set_defaults(f=cmd_details)
    s = sub.add_parser("poll"); s.add_argument("--limit", type=int, default=5); s.set_defaults(f=cmd_poll)
    s = sub.add_parser("track"); s.add_argument("--n", type=int, required=True)
    s.add_argument("--status", default="saved", choices=["saved", "applied", "interview", "offer", "rejected"])
    s.add_argument("--note"); s.set_defaults(f=cmd_track)
    s = sub.add_parser("tracker"); s.set_defaults(f=cmd_tracker)
    s = sub.add_parser("add-board")
    s.add_argument("--provider", required=True, choices=list(jc.FETCHERS))
    s.add_argument("--board", required=True); s.add_argument("--name", required=True)
    s.set_defaults(f=cmd_add_board)
    a = ap.parse_args()
    if getattr(a, "level", None) == "any":
        a.level = "any"
    a.f(a)
    sys.stdout.flush()
    os._exit(0)   # don't wait for timed-out fetch threads


if __name__ == "__main__":
    main()
