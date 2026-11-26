-- Read-only role for the public Grafana. Anonymous Grafana viewers can send
-- arbitrary queries through a datasource, so this role may only SELECT the
-- exact tables/columns the analytics dashboard needs. NEVER give Grafana the
-- owner account.
--
-- Run in the Neon SQL editor. Replace CHANGE_ME with a strong password.

-- 1) Run once (any database):
CREATE ROLE grafana_ro WITH LOGIN PASSWORD 'CHANGE_ME';

-- 2) Switch the SQL editor to database "codebridge_project", then run:
GRANT CONNECT ON DATABASE codebridge_project TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON projects, project_requirements TO grafana_ro;

-- 3) Switch the SQL editor to database "codebridge_identity", then run.
--    Column-level grant: NO access to email, names or password hashes.
GRANT CONNECT ON DATABASE codebridge_identity TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT (id, role, is_active, created_at) ON users TO grafana_ro;
