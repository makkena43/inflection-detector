-- 0041: which side of a theme a company is on (inflection.themes.emergent, version emergent-4).
-- role is read from the passage wording: MAKER (capacity / production / launch), SUPPLIER (order received,
-- qualification), EPC (order received for erection / installation / turnkey work), BUYER (order placed, captive
-- use), or NULL when the wording does not say. Rows of earlier versions keep NULL.
BEGIN;
ALTER TABLE theme_phrase_mentions ADD COLUMN role text
    CHECK (role IN ('MAKER', 'SUPPLIER', 'EPC', 'BUYER'));
ALTER TABLE emergent_theme_companies ADD COLUMN role text
    CHECK (role IN ('MAKER', 'SUPPLIER', 'EPC', 'BUYER'));
INSERT INTO schema_migrations (version) VALUES ('0041_emergent_roles');
COMMIT;
