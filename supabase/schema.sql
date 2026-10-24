-- job-sniper Pulse backend. Paste into Supabase > SQL Editor > Run.
-- Clients only use the anon key and can ONLY call the functions below
-- (tables are locked by row level security, no direct reads/writes).

create extension if not exists pgcrypto;

create table if not exists students (
  id uuid primary key default gen_random_uuid(),
  token text unique not null,              -- secret per-student id kept in SKILL_DATA_DIR
  grad text, major text,
  contact text,                            -- only revealed after mutual consent
  intros_paused boolean default false,
  created_at timestamptz default now()
);

create table if not exists applications (
  id uuid primary key default gen_random_uuid(),
  student_id uuid references students(id) on delete cascade,
  company text not null, role text not null,
  status text not null default 'applied',  -- applied | oa | interview | offer | rejected | ghosted
  applied_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (student_id, company, role)
);

create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  student_id uuid references students(id) on delete cascade,
  company text not null, role text,
  stage text,                              -- oa | interview | offer | rejected | tip
  body text not null,
  created_at timestamptz default now()
);

create table if not exists intros (
  id uuid primary key default gen_random_uuid(),
  requester uuid references students(id) on delete cascade,
  target uuid references students(id) on delete cascade,
  company text not null,
  question text,
  status text not null default 'pending',  -- pending | accepted | declined | answered
  answer text,
  created_at timestamptz default now()
);

alter table students enable row level security;
alter table applications enable row level security;
alter table reports enable row level security;
alter table intros enable row level security;
-- No policies on purpose: anon can't touch tables directly.

create or replace function _sid(p_token text) returns uuid
language sql security definer set search_path = public as $$
  select id from students where token = p_token
$$;

create or replace function _norm(t text) returns text
language sql immutable as $$ select lower(regexp_replace(trim(t), '\s+', ' ', 'g')) $$;

-- Register or update a student. Returns their id.
create or replace function pulse_join(p_token text, p_grad text, p_major text, p_contact text)
returns uuid language plpgsql security definer set search_path = public as $$
declare v uuid;
begin
  insert into students(token, grad, major, contact) values (p_token, p_grad, p_major, p_contact)
  on conflict (token) do update set
    grad = coalesce(excluded.grad, students.grad),
    major = coalesce(excluded.major, students.major),
    contact = coalesce(excluded.contact, students.contact)
  returning id into v;
  return v;
end $$;

-- Log or update an application.
create or replace function pulse_apply(p_token text, p_company text, p_role text, p_status text)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token);
begin
  if s is null then raise exception 'unknown student'; end if;
  insert into applications(student_id, company, role, status)
  values (s, _norm(p_company), _norm(p_role), coalesce(p_status, 'applied'))
  on conflict (student_id, company, role) do update
    set status = coalesce(excluded.status, applications.status), updated_at = now();
  return json_build_object('ok', true);
end $$;

-- Post an interview report / tip. Counts as a contribution for give-to-get.
create or replace function pulse_report(p_token text, p_company text, p_role text, p_stage text, p_body text)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token); n int;
begin
  if s is null then raise exception 'unknown student'; end if;
  if length(coalesce(p_body, '')) < 10 then raise exception 'report too short'; end if;
  select count(*) into n from reports where student_id = s and created_at > now() - interval '1 day';
  if n >= 10 then raise exception 'daily report limit'; end if;
  insert into reports(student_id, company, role, stage, body)
  values (s, _norm(p_company), _norm(p_role), p_stage, left(p_body, 2000));
  -- how many other students are waiting on this company (they will be notified on their next check)
  return json_build_object('ok', true, 'waiting_students',
    (select count(distinct student_id) from applications
     where company = _norm(p_company) and student_id <> s
       and status in ('applied', 'oa', 'interview')));
end $$;

-- Where do I stand for a company? Aggregates only when >= 3 other students reported (privacy).
-- Reports are unlocked only if the student has contributed at least one report (give-to-get).
create or replace function pulse_status(p_token text, p_company text)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token); c text := _norm(p_company); others int; contributed boolean; mine json;
begin
  if s is null then raise exception 'unknown student'; end if;
  select count(distinct student_id) into others from applications where company = c and student_id <> s;
  select exists(select 1 from reports where student_id = s) into contributed;
  select json_agg(json_build_object('role', role, 'status', status,
         'days_since_applied', extract(day from now() - applied_at)::int))
    into mine from applications where student_id = s and company = c;
  return json_build_object(
    'company', c,
    'my_applications', coalesce(mine, '[]'::json),
    'others_applied', others,
    'enough_data', others >= 3,
    'status_counts', case when others >= 3 then (
        select json_object_agg(status, n) from (
          select status, count(*) n from applications where company = c and student_id <> s group by status) x)
      else null end,
    'median_days_to_first_response', case when others >= 3 then (
        select percentile_cont(0.5) within group (order by extract(epoch from updated_at - applied_at) / 86400)
        from applications where company = c and student_id <> s and status <> 'applied') else null end,
    'unlocked', contributed,
    'reports', case when contributed then (
        select coalesce(json_agg(r order by r.created_at desc), '[]'::json) from (
          select role, stage, body, created_at from reports
          where company = c and student_id <> s order by created_at desc limit 8) r)
      else null end,
    'locked_report_count', case when contributed then 0 else
      (select count(*) from reports where company = c and student_id <> s) end
  );
end $$;

-- New reports since a timestamp for every company I'm waiting on (used by the scheduled check).
create or replace function pulse_feed(p_token text, p_since timestamptz)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token); contributed boolean;
begin
  if s is null then raise exception 'unknown student'; end if;
  select exists(select 1 from reports where student_id = s) into contributed;
  return json_build_object('unlocked', contributed, 'items', (
    select coalesce(json_agg(x order by x.created_at desc), '[]'::json) from (
      select r.company, r.role, r.stage,
             case when contributed then r.body else null end as body, r.created_at
      from reports r
      where r.student_id <> s and r.created_at > p_since
        and r.company in (select company from applications
                          where student_id = s and status in ('applied', 'oa', 'interview'))
      order by r.created_at desc limit 10) x));
end $$;

-- Ask to talk to someone further along at a company. Max 3 requests per day.
create or replace function pulse_intro_request(p_token text, p_company text, p_question text)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token); c text := _norm(p_company); t uuid; n int;
begin
  if s is null then raise exception 'unknown student'; end if;
  select count(*) into n from intros where requester = s and created_at > now() - interval '1 day';
  if n >= 3 then return json_build_object('ok', false, 'reason', 'daily limit of 3 intro requests'); end if;
  -- best candidate: furthest stage at that company, not paused, not already asked by me, fewest open requests
  select a.student_id into t from applications a join students st on st.id = a.student_id
  where a.company = c and a.student_id <> s and not st.intros_paused
    and a.status in ('offer', 'interview', 'oa')
    and not exists (select 1 from intros i where i.requester = s and i.target = a.student_id and i.company = c)
    and (select count(*) from intros i where i.target = a.student_id and i.created_at > now() - interval '7 days') < 5
  order by case a.status when 'offer' then 0 when 'interview' then 1 else 2 end,
           a.updated_at desc
  limit 1;
  if t is null then return json_build_object('ok', false, 'reason', 'no one available right now'); end if;
  insert into intros(requester, target, company, question) values (s, t, c, left(p_question, 500));
  return json_build_object('ok', true);
end $$;

-- Requests waiting for my answer, and updates on requests I made.
create or replace function pulse_inbox(p_token text)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token);
begin
  if s is null then raise exception 'unknown student'; end if;
  return json_build_object(
    'to_answer', (select coalesce(json_agg(json_build_object(
        'id', i.id, 'company', i.company, 'question', i.question,
        'from_grad', r.grad, 'from_major', r.major)), '[]'::json)
      from intros i join students r on r.id = i.requester
      where i.target = s and i.status = 'pending' and i.created_at > now() - interval '48 hours'),
    'my_requests', (select coalesce(json_agg(json_build_object(
        'id', i.id, 'company', i.company, 'status', i.status, 'answer', i.answer,
        'contact', case when i.status = 'accepted' then t.contact else null end)), '[]'::json)
      from intros i join students t on t.id = i.target
      where i.requester = s and i.created_at > now() - interval '14 days'));
end $$;

-- Answer a request: 'accept' (share contacts both ways), 'answer' (anonymous reply), 'decline'.
create or replace function pulse_intro_respond(p_token text, p_intro uuid, p_action text, p_answer text)
returns json language plpgsql security definer set search_path = public as $$
declare s uuid := _sid(p_token); i intros; rc text;
begin
  if s is null then raise exception 'unknown student'; end if;
  select * into i from intros where id = p_intro and target = s and status = 'pending';
  if i.id is null then return json_build_object('ok', false, 'reason', 'request not found or already answered'); end if;
  if p_action = 'accept' then
    update intros set status = 'accepted' where id = i.id;
    select contact into rc from students where id = i.requester;
    return json_build_object('ok', true, 'requester_contact', rc);
  elsif p_action = 'answer' then
    update intros set status = 'answered', answer = left(p_answer, 2000) where id = i.id;
    return json_build_object('ok', true);
  else
    update intros set status = 'declined' where id = i.id;
    return json_build_object('ok', true);
  end if;
end $$;

create or replace function pulse_pause(p_token text, p_paused boolean)
returns json language plpgsql security definer set search_path = public as $$
begin
  update students set intros_paused = p_paused where token = p_token;
  return json_build_object('ok', true, 'paused', p_paused);
end $$;

-- Lock everything down, then expose only the functions to anon.
revoke all on all tables in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;
grant execute on function pulse_join(text, text, text, text) to anon;
grant execute on function pulse_apply(text, text, text, text) to anon;
grant execute on function pulse_report(text, text, text, text, text) to anon;
grant execute on function pulse_status(text, text) to anon;
grant execute on function pulse_feed(text, timestamptz) to anon;
grant execute on function pulse_intro_request(text, text, text) to anon;
grant execute on function pulse_inbox(text) to anon;
grant execute on function pulse_intro_respond(text, uuid, text, text) to anon;
grant execute on function pulse_pause(text, boolean) to anon;
