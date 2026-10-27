"""Export picks (with the dashboard's own as-of features) + daily prices for the final rules backtest.
Read-only. Writes picks.csv, prices.csv, index.csv next to this file."""
import csv, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/Users/makkenasrinivas/inflection-jobs/ui")
sys.path.insert(0, "/Users/makkenasrinivas/PycharmProjects/inflection-detector/src")
import app  # dashboard module; server only starts under __main__
import psycopg
import combo_flags  # same price source rule as the dashboard

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
n_missing = n_bse = 0
with open(os.path.join(HERE, "prices.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["issuer_id", "trade_date", "close", "turnover_cr"])
    for iss in issuers:
        sec, prov = combo_flags.price_source(c, iss)  # NSE listing, else BSE for BSE-only companies
        if not sec: n_missing += 1; continue
        n_bse += prov == "bse_bhavcopy"
        q = """select a.trade_date, a.close, u.close*u.volume/1e7 from
              (select distinct on (trade_date) trade_date, close::float from {src}
                where security_id=%s and provider=%s and close>0 and trade_date>='2020-01-01' {adj} order by trade_date) a
            left join (select distinct on (trade_date) trade_date, close::float, volume::float from prices
                where security_id=%s and provider=%s and adjustment='UNADJUSTED' and trade_date>='2020-01-01' order by trade_date) u
            using (trade_date) order by 1"""
        rows_ = c.execute(q.format(src="prices_split_bonus_adjusted", adj=""), (sec, prov, sec, prov)).fetchall()
        if len(rows_) < 60:  # no adjusted series (BSE): raw closes; final_rules drops names with split-size jumps
            rows_ = c.execute(q.format(src="prices", adj="and adjustment='UNADJUSTED'"), (sec, prov, sec, prov)).fetchall()
        for d, cl, t in rows_:
            w.writerow([iss, d, round(cl, 4), round(t, 3) if t is not None else ""])
print("issuers", len(issuers), "priced from BSE", n_bse, "without prices", n_missing, flush=True)

with open(os.path.join(HERE, "index.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["index_name", "trade_date", "close"])
    for row in c.execute("""select index_name, trade_date, close::float from index_closes where trade_date>='2020-01-01'
                            order by 1, 2""").fetchall():
        w.writerow(row)
print("done", flush=True)
