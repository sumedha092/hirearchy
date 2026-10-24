# job-sniper: a Cubbie Skill

Text Cubbie "any SWE internships?" and get the best matches from **443 company career boards** (Greenhouse, Lever, Ashby, SmartRecruiters) in seconds. Then turn on alerts and Cubbie texts you **only when a new matching job goes live**, and tailors your resume when you say yes.

## Install in Cubbie

Text Cubbie the link to this folder:

```
https://github.com/<you>/<repo>/tree/main/job-sniper
```

Reply **yes** to the install summary. There are no keys and no logins.

## Try it

- "Find me software engineering internships"
- "Any data engineering new grad jobs posted this week?"
- "Text me when new ones drop, every 6 hours"
- "Tell me about #2" / "Tailor my resume for #2"
- "I applied to #1" / "Show my applications"

## How it works

| File | What it does |
|---|---|
| `SKILL.md` | Tells Cubbie when to use the Skill and each flow: setup, search, alerts, details, tailoring, tracker |
| `scripts/jobs.py` | Command line: `profile`, `search`, `details`, `poll`, `track`, `tracker`, `add-board` |
| `scripts/jobs_core.py` | Parallel board fetching (48 threads, 8 s timeout per board, 80 s overall cap), US-location, seniority and visa filters, ranking |
| `scripts/boards.json` | 443 company boards |
| `cubbie.yaml` | The 4 API hosts the scripts call |

- **Speed:** All boards are fetched in parallel. Greenhouse lists are fetched without descriptions; descriptions are pulled only for the jobs about to be shown. Results are cached for 20 minutes, so follow-up searches return instantly.
- **Alerts:** `poll` compares each board against the job IDs it saw last time, stored in `$SKILL_DATA_DIR`. A board that returned 0 jobs on its first successful fetch still counts as baselined, so its first real posting is alerted. Postings older than 30 days that show up under a new ID count as reposts and are not alerted.
- **Safety:** Cubbie never applies or sends anything without the student's yes. Resumes are tailored only from facts already in the student's resume.

Standard library only (Python 3.12). No packages.

## Test locally

```
python3 tests/test_offline.py                         # 22 offline checks, fake data
python3 scripts/jobs.py profile --roles "software engineer" --level both
python3 scripts/jobs.py search --fresh                # live; check "seconds" < 90
python3 scripts/jobs.py poll                          # first run: BASELINE_SAVED
python3 scripts/jobs.py poll                          # later runs: NEW_JOBS or NOTHING_NEW
```

When run outside Cubbie, state goes to `~/.job-sniper/`.
