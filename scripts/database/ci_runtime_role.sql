DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'funnel_crm_runtime'
    ) THEN
        CREATE ROLE funnel_crm_runtime
            NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO funnel_crm_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO funnel_crm_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO funnel_crm_runtime;
