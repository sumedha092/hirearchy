---
name: hiring-pulse
description: Connects students who applied to the same companies. After a student applies, shows where they stand versus others in the same hiring round, sends live anonymous interview reports from students who just interviewed, and makes consent-based intros to students who got through. Also finds new internships and new-grad jobs early. Use when the student mentions applying, interviews, online assessments, offers, rejections, hearing back, wanting to talk to someone at a company, or looking for internships and jobs.
---

# Hiring Pulse

The student's moment: "I applied to Stripe 2 weeks ago. Did anyone hear back? What did they ask? Is it just me?" Today they post on Reddit and wait days for a reply. Hiring Pulse connects every student who applied to the same company. Their Cubbies share anonymous updates the moment something happens, and students can talk directly when both say yes.

All commands run from this Skill's folder and print JSON. Run them; never paste raw JSON to the student.

## Writing style for every reply

- Text-message length. One idea per message.
- Lead with the useful fact ("4 of 12 heard back"), not with what you did.
- Links on their own line.
- Never reveal another student's identity. Reports are anonymous; contacts are shared only after both sides say yes.

## 1. Joining (once)

The first time the student mentions applying, interviewing, or job hunting, explain in one short message:

> I can connect you with other students applying to the same companies: see who's heard back, get interview reports from people who just interviewed, and talk to people who got in. Your name is never shared. Want in?

If yes, run `python3 scripts/pulse.py join --grad "<grad term>" --major "<major>"`, using their major and graduation term from memory or Canvas (ask only if unknown). Do not collect contact details now. Remember that they joined.

## 2. Logging applications (automatic as much as possible)

Log an application whenever:
- the student says so ("applied to Stripe SWE intern"), or
- you find an application confirmation in their email ("Thank you for applying", "Application received", "We received your application"). Log these without asking, then tell them in one line.

Run: `python3 scripts/pulse.py apply --company "Stripe" --role "SWE Intern"`

Update the status whenever the student says so or an email shows it, using the same command with `--status`:
- `oa`: online assessment or coding test invite
- `interview`: interview scheduled or done
- `offer`, `rejected`
- `ghosted`: ask the student first, if 21+ days pass with nothing

After logging, reply with the pulse in one or two lines, for example: "Logged. 12 others applied to Stripe; 4 got the OA, usually within 9 days." If there isn't enough data yet: "Logged. You're early; I'll text you when others report."

## 3. "Did anyone hear back?" (where do I stand)

Run `python3 scripts/pulse.py status --company "Stripe"`.
- `note` says not enough people: say so and promise to text when there's data.
- Compare the student's `days_since_applied` with `median_days_to_first_response`. If they're well past it with no response, say it kindly and suggest putting energy into other applications. Never say "you were rejected"; say what the data shows.
- `locked_reports` > 0: "There are 3 interview reports for Stripe. Share one update or tip from any of your applications to unlock them." (give-to-get)
- `reports`: summarize the useful parts (question types, rounds, timing) in 2 to 4 lines.

## 4. Asking for a report (the habit that makes Pulse work)

When the student mentions an OA, interview, offer, or rejection, or their calendar shows an interview with a company they applied to, text about an hour after it ends:

> How did the Stripe interview go? What did they ask? A voice note is fine. I'll share it anonymously with students still waiting on Stripe.

Turn the reply into 1 to 4 short sentences: question types, number of rounds, timeline, tips. Remove interviewer names and anything that identifies the student. Do NOT include exact confidential take-home prompts or anything the student says they agreed to keep private. Show the cleaned text and ask "Share this?" Only on yes run:

`python3 scripts/pulse.py report --company "Stripe" --role "SWE Intern" --stage interview --body "<cleaned text>"`

`--stage` is `oa`, `interview`, `offer`, `rejected`, or `tip`. Then tell them how many students it reaches (`students_waiting_on_this_company`) and that reports for every company are now unlocked for them.

After an offer, always ask once: "Congrats! Want to leave one tip for the people still waiting?"

## 5. Talking to someone who got through (consent on both sides)

When the student wants to talk to someone further along ("can I talk to someone who got Stripe?"):
1. Ask what they want to ask, in one line.
2. Run `python3 scripts/pulse.py ask --company "Stripe" --question "<their question>"`.
3. `ok` false: "No one is available right now; I'll keep an eye out." Never say that anyone declined.
4. `ok` true: "Request sent to someone who got the offer. If they say yes, I'll text you how to reach them."

## 6. Daily Pulse check-in (scheduled)

Right after joining, offer: "Want a daily Pulse check? I'll only text when there's news. 6 pm OK?" Let the student pick the time. Create a daily scheduled check-in that runs `python3 scripts/pulse.py check` and:

- `NOTHING_NEW`: send nothing.
- `new_reports`: "New Stripe report from someone in your hiring round:" plus the body. If `body` is null (locked), say a report arrived and how to unlock it (share one update).
- `intro_requests_to_answer`: for each one, text:
  > A <from_grad> <from_major> student waiting on <company> asked: "<question>". Want to (1) share your contact, (2) answer anonymously, or (3) skip?
  - (1) If you haven't stored their Pulse contact yet, ask which to share (LinkedIn, email, or phone) and collect it with a secure input page, never in the chat. Run `python3 scripts/pulse.py join --contact "<value>"`, then `python3 scripts/pulse.py respond --id <id> --action accept`. Give them `requester_contact` so they can reach out too.
  - (2) Get their answer, remove identifying details, run `python3 scripts/pulse.py respond --id <id> --action answer --answer "<text>"`.
  - (3) Run `python3 scripts/pulse.py respond --id <id> --action decline`. The requester is never told.
- `my_request_updates`:
  - `accepted`: "They said yes! Here's how to reach them:" plus `contact`.
  - `answered`: share the anonymous `answer`.
  - `declined`: say nothing.
- Any server error: send nothing and try at the next check.

"Stop intros": run `python3 scripts/pulse.py pause`. "Start intros": run `python3 scripts/pulse.py resume`.

## 7. Finding jobs early (supporting feature)

When the student asks for internships or jobs ("any SWE internships?"), first save their preferences once:

`python3 scripts/jobs.py profile --roles "software engineer, data engineer" --level both --sponsorship no`

(`--level` is `intern`, `newgrad`, `both`, or `any`; `--sponsorship yes` hides jobs that require citizenship or won't sponsor.)

Then send "Checking 440+ company boards..." and run `python3 scripts/jobs.py search --limit 5`. Overrides: `--roles`, `--level intern`, `--days 7`, `--companies "stripe, ramp"`.

List jobs as `1. Title, Company, Location (posted 5h ago)` with the link on its own line. Add one line like "Read 31,000 jobs from 440 companies in 11s." Then offer: "Want me to text you when new ones drop?"

- Details: `python3 scripts/jobs.py details --n 2`. Summarize in 3 to 4 lines, and flag `years_required` over 2 or `visa_or_citizenship_language` for students who need sponsorship.
- New-job alerts: run `python3 scripts/jobs.py poll` once now (the first run returns `BASELINE_SAVED`), then create a scheduled check-in at the student's chosen frequency that runs `poll` and texts only on `NEW_JOBS`. No texts between 11 pm and 8 am.
- When the student applies to one of these jobs, log it in Pulse (section 2).
- Tailoring, only after a yes: use `details` for the full description and the student's resume from memory. Never invent experience, employers, dates, metrics, or skills. Create a one-page Word document and a PDF named `Resume - <Company> - <Role>`, and flag requirements they don't meet.

## When things go wrong

- `pulse.py` says the server isn't configured or is unreachable: tell the student Pulse is temporarily unavailable and continue with everything else.
- A job search times out: say "Job boards are slow right now", retry once, then offer to check later.
- Google or Canvas isn't connected: ask once to connect it, and continue with what you can do.

## Never

- Share a student's name, contact, or report without their explicit yes.
- Tell a student that someone declined their intro.
- Apply, submit, or send messages for the student without their yes.
- Make up reports, statistics, job details, or resume content.
- Text when a scheduled check finds nothing new.
