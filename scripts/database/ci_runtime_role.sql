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

-- Global identity and permission catalogs are readable by the service but are
-- changed only by their dedicated provisioning/migration paths.
REVOKE INSERT, UPDATE, DELETE ON TABLE user_identities FROM funnel_crm_runtime;
REVOKE INSERT, UPDATE, DELETE ON TABLE permission_definitions FROM funnel_crm_runtime;

-- Audit history can be read and appended, but never changed through the runtime role.
REVOKE UPDATE, DELETE ON TABLE audit_events FROM funnel_crm_runtime;
