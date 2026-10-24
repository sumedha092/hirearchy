# Hirearchy: a Cubbie Skill

*Climb the hiring ladder. Learn from students one step ahead, help the ones behind.*

**You applied to Stripe two weeks ago. Did anyone hear back? What did they ask?**

Today students post "anyone heard back from X?" on Reddit and wait days. Hirearchy connects every student who applied to the same company, through their own Cubbie:

- **Where you stand:** "12 others applied. 4 got the OA, usually within 9 days. You're on day 14."
- **Live interview reports:** right after someone interviews, Cubbie asks them how it went and sends an anonymous report to everyone still waiting on that company.
- **Give-to-get:** share one update to unlock everyone's reports.
- **Talk to someone who got in:** an intro happens only when both students say yes. They can share a contact, answer anonymously, or skip. Nobody is told who declined.
- **Find jobs early, too:** searches 440+ company career boards and texts you when new internships and new-grad roles go live.

## Install

Text Cubbie the link to this repo and reply **yes**. There are no keys or logins.

Try: "I applied to Stripe SWE intern" · "Did anyone hear back from Stripe?" · "Can I talk to someone who got the offer?" · "Find me SWE internships"

## How it works

| File | What it does |
|---|---|
| `SKILL.md` | When Cubbie uses the Skill and every flow: joining, logging applications, status, reports, intros, daily check, job search |
| `scripts/pulse.py` | Pulse client: `join`, `apply`, `status`, `report`, `ask`, `respond`, `check`, `pause` |
| `supabase/schema.sql` | Shared backend. Tables are locked; only these functions are exposed. Enforces anonymity, the 3+ reporter minimum for stats, give-to-get, intro consent, and rate limits |
| `scripts/jobs.py`, `jobs_core.py`, `boards.csv` | Job search across 443 boards (Greenhouse, Lever, Ashby, SmartRecruiters): parallel fetch, entry-level/US/visa filters, new-job alerts |
| `cubbie.yaml` | Allowed hosts: the job board APIs and `*.supabase.co` |

**Privacy:** no names are stored. Each student is a random token kept in their own Cubbie sandbox. Contact details are stored only if the student chooses to share them, and are revealed only after both sides accept.

## Run your own backend

1. Create a Supabase project, open SQL Editor, paste `supabase/schema.sql`, and run it.
2. Put the Project URL and **anon public** key in `scripts/pulse_config.json`. The anon key is safe to publish, because it can only call the Pulse functions.

## Tests

```
python3 tests/test_offline.py   # job search, filters, alerts (fake boards)
python3 tests/test_pulse.py     # Pulse flows against a real local Postgres
```
