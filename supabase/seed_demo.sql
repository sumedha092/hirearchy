-- DEMO DATA for Hiring Pulse. Clearly fake: every seeded student's token starts with 'seed-'.
-- Paste into Supabase > SQL Editor > Run. Safe to run more than once.
-- Remove it all later with supabase/clear_demo.sql.

delete from students where token like 'seed-%';

insert into students (token, grad, major, contact) values
 ('seed-01','May 2027','CS',null), ('seed-02','May 2027','CS',null), ('seed-03','Dec 2026','CS',null),
 ('seed-04','May 2027','Data Science',null), ('seed-05','May 2026','CS',null), ('seed-06','May 2027','CSE',null),
 ('seed-07','May 2027','CS',null), ('seed-08','May 2028','CS',null), ('seed-09','May 2027','Software Eng',null),
 ('seed-10','May 2026','CS',null), ('seed-11','May 2027','CS',null), ('seed-12','Dec 2026','Data Science',null);

-- applications: (token, company, role, status, days since applied, days until status changed)
insert into applications (student_id, company, role, status, applied_at, updated_at)
select s.id, v.company, v.role, v.status,
       now() - (v.applied_days || ' days')::interval,
       now() - ((v.applied_days - v.response_days) || ' days')::interval
from (values
 ('seed-01','stripe','swe intern','oa',          16, 7),
 ('seed-02','stripe','swe intern','oa',          15, 8),
 ('seed-03','stripe','swe intern','interview',   18, 6),
 ('seed-04','stripe','swe intern','rejected',    14, 10),
 ('seed-05','stripe','swe intern','offer',       25, 9),
 ('seed-06','stripe','swe intern','applied',     12, 0),
 ('seed-07','stripe','swe intern','applied',     11, 0),
 ('seed-08','stripe','swe intern','applied',      9, 0),
 ('seed-09','stripe','swe intern','applied',      6, 0),
 ('seed-10','stripe','swe intern','oa',          13, 9),
 ('seed-11','stripe','swe intern','applied',      4, 0),
 ('seed-12','stripe','swe intern','rejected',    20, 12),
 ('seed-01','ramp','software engineer intern','interview', 10, 4),
 ('seed-03','ramp','software engineer intern','oa',        9, 5),
 ('seed-07','ramp','software engineer intern','applied',   8, 0),
 ('seed-11','ramp','software engineer intern','rejected',  12, 6),
 ('seed-02','mongodb','software engineering intern','applied', 3, 0),
 ('seed-06','mongodb','software engineering intern','oa',      7, 3),
 ('seed-08','mongodb','software engineering intern','applied', 2, 0),
 ('seed-09','mongodb','software engineering intern','applied', 5, 0)
) as v(token, company, role, status, applied_days, response_days)
join students s on s.token = v.token;

-- Sample reports (written as generic examples, not real company questions).
insert into reports (student_id, company, role, stage, body, created_at)
select s.id, v.company, v.role, v.stage, v.body, now() - (v.hours || ' hours')::interval
from (values
 ('seed-01','stripe','swe intern','oa','[sample] OA was 2 problems in 70 minutes: one string parsing task and one graph traversal. Partial credit seemed to count.', 30),
 ('seed-03','stripe','swe intern','interview','[sample] Two 45-minute rounds. First was a practical coding task building a small API helper, second was debugging an existing codebase. Talk through your thinking out loud.', 10),
 ('seed-05','stripe','swe intern','offer','[sample] Offer came about 9 days after the final round. Recruiter said clear communication mattered as much as speed.', 50),
 ('seed-10','stripe','swe intern','oa','[sample] Got the OA link 9 days after applying. Practice reading longer problem statements carefully.', 4),
 ('seed-01','ramp','software engineer intern','interview','[sample] Recruiter screen then one technical round focused on a product-style coding question.', 20)
) as v(token, company, role, stage, body, hours)
join students s on s.token = v.token;
