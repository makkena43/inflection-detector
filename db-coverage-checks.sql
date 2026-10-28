-- Read-only coverage checks for the local `inflection` database.
-- Run:  psql inflection -f db-coverage-checks.sql > db-checks-out.txt   and paste the output back.
-- Nothing here writes; every statement is a SELECT.

\echo '== 1. migrations applied'
SELECT version FROM schema_migrations ORDER BY version;

\echo '== 2. issuers, securities, prices'
SELECT (SELECT count(*) FROM issuers) AS issuers, (SELECT count(*) FROM securities) AS securities,
       (SELECT count(*) FROM prices) AS price_rows,
       (SELECT min(trade_date) FROM prices) AS first_price, (SELECT max(trade_date) FROM prices) AS last_price;
SELECT exchange, count(*) AS rows, min(trade_date), max(trade_date) FROM bhavcopy_rows GROUP BY exchange;

\echo '== 3. filings by source and pipeline state'
SELECT s.name AS source, p.pipeline_state, count(*) AS filings,
       min(p.published_at)::date AS first, max(p.published_at)::date AS last,
       count(*) FILTER (WHERE p.issuer_id IS NULL) AS no_issuer
  FROM document_publications p JOIN sources s USING (source_id)
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 4. filings per year (announcements vs results XBRL)'
SELECT s.name AS source, extract(year FROM p.published_at)::int AS year, count(*)
  FROM document_publications p JOIN sources s USING (source_id)
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 5. ingestion runs by source and coverage status'
SELECT s.name AS source, r.coverage_status, count(*) AS runs,
       min(r.window_start)::date AS from, max(r.window_end)::date AS to
  FROM ingestion_runs r JOIN sources s USING (source_id)
 GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 6. results figures'
SELECT scope, period_type, count(DISTINCT issuer_id) AS companies, count(DISTINCT publication_id) AS filings,
       min(period_end), max(period_end)
  FROM financial_facts GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== 7. route scans'
SELECT 'commercial' AS route, status, count(*) FROM commercial_scans GROUP BY 2
UNION ALL
SELECT 'financial', status, count(*) FROM financial_scans GROUP BY 2 ORDER BY 1, 2;

\echo '== 8. events and candidate evaluations'
SELECT (SELECT count(*) FROM events) AS events, (SELECT count(*) FROM event_versions) AS event_versions;
SELECT route, priority_class, queue_allocation, count(*) AS evaluations, count(DISTINCT issuer_id) AS companies,
       min(as_of)::date AS first, max(as_of)::date AS last
  FROM candidate_evaluations GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

\echo '== 9. companies per week by best class (what a weekly shortlist would face), last 12 weeks'
WITH w AS (SELECT date_trunc('week', as_of AT TIME ZONE 'Asia/Kolkata')::date AS week, issuer_id,
                  min(CASE priority_class WHEN 'U0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END) AS best
             FROM candidate_evaluations GROUP BY 1, 2)
SELECT week, count(*) FILTER (WHERE best <= 2) AS u0_p1_p2, count(*) FILTER (WHERE best = 3) AS p3,
       count(*) FILTER (WHERE best = 4) AS d
  FROM w GROUP BY week ORDER BY week DESC LIMIT 12;
