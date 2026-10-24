#!/usr/bin/env python3
"""Pulse: the shared, after-you-apply side of job-sniper. Prints one JSON object.

  python3 scripts/pulse.py join    --grad "May 2027" --major "CS" [--contact "linkedin.com/in/x"]
  python3 scripts/pulse.py apply   --company Stripe --role "SWE Intern" [--status applied|oa|interview|offer|rejected|ghosted]
  python3 scripts/pulse.py status  --company Stripe
  python3 scripts/pulse.py report  --company Stripe --role "SWE Intern" --stage interview --body "They asked..."
  python3 scripts/pulse.py ask     --company Stripe --question "How did you prep for system design?"
  python3 scripts/pulse.py respond --id <request id> --action accept|answer|decline [--answer "..."]
  python3 scripts/pulse.py check   # scheduled: new reports for my companies + intro requests/updates
  python3 scripts/pulse.py pause | resume

Talks only to the team's Supabase project (declared in cubbie.yaml) using a
public anon key. The database exposes functions only; tables are locked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SKILL_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".job-sniper")
os.makedirs(DATA_DIR, exist_ok=True)


def config():
    with open(os.path.join(HERE, "pulse_config.json")) as f:
        return json.load(f)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str)[:7900])


def rpc(fn, **params):
    """Call a Supabase SQL function. Replaced in tests."""
    cfg = config()
    if "YOUR-PROJECT" in cfg["url"]:
        raise RuntimeError("Pulse server not configured yet (pulse_config.json)")
    req = urllib.request.Request(
        f"{cfg['url'].rstrip('/')}/rest/v1/rpc/{fn}",
        data=json.dumps(params).encode(),
        headers={"apikey": cfg["anon_key"], "Authorization": f"Bearer {cfg['anon_key']}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        try:
            msg = json.loads(msg).get("message", msg)
        except Exception:
            pass
        raise RuntimeError(msg[:200])


def state():
    try:
        return json.load(open(os.path.join(DATA_DIR, "pulse_state.json")))
    except Exception:
        return {}


def save_state(s):
    with open(os.path.join(DATA_DIR, "pulse_state.json"), "w") as f:
        json.dump(s, f)


def token():
    s = state()
    if not s.get("token"):
        s["token"] = secrets.token_urlsafe(24)
        save_state(s)
    return s["token"]


def joined():
    return bool(state().get("joined"))


# ------------------------------------------------------------------ commands
def cmd_join(a):
    rpc("pulse_join", p_token=token(), p_grad=a.grad, p_major=a.major, p_contact=a.contact)
    s = state(); s["joined"] = True; save_state(s)
    out({"ok": True, "joined": True, "contact_saved": bool(a.contact)})


def need_join():
    if not joined():
        rpc("pulse_join", p_token=token(), p_grad=None, p_major=None, p_contact=None)
        s = state(); s["joined"] = True; save_state(s)


def cmd_apply(a):
    need_join()
    rpc("pulse_apply", p_token=token(), p_company=a.company, p_role=a.role, p_status=a.status)
    st = rpc("pulse_status", p_token=token(), p_company=a.company)
    out({"ok": True, "logged": f"{a.role} at {a.company}", "status": a.status, "pulse": summarize(st)})


def summarize(st):
    if not st:
        return None
    s = {"company": st.get("company"), "my_applications": st.get("my_applications"),
         "others_applied": st.get("others_applied")}
    if st.get("enough_data"):
        s["others_status_counts"] = st.get("status_counts")
        med = st.get("median_days_to_first_response")
        s["median_days_to_first_response"] = round(med, 1) if med is not None else None
    else:
        s["note"] = "not enough people yet to show stats (need 3+)"
    if st.get("unlocked"):
        s["reports"] = st.get("reports")
    else:
        s["locked_reports"] = st.get("locked_report_count")
        s["unlock_hint"] = "share one report or tip to unlock reports for every company"
    return s


def cmd_status(a):
    need_join()
    out(summarize(rpc("pulse_status", p_token=token(), p_company=a.company)))


def cmd_report(a):
    need_join()
    r = rpc("pulse_report", p_token=token(), p_company=a.company, p_role=a.role,
            p_stage=a.stage, p_body=a.body)
    out({"ok": True, "students_waiting_on_this_company": r.get("waiting_students")})


def cmd_ask(a):
    need_join()
    out(rpc("pulse_intro_request", p_token=token(), p_company=a.company, p_question=a.question))


def cmd_respond(a):
    out(rpc("pulse_intro_respond", p_token=token(), p_intro=a.id, p_action=a.action, p_answer=a.answer))


def cmd_check(a):
    """For the scheduled check-in. status NOTHING_NEW means: send nothing."""
    need_join()
    s = state()
    since = s.get("last_check") or (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
    feed = rpc("pulse_feed", p_token=token(), p_since=since)
    inbox = rpc("pulse_inbox", p_token=token())
    seen = set(s.get("seen_updates", []))
    updates = []
    for r in inbox.get("my_requests", []):
        key = f"{r['id']}:{r['status']}"
        if r["status"] in ("accepted", "answered", "declined") and key not in seen:
            updates.append(r)
            seen.add(key)
    s["seen_updates"] = sorted(seen)[-200:]
    s["last_check"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_state(s)
    items, to_answer = feed.get("items", []), inbox.get("to_answer", [])
    out({"status": "UPDATES" if (items or to_answer or updates) else "NOTHING_NEW",
         "new_reports": items, "reports_unlocked": feed.get("unlocked"),
         "intro_requests_to_answer": to_answer, "my_request_updates": updates})


def cmd_pause(a):
    out(rpc("pulse_pause", p_token=token(), p_paused=True))


def cmd_resume(a):
    out(rpc("pulse_pause", p_token=token(), p_paused=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("join"); s.add_argument("--grad"); s.add_argument("--major"); s.add_argument("--contact")
    s.set_defaults(f=cmd_join)
    s = sub.add_parser("apply"); s.add_argument("--company", required=True); s.add_argument("--role", required=True)
    s.add_argument("--status", default="applied",
                   choices=["applied", "oa", "interview", "offer", "rejected", "ghosted"]); s.set_defaults(f=cmd_apply)
    s = sub.add_parser("status"); s.add_argument("--company", required=True); s.set_defaults(f=cmd_status)
    s = sub.add_parser("report"); s.add_argument("--company", required=True); s.add_argument("--role", default="")
    s.add_argument("--stage", default="tip", choices=["oa", "interview", "offer", "rejected", "tip"])
    s.add_argument("--body", required=True); s.set_defaults(f=cmd_report)
    s = sub.add_parser("ask"); s.add_argument("--company", required=True); s.add_argument("--question", default="")
    s.set_defaults(f=cmd_ask)
    s = sub.add_parser("respond"); s.add_argument("--id", required=True)
    s.add_argument("--action", required=True, choices=["accept", "answer", "decline"]); s.add_argument("--answer")
    s.set_defaults(f=cmd_respond)
    s = sub.add_parser("check"); s.set_defaults(f=cmd_check)
    s = sub.add_parser("pause"); s.set_defaults(f=cmd_pause)
    s = sub.add_parser("resume"); s.set_defaults(f=cmd_resume)
    a = ap.parse_args()
    try:
        a.f(a)
    except Exception as e:
        out({"ok": False, "error": str(e)[:300]})


if __name__ == "__main__":
    main()
