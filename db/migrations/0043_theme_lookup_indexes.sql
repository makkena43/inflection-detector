-- 0043: lookups the 3.6.x packet sections make once per packet (theme snapshot date, company roles by symbol).
BEGIN;
CREATE INDEX IF NOT EXISTS theme_beneficiaries_as_of ON theme_beneficiaries (as_of_date, recorded_at);
CREATE INDEX IF NOT EXISTS mg_company_capabilities_ticker ON makrograph_ref.mg_company_capabilities (upper(ticker), as_of_date);
CREATE INDEX IF NOT EXISTS mg_company_product_roles_ticker ON makrograph_ref.mg_company_product_roles (upper(ticker), as_of_date);
INSERT INTO schema_migrations (version) VALUES ('0043_theme_lookup_indexes');
COMMIT;
