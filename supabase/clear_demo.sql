-- Removes all seeded demo data (students whose token starts with 'seed-').
-- Applications, reports and intros are removed automatically (on delete cascade).
delete from students where token like 'seed-%';
