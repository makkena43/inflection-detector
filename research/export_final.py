"""Export picks (with the dashboard's own as-of features) + daily prices for the final rules backtest.
Read-only. Writes picks.csv, prices.csv, index.csv next to this file."""
import csv, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/Users/makkenasrinivas/inflection-jobs/ui")
sys.path.insert(0, "/Users/makkenasrinivas/PycharmProjects/inflection-detector/src")
import app  # dashboard module; server only starts under __main__
import psycopg

rows = app.picks(0, "picks")          # one DEEP pick per issuer per year, all years
flat = []
for r in rows:
    d = {}
    for k, v in r.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if not isinstance(v2, (dict, list)): d[f"{k}.{k2}"] = v2
        elif isinstance(v, list): d[k] = "; ".join(map(str, v))
        else: d[k] = v
    flat.append(d)
keys = sorted({k for d in flat for k in d})
with open(os.path.join(HERE, "picks.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, keys); w.writeheader(); w.writerows(flat)
print("picks", len(flat), flush=True)

c = psycopg.connect("postgresql:///inflection")
issuers = sorted({str(r["issuer_id"]) for r in rows})
n_missing = 0
with open(os.path.join(HERE, "prices.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["issuer_id", "trade_date", "close", "turnover_cr"])
    for iss in issuers:
        s = c.execute("""select h.security_id from securities s join identifier_history h using(security_id) where s.issuer_id=%s
                         and h.exchange='NSE' and h.kind='SYMBOL' order by h.valid_to nulls first limit 1""", (iss,)).fetchone()
        if not s: n_missing += 1; continue
        for d, cl, t in c.execute("""
            select a.trade_date, a.close, u.close*u.volume/1e7 from
              (select distinct on (trade_date) trade_date, close::float from prices_split_bonus_adjusted
                where security_id=%s and provider='nse_bhavcopy' and close>0 and trade_date>='2020-01-01' order by trade_date) a
            left join (select distinct on (trade_date) trade_date, close::float, volume::float from prices
                where security_id=%s and provider='nse_bhavcopy' and adjustment='UNADJUSTED' and trade_date>='2020-01-01' order by trade_date) u
            using (trade_date) order by 1""", (s[0], s[0])).fetchall():
            w.writerow([iss, d, round(cl, 4), round(t, 3) if t is not None else ""])
print("issuers", len(issuers), "without NSE symbol", n_missing, flush=True)

with open(os.path.join(HERE, "index.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["index_name", "trade_date", "close"])
    for row in c.execute("""select index_name, trade_date, close::float from index_closes where trade_date>='2020-01-01'
                            order by 1, 2""").fetchall():
        w.writerow(row)
print("done", flush=True)
