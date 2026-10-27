"""Final selection + trading-rule backtest on the triage picks (2026-10-26).

Input: picks.csv / prices.csv / index.csv written by export_final.py (dashboard features, adjusted NSE closes).
Each pick is enriched with the dashboard's op_margin() (OPM change, TTM revenue growth, liquidity) as of its week.

Split, fixed before looking: train = 2021-2023 picks, validate = 2024, holdout = 2025-2026 (open trades marked to market).
Returns are price only, minus 0.5% round-trip cost, compared with the Nifty Smallcap 250 over the same holding.

Usage: python final_rules.py DIR   (DIR holds the three CSVs; writes trades.csv and results.txt there)
"""
import bisect
import csv
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta

DIR = sys.argv[1]
COST = 0.005
OUT = open(os.path.join(DIR, "results.txt"), "w")


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s); OUT.write(s + "\n")


def fnum(x):
    try:
        return float(x) if x not in (None, "", "None") else None
    except ValueError:
        return None


def fbool(x):
    return str(x).lower() in ("true", "t", "1")


# ---------- data ----------
picks = list(csv.DictReader(open(os.path.join(DIR, "picks.csv"))))
try:
    sys.path.insert(0, "/Users/makkenasrinivas/inflection-jobs/ui")
    sys.path.insert(0, "/Users/makkenasrinivas/PycharmProjects/inflection-detector/src")
    import app
    for p in picks:
        opm, opm_chg, revg, liq = app.op_margin(p["issuer_id"], date.fromisoformat(p["week_start"][:10]))
        p["opm_chg"], p["revg"], p["liq"] = opm_chg, revg, liq
except ImportError:  # offline test run
    pass

px = defaultdict(list)
for r in csv.DictReader(open(os.path.join(DIR, "prices.csv"))):
    px[r["issuer_id"]].append((date.fromisoformat(r["trade_date"]), float(r["close"]), fnum(r["turnover_cr"])))
idx = defaultdict(list)
for r in csv.DictReader(open(os.path.join(DIR, "index.csv"))):
    idx[r["index_name"]].append((date.fromisoformat(r["trade_date"]), float(r["close"])))
SC = sorted(idx["Nifty Smallcap 250"]); scd = [d for d, _ in SC]; scv = [v for _, v in SC]; LAST = scd[-1]


def sc(d):
    i = bisect.bisect_left(scd, d)
    return scv[min(i, len(scv) - 1)]


class Series:
    def __init__(self, rows):
        rows.sort()
        self.d = [r[0] for r in rows]; self.p = [r[1] for r in rows]; self.t = [r[2] for r in rows]
        self.c = [0.0]
        for v in self.p: self.c.append(self.c[-1] + v)

    def sma(self, k, n):
        return (self.c[k + 1] - self.c[k + 1 - n]) / n if k + 1 >= n else None

    def at(self, d):
        return bisect.bisect_left(self.d, d)


SER = {i: Series(r) for i, r in px.items()}
bad = set()
for i, s in SER.items():  # unadjusted corporate actions show as one-day jumps; drop those names
    if any(b / a > 1.8 or b / a < 0.45 for a, b in zip(s.p, s.p[1:])): bad.add(i)

# ---------- per-pick features ----------
P = []
for p in picks:
    iss = p["issuer_id"]
    if iss not in SER or iss in bad: continue
    s = SER[iss]; wk = date.fromisoformat(p["week_start"][:10])
    k = s.at(wk + timedelta(days=14))
    if k >= len(s.d) or (s.d[k] - wk).days > 30: continue
    k7 = s.at(wk + timedelta(days=7))
    p0 = s.p[k]
    sma200, sma50 = s.sma(k, 200), s.sma(k, 50)
    sma200_old = s.sma(k - 20, 200) if k >= 220 else None
    hi = max(s.p[max(0, k - 251):k + 1])
    k6 = s.at(s.d[k] - timedelta(days=182))
    r6 = p0 / s.p[k6] - 1 if k6 < k else None
    sc6 = sc(s.d[k]) / sc(s.d[k] - timedelta(days=182)) - 1
    tv = [t for t in s.t[max(0, k - 60):k] if t]
    x = dict(
        p=p, iss=iss, label=p["label"], wk=wk, year=wk.year, s=s, k=k, k7=k7 if k7 < len(s.d) else k,
        firm=fbool(p.get("firm")), routine=fbool(p.get("routine")),
        revg=fnum(p.get("revg")), opm=fnum(p.get("opm")), opm_chg=fnum(p.get("opm_chg")), ps=fnum(p.get("ps")),
        mcap=fnum(p.get("mcap_cr")), o_mc=fnum(p.get("order_to_mcap")), size=fnum(p.get("size_pct_of_revenue")),
        score=fnum(p.get("score")), tech=fnum(p.get("tech_score")), o12=fnum(p.get("orders_12m_pct")),
        oy1=fnum(p.get("orders_y1_pct")), liq=fnum(p.get("liq")) if p.get("liq") not in (None, "") else (st.median(tv) if tv else None),
        prom=fnum(p.get("promoter_yoy_pp")), prom_q=fnum(p.get("promoter_change_pp")),
        fii=fnum(p.get("fii_yoy_pp")), fii_q=fnum(p.get("fii_change_pp")),
        runup6=r6,
        # own technicals at entry (no look-ahead): uptrend, near 52w high, beating the index over 6m
        t_up=bool(sma200 and sma50 and sma200_old and p0 > sma200 and sma50 > sma200 and sma200 > sma200_old),
        t_hi=p0 >= 0.80 * hi, t_rs=r6 is not None and r6 > sc6,
    )
    x["t3"] = x["t_up"] + x["t_hi"] + x["t_rs"]
    x["split"] = "train" if x["year"] <= 2023 else ("valid" if x["year"] == 2024 else "hold")
    P.append(x)
# buy each company once per 12 months: a later pick of the same issuer within 365 days of a kept one is a repeat
P.sort(key=lambda x: x["wk"]); _last = {}; _keep = []
for x in P:
    if x["iss"] in _last and (x["wk"] - _last[x["iss"]]).days < 365: continue
    _last[x["iss"]] = x["wk"]; _keep.append(x)
REPEATS = len(P) - len(_keep); P = _keep
say(f"picks {len(picks)}, with clean NSE prices {len(P)} (dropped for jumps: {len(bad)}; repeats within 12m: {REPEATS})")
say("by year:", dict(sorted(defaultdict(int, {y: sum(1 for x in P if x['year'] == y) for y in range(2021, 2027)}).items())))
say("revg known:", sum(x["revg"] is not None for x in P), " score known:", sum(x["score"] is not None for x in P),
    " promoter chg known:", sum(x["prom"] is not None for x in P))


def gt(v, t): return v is not None and v > t
def lt(v, t): return v is not None and v < t
def ge(v, t): return v is not None and v >= t


S1 = lambda x: x["firm"] and gt(x["revg"], 0)
SEL = {
    "S0 all picks": lambda x: True,
    "S1 firm + revenue growing": S1,
    "S2 score>=4": lambda x: ge(x["score"], 4),
    "S3 score>=5": lambda x: ge(x["score"], 5),
    "S4 S1 + score>=4": lambda x: S1(x) and ge(x["score"], 4),
    "S5 S1 + cheap or thin (P/S<1.5 or OPM<10%)": lambda x: S1(x) and (lt(x["ps"], 1.5) or lt(x["opm"], 0.10)),
    "S6 S1 + P/S<1.5": lambda x: S1(x) and lt(x["ps"], 1.5),
    "S7 S1 + order>=25% mcap": lambda x: S1(x) and ge(x["o_mc"], 0.25),
    "S8 S1 + technicals 2-3/3": lambda x: S1(x) and x["t3"] >= 2,
    "S9 S1 + liquid >=0.5cr/day": lambda x: S1(x) and ge(x["liq"], 0.5),
    "S10 S1 + 12m orders>=50% rev": lambda x: S1(x) and ge(x["o12"], 50),
    "S11 S1 + promoter not cut": lambda x: S1(x) and not lt(x["prom"], -0.5),
    "S12 S1 + growth>20%": lambda x: x["firm"] and gt(x["revg"], 0.20 if (x["revg"] or 0) < 5 else 20),
    "S13 not S1 (rest)": lambda x: not S1(x),
}


# ---------- exit rules ----------
def sim(x, stop=None, trail=None, arm=None, maxd=730, half=None, time6=False, dma=False, entry="k", target=None):
    """Return (events, open): events = [(index, fraction_sold)]. arm: trailing stop starts once gain >= arm."""
    s = x["s"]; k0 = x[entry]; d0, p0 = s.d[k0], s.p[k0]; peak = p0; left = 1.0; ev = []
    armed = arm is None; checked6 = False
    for k in range(k0 + 1, len(s.d)):
        d, p = s.d[k], s.p[k]; peak = max(peak, p); days = (d - d0).days
        if half and left == 1.0 and p >= p0 * half:
            ev.append((k, 0.5)); left = 0.5
        if arm is not None and p >= p0 * (1 + arm): armed = True
        hit = False
        if stop and not (arm is not None and armed) and p <= p0 * (1 - stop): hit = True
        if trail and armed and p <= peak * (1 - trail): hit = True
        if time6 and not checked6 and days >= 182:
            checked6 = True
            if p < p0 and p / p0 < sc(d) / sc(d0): hit = True
        if dma and days >= 91:
            m = s.sma(k, 200)
            if m and p < 0.97 * m: hit = True
        if target and p >= p0 * target: hit = True
        if days >= maxd: hit = True
        if hit:
            ev.append((k, left)); return ev, False
    ev.append((len(s.d) - 1, left)); return ev, True


EXITS = {
    "E1 hold 12m": dict(maxd=365),
    "E2 hold 24m": dict(maxd=730),
    "E3 hold 36m": dict(maxd=1095),
    "E4 stop -20%, else 24m": dict(stop=0.20),
    "E5 stop -30%, else 24m": dict(stop=0.30),
    "E6 trail 30% from peak, max 36m": dict(trail=0.30, maxd=1095),
    "E7 stop -20% until +30%, then trail 25%, max 36m": dict(stop=0.20, trail=0.25, arm=0.30, maxd=1095),
    "E8 sell half at 2x, trail 30%, max 36m": dict(half=2.0, trail=0.30, maxd=1095),
    "E9 6m check (exit if down and lagging), else 24m": dict(time6=True),
    "E10 exit below 200DMA after 3m, max 36m": dict(dma=True, maxd=1095),
    "E11 stop -25% until 2x; sell half at 2x; trail 30%; 36m": dict(stop=0.25, half=2.0, trail=0.30, arm=1.0, maxd=1095),
    "E12 stop -25% until +50%, then trail 30%, max 36m": dict(stop=0.25, trail=0.30, arm=0.50, maxd=1095),
}


def outcome(x, rule, entry="k"):
    s = x["s"]; k0 = x[entry]; d0, p0 = s.d[k0], s.p[k0]
    ev, op = sim(x, entry=entry, **rule)
    mult = sum(f * s.p[k] / p0 for k, f in ev) - COST
    bench = sum(f * sc(s.d[k]) / sc(d0) for k, f in ev)
    yrs = max(sum(f * (s.d[k] - d0).days for k, f in ev) / 365.25, 1 / 52)
    return dict(mult=mult, ex=mult - bench, yrs=yrs, open=op)


def summarise(rows):
    if not rows: return "n=0"
    m = [r["mult"] - 1 for r in rows]; e = [r["ex"] for r in rows]; y = st.mean(r["yrs"] for r in rows)
    m.sort()
    p10 = m[max(0, int(len(m) * 0.1) - 1)] if len(m) >= 5 else m[0]
    cagr = (1 + st.mean(m)) ** (1 / y) - 1 if y > 0.1 else float("nan")
    return (f"n={len(rows):3d} med {100*st.median(m):+5.0f}% mean {100*st.mean(m):+5.0f}% | vs SC med {100*st.median(e):+5.0f}% "
            f"beat {100*sum(v>0 for v in e)/len(e):3.0f}% | worst10% {100*p10:+4.0f}% | yrs {y:.1f} ~{100*cagr:+.0f}%/yr")


# ---------- 4. portfolio simulation ----------
def portfolio(f, rule, start, size=0.05, maxpos=20):
    trades = []
    for x in P:
        if not f(x): continue
        s = x["s"]; k0 = x["k"]
        if s.d[k0] < start: continue
        ev, _ = sim(x, **rule)
        trades.append((s.d[k0], x, ev))
    trades.sort(key=lambda t: t[0])
    cash, pos, eq_hist, ti, n = 100.0, [], [], 0, 0
    days = [d for d in scd if d >= start]
    for d in days:
        # exits
        for ps_ in pos:
            s = ps_["x"]["s"]
            while ps_["ev"] and s.d[ps_["ev"][0][0]] <= d:
                k, frac = ps_["ev"].pop(0)
                cash += ps_["sh0"] * frac * s.p[k] * (1 - COST / 2); ps_["sh"] -= ps_["sh0"] * frac
        pos = [q for q in pos if q["ev"]]
        # entries
        while ti < len(trades) and trades[ti][0] <= d:
            _, x, ev = trades[ti]; ti += 1
            if len(pos) >= maxpos or any(q["x"]["iss"] == x["iss"] for q in pos): continue
            eq = cash + sum(q["sh"] * q["x"]["s"].p[min(q["x"]["s"].at(d), len(q["x"]["s"].d) - 1)] for q in pos)
            amt = min(eq * size, cash)
            if amt <= 0: continue
            p0 = x["s"].p[x["k"]]
            cash -= amt; sh = amt * (1 - COST / 2) / p0
            pos.append(dict(x=x, ev=list(ev), sh=sh, sh0=sh)); n += 1
        val = 0.0
        for q in pos:
            s = q["x"]["s"]; j = bisect.bisect_right(s.d, d) - 1
            val += q["sh"] * s.p[max(j, 0)]
        eq_hist.append((d, cash + val, val))
    e0, e1 = eq_hist[0][1], eq_hist[-1][1]; yrs = (eq_hist[-1][0] - eq_hist[0][0]).days / 365.25
    peak, mdd = 0, 0
    for _, v, _ in eq_hist:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    b = sc(eq_hist[-1][0]) / sc(eq_hist[0][0])
    expo = st.mean(v / t for _, t, v in eq_hist)
    return (f"CAGR {100*((e1/e0)**(1/yrs)-1):+5.1f}% vs SC250 {100*(b**(1/yrs)-1):+5.1f}% | max DD {100*mdd:.0f}% | "
            f"trades {n} | avg invested {100*expo:.0f}%")



EXTRA = len(sys.argv) > 2 and sys.argv[2] == "extra"
if EXTRA:
    say("\n## 5. Score gates and stop levels, portfolio 5% x 20")
    SEL["S14 score>=3"] = lambda x: ge(x["score"], 3)
    for start, lab in ((date(2021, 1, 1), "2021-now"), (date(2024, 1, 1), "2024-now"), (date(2025, 1, 1), "2025-now")):
        for sname in ("S0 all picks", "S14 score>=3", "S2 score>=4", "S3 score>=5"):
            for st_ in (0.15, 0.20, 0.25, 0.30):
                say(f"   {lab:9s} {sname:14s} stop -{int(st_*100)}% else 24m  {portfolio(SEL[sname], dict(stop=st_), start)}")
            say(f"   {lab:9s} {sname:14s} stop -20% else 36m   {portfolio(SEL[sname], dict(stop=0.20, maxd=1095), start)}")
            say(f"   {lab:9s} {sname:14s} stop -20%, after 2x trail 30%, 36m {portfolio(SEL[sname], dict(stop=0.20, trail=0.30, arm=1.0, maxd=1095), start)}")

    sys.exit(0)




if len(sys.argv) > 2 and sys.argv[2] == "runup":
    # Does skipping picks whose price already ran 3x/5x/10x before entry improve the rulebook and watch-list combos?
    def back(x, days):
        s = x["s"]; k = x["k"]; j = s.at(s.d[k] - timedelta(days=days))
        return s.p[k] / s.p[j] if j < k and (s.d[k] - s.d[j]).days >= days - 10 else None
    for x in P:
        s, k = x["s"], x["k"]
        x["r1y"], x["r2y"], x["r3y"] = back(x, 365), back(x, 730), back(x, 1095)
        x["xlow"] = s.p[k] / min(s.p[s.at(s.d[k] - timedelta(days=1095)):k + 1])
        x["hist"] = (s.d[k] - s.d[0]).days / 365.25
        q = x["p"]; x["prom_pct"] = fnum(q.get("promoter_holding_pct"))
        x["p36"] = outcome(x, dict(stop=0.20, maxd=1095))["mult"] - 1
        x["ex36"] = outcome(x, dict(stop=0.20, maxd=1095))["ex"]
    sz = lambda x, v: (x["size"] or 0) >= v
    CB = {"ALL picks": lambda x: True,
          "C1 order100%+near high+liq2cr": lambda x: sz(x, 100) and x["t_hi"] and (x["liq"] or 0) >= 2,
          "C2 order25%+near high+6m>60%": lambda x: sz(x, 25) and x["t_hi"] and (x["runup6"] or 0) > 0.60,
          "C3 order25%+OPM<10%+uptrend": lambda x: sz(x, 25) and x["opm"] is not None and x["opm"] < 0.10 and x["t3"] >= 2,
          "C4 order100%+not routine+200DMA": lambda x: sz(x, 100) and not x["routine"] and x["t_up"],
          "C5 FII up qoq+prom60%+near high": lambda x: gt(x["fii_q"], 0) and (x["prom_pct"] or 0) >= 60 and x["t_hi"],
          "R1 order300%+uptrend": lambda x: sz(x, 300) and x["t3"] >= 2,
          "R2 order200%+FII up qoq": lambda x: sz(x, 200) and gt(x["fii_q"], 0),
          "R3 order200%+ of mcap": lambda x: (x["o_mc"] or 0) >= 2.0}
    CB["ANY C1-C5"] = lambda x: any(CB[c](x) for c in CB if c[:1] == "C")
    if len(sys.argv) > 3 and sys.argv[3] == "period":
        say("## 18. Skip picks whose price rose >= T in the 12 months before entry: per period, kept vs skipped")
        say("   cells: period kept n / profit per 1L (stop -20%, 36m) / median vs SC  ||  skipped n / profit / median vs SC")
        for c, f in CB.items():
            say(f"\n   {c}")
            for T in (1.5, 2.0, 3.0):
                cells = []
                for sp, lab in (("train", "21-23"), ("valid", "24"), ("hold", "25-26")):
                    sel = [x for x in P if f(x) and x["split"] == sp]
                    a = [x for x in sel if not ge(x["r1y"], T)]; b = [x for x in sel if ge(x["r1y"], T)]
                    q = lambda v: (f"n{len(v)} Rs{1e5*st.mean(x['p36'] for x in v)/1e5:.2f}L {100*st.median(x['ex36'] for x in v):+.0f}%" if v else "n0")
                    cells.append(f"{lab}: {q(a)} || {q(b)}")
                say(f"      skip 1y>={T}x  " + " | ".join(cells))
        sys.exit(0)
    RULES = {"1y>=2x": lambda x: ge(x["r1y"], 2), "1y>=3x": lambda x: ge(x["r1y"], 3), "2y>=3x": lambda x: ge(x["r2y"], 3),
             "2y>=5x": lambda x: ge(x["r2y"], 5), "3y>=5x": lambda x: ge(x["r3y"], 5), "3y>=10x": lambda x: ge(x["r3y"], 10),
             "3y-low>=3x": lambda x: x["xlow"] >= 3, "3y-low>=5x": lambda x: x["xlow"] >= 5, "3y-low>=10x": lambda x: x["xlow"] >= 10}
    say("## 17. Prior run-up before entry (price at entry vs 1y/2y/3y earlier, and vs lowest close in the 3y before)")
    say(f"   picks {len(P)}; with 1y history {sum(x['r1y'] is not None for x in P)}, 2y {sum(x['r2y'] is not None for x in P)}, 3y {sum(x['r3y'] is not None for x in P)}")
    for r, f in RULES.items():
        sel = [x for x in P if f(x)]
        say(f"   {r}: {len(sel)} picks")
    m = lambda v: f"Rs{1e5*st.mean(v):,.0f}" if v else "-"
    for c, f in CB.items():
        sel = [x for x in P if f(x)]
        say(f"\n   {c}: {len(sel)} buys, base {m([x['p36'] for x in sel])}/1L (stop -20%, 36m)")
        for r, g in RULES.items():
            out = [x for x in sel if g(x)]; kept = [x for x in sel if not g(x)]
            if not out: continue
            say(f"      skip {r:11s}: drops {len(out):2d} (they made {m([x['p36'] for x in out])}) -> kept {len(kept)} make {m([x['p36'] for x in kept])}"
                + ((" | " + ", ".join("%s %s %+.0f%%" % (x["label"][:14], str(x["year"])[2:], 100 * x["p36"]) for x in out))[:220] if len(out) <= 8 else ""))
    say("\n   ALL picks by period, median 36m excess vs SC: ran-up vs rest")
    for r in ("1y>=3x", "2y>=5x", "3y-low>=5x", "3y-low>=10x"):
        cells = []
        for sp in ("train", "valid", "hold"):
            a = [x["ex36"] for x in P if x["split"] == sp and RULES[r](x)]; b = [x["ex36"] for x in P if x["split"] == sp and not RULES[r](x)]
            cells.append(f"{sp} {100*st.median(a):+.0f}%(n{len(a)}) vs {100*st.median(b):+.0f}%" if a else f"{sp} n0")
        say(f"   {r:11s}: " + " | ".join(cells))
    sys.exit(0)

QRULE = None
if len(sys.argv) > 3 and sys.argv[2] == "deep" and sys.argv[3].startswith("quick"):
    # deep quick T M: sell everything at +T% or a -20% close, else after M months
    QRULE = dict(stop=0.20, target=1 + float(sys.argv[4]) / 100, maxd=int(float(sys.argv[5]) * 30.4))
if len(sys.argv) > 2 and sys.argv[2] == "deep":
    import itertools, random, re
    up = lambda v: v is not None and v > 0
    keep = lambda v: v is not None and v >= 0
    for x in P:
        q = x["p"]
        x["mgmt"] = fnum(q.get("mgmt_target_x")); x["prom_buy"] = fnum(q.get("promoter_net_cr")); x["inst_buy"] = fnum(q.get("inst_net_cr"))
        x["ob"] = fnum(q.get("order_book.order_book_cr")); x["ob_yoy"] = fnum(q.get("order_book.book_yoy_pct"))
        x["in_yoy"] = fnum(q.get("order_book.inflow_yoy_pct"))
        oc = fnum(q.get("order_cr")); x["rev"] = oc * 100 / x["size"] if oc and x["size"] else None
        x["ob_rev"] = x["ob"] / x["rev"] if x["ob"] and x["rev"] else None
        x["prom_pct"] = fnum(q.get("promoter_holding_pct")); x["fii_pct"] = fnum(q.get("fii_holding_pct"))
        x["estimated"] = "estim" in str(q.get("size_basis", "")).lower()
        x["conf"] = str(q.get("confidence", "")).lower()
        x["below_falling"] = "Below falling 200" in str(q.get("signals", ""))
    # extra as-of data straight from the DB (shareholding detail, filings, insider and bulk deals)
    try:
        import psycopg
        c = psycopg.connect("postgresql:///inflection")
        cols = [r[0] for r in c.execute("select column_name from information_schema.columns where table_name='identifier_history'")]
        symcol = "value" if "value" in cols else ("identifier" if "identifier" in cols else cols[2])
        iss = list({x["iss"] for x in P})
        sym = dict(c.execute(f"""select distinct on (s.issuer_id) s.issuer_id::text, h.{symcol} from securities s join identifier_history h using(security_id)
          where s.issuer_id = any(%s::uuid[]) and h.exchange='NSE' and h.kind='SYMBOL' order by s.issuer_id, h.valid_to nulls first""", (iss,)).fetchall())
        pubs = c.execute("""select issuer_id::text, published_at::date, coalesce(original_subcategory, original_category), coalesce(title,'')
          from document_publications where issuer_id = any(%s::uuid[]) and coalesce(original_subcategory, original_category) ~*
          'rating|preferential|warrant|acqui|management control|open offer|capacity|commercial production|buy.?back|bonus|split'""", (iss,)).fetchall()
        bypub = defaultdict(list)
        for i, d, cat, ti in pubs: bypub[i].append((d, cat, ti))
        try: pli = {r[0] for r in c.execute("select distinct issuer_id::text from pli_beneficiaries where issuer_id is not null")}
        except Exception: c.rollback(); pli = set()
        for x in P:
            i, e = x["iss"], x["s"].d[x["k"]]
            s = c.execute("""select period_end, promoter_pct, fii_pct, dii_pct, mf_pct, promoter_pledged_pct from shareholding_patterns
               where issuer_id=%s and coalesce(broadcast_at::date, period_end + 21) < %s order by period_end desc limit 5""", (i, e)).fetchall()
            def chg(k, back):
                if len(s) > back and s[0][k] is not None and s[back][k] is not None: return float(s[0][k] - s[back][k])
            x["dii_y"], x["dii_q"], x["mf_y"], x["mf_q"] = chg(3, 4), chg(3, 1), chg(4, 4), chg(4, 1)
            x["inst_y"] = (x["dii_y"] or 0) + (x["fii"] or 0) if x["dii_y"] is not None and x["fii"] is not None else None
            x["mf_pct"] = float(s[0][4]) if s and s[0][4] is not None else None
            x["pledge"] = float(s[0][5]) if s and s[0][5] is not None else None
            x["pledge_chg"] = chg(5, 4)
            def has(pat, days, tpat=None):
                return any(e - timedelta(days=days) <= d < e and re.search(pat, cat, re.I) and (not tpat or re.search(tpat, ti, re.I)) for d, cat, ti in bypub[i])
            x["pref"] = has("preferential|warrant", 365); x["rating_up"] = has("rating", 365, "upgrad")
            x["rating_dn"] = has("rating", 365, "downgrad|negative|not cooperating"); x["control"] = has("management control|open offer", 365)
            x["acq"] = has("acqui", 365); x["capacity"] = has("capacity|commercial production", 365); x["buyback"] = has("buy.?back", 365)
            x["bonus"] = has("bonus|split", 365); x["pli"] = i in pli
            sy = sym.get(i)
            x["ins_buy"] = x["bulk"] = None
            if sy:
                v = c.execute("""select sum(case when transaction_type ilike 'buy%%' then value_inr else -value_inr end) from insider_trades
                  where symbol=%s and person_category ilike 'promoter%%' and trade_to between %s and %s""", (sy, e - timedelta(days=182), e)).fetchone()[0]
                x["ins_buy"] = float(v) / 1e7 if v is not None else 0.0
                v = c.execute("""select sum(case when side ilike 'b%%' then quantity*price else -quantity*price end) from bulk_block_deals
                  where symbol=%s and trade_date between %s and %s""", (sy, e - timedelta(days=182), e)).fetchone()[0]
                x["bulk"] = float(v) / 1e7 if v is not None else None
        say("db features: ok")
    except Exception as err:
        say("db features failed:", repr(err)[:200])
    G = lambda k: (lambda x: x.get(k))
    def thr(k, op, v): return lambda x: (x.get(k) is not None) and (x[k] >= v if op == ">=" else (x[k] > v if op == ">" else x[k] < v))
    COND = {}
    for v in (25, 50, 100, 200, 300, 500): COND[f"order>={v}%rev"] = thr("size", ">=", v)
    for v in (0.25, 0.5, 1.0, 2.0): COND[f"order>={int(v*100)}%mcap"] = thr("o_mc", ">=", v)
    for v in (50, 100, 200, 300): COND[f"12m orders>={v}%rev"] = thr("o12", ">=", v)
    for v in (25, 50, 100): COND[f"yr1 exec>={v}%rev"] = thr("oy1", ">=", v)
    for v in (1, 2, 3): COND[f"order book>={v}x rev"] = thr("ob_rev", ">=", v)
    for v in (0, 30, 50, 100): COND[f"order book +{v}% yoy"] = thr("ob_yoy", ">", v)
    COND["order inflow +30% yoy"] = thr("in_yoy", ">", 30)
    for v in (500, 2000, 5000): COND[f"mcap<{v}cr"] = thr("mcap", "<", v)
    COND["mcap>=2000cr"] = thr("mcap", ">=", 2000); COND["mcap>=10000cr"] = thr("mcap", ">=", 10000)
    for v in (0.75, 1.5, 3): COND[f"P/S<{v}"] = thr("ps", "<", v)
    COND["P/S>=3"] = thr("ps", ">=", 3)
    COND["OPM<10%"] = thr("opm", "<", 0.10); COND["OPM>=15%"] = thr("opm", ">=", 0.15); COND["OPM rising"] = thr("opm_chg", ">", 0.01)
    COND["rev growing"] = thr("revg", ">", 0)
    COND["routine order"] = lambda x: x["routine"]; COND["not routine"] = lambda x: not x["routine"]
    COND["stated (not estimated) size"] = lambda x: not x["estimated"]
    for v in (0, 0.5, 1, 2, 5): COND[f"FII +{v}pp yoy" if v else "FII up yoy"] = thr("fii", ">", v) if v == 0 else thr("fii", ">=", v)
    for v in (0, 0.5, 1, 2): COND[f"FII +{v}pp qoq" if v else "FII up qoq"] = thr("fii_q", ">", v) if v == 0 else thr("fii_q", ">=", v)
    COND["FII holding<2%"] = thr("fii_pct", "<", 2); COND["FII holding>=5%"] = thr("fii_pct", ">=", 5)
    COND["promoter not cut yoy"] = thr("prom", ">=", 0); COND["promoter not cut qoq"] = thr("prom_q", ">=", 0)
    for v in (0, 1, 5, 10): COND[f"promoter +{v}pp yoy" if v else "promoter up yoy"] = thr("prom", ">", v) if v == 0 else thr("prom", ">=", v)
    COND["promoter holding>=60%"] = thr("prom_pct", ">=", 60); COND["promoter holding>=70%"] = thr("prom_pct", ">=", 70)
    COND["promoter holding<50%"] = thr("prom_pct", "<", 50)
    COND["DII up yoy"] = thr("dii_y", ">", 0); COND["DII up qoq"] = thr("dii_q", ">", 0)
    COND["MF up yoy"] = thr("mf_y", ">", 0); COND["MF up qoq"] = thr("mf_q", ">", 0); COND["MF holding>=2%"] = thr("mf_pct", ">=", 2)
    COND["FII+DII up yoy"] = thr("inst_y", ">", 0); COND["FII+DII +2pp yoy"] = thr("inst_y", ">=", 2)
    COND["no pledge"] = lambda x: x.get("pledge") is not None and x["pledge"] <= 0
    COND["pledge falling"] = thr("pledge_chg", "<", 0)
    COND["promoter bought (insider, 6m)"] = thr("ins_buy", ">=", 1); COND["bulk deals net buy 6m"] = thr("bulk", ">=", 1)
    COND["bulk deals net sell 6m"] = thr("bulk", "<", -1)
    for k, lab in (("pref", "pref issue/warrants 12m"), ("rating_up", "rating upgrade 12m"), ("rating_dn", "rating downgrade 12m"),
                   ("control", "change of control 12m"), ("acq", "acquisition 12m"), ("capacity", "capacity addition 12m"),
                   ("buyback", "buyback 12m"), ("bonus", "bonus/split 12m"), ("pli", "PLI beneficiary")):
        COND[lab] = (lambda kk: (lambda x: bool(x.get(kk))))(k)
    COND["mgmt target>=1.5x rev"] = thr("mgmt", ">=", 1.5)
    COND["uptrend 2/3"] = lambda x: x["t3"] >= 2; COND["uptrend 3/3"] = lambda x: x["t3"] == 3
    COND["above rising 200DMA"] = lambda x: x["t_up"]; COND["near 52w high"] = lambda x: x["t_hi"]; COND["beats index 6m"] = lambda x: x["t_rs"]
    COND["6m run-up>30%"] = thr("runup6", ">", 0.30); COND["6m run-up>60%"] = thr("runup6", ">", 0.60); COND["6m run-up<0"] = thr("runup6", "<", 0)
    COND["liquid>=0.5cr/day"] = thr("liq", ">=", 0.5); COND["liquid>=2cr/day"] = thr("liq", ">=", 2)
    COND["score>=3"] = thr("score", ">=", 3); COND["score>=4"] = thr("score", ">=", 4); COND["score>=5"] = thr("score", ">=", 5)
    names = list(COND)
    for x in P:
        o = outcome(x, QRULE or dict(stop=0.20)); x["ex"] = o["ex"]
        x["p36"] = outcome(x, QRULE or dict(stop=0.20, maxd=1095))["mult"] - 1
        if QRULE:  # quick mode: did it reach the target within the window, and how many days did it take
            ev, op = sim(x, **QRULE); k1 = ev[-1][0]
            x["qhit"] = x["s"].p[k1] >= x["s"].p[x["k"]] * QRULE["target"]; x["qdays"] = (x["s"].d[k1] - x["s"].d[x["k"]]).days
    mask = {}
    for cnd in names:
        try: mask[cnd] = sum(1 << i for i, x in enumerate(P) if COND[cnd](x))
        except Exception: mask[cnd] = 0
    if len(sys.argv) > 3 and sys.argv[3] == "rare":
        def hold(x, days):
            s = x["s"]; k0 = x["k"]; t1 = s.d[k0] + timedelta(days=days)
            if t1 > s.d[-1]: return None
            return s.p[s.at(t1)] / s.p[k0] - 1 - COST
        extra = {"order>=200%rev + FII up qoq": lambda x: COND["order>=200%rev"](x) and COND["FII up qoq"](x),
                 "order>=200%rev + uptrend 2/3": lambda x: COND["order>=200%rev"](x) and x["t3"] >= 2,
                 "order>=300%rev + uptrend 2/3": lambda x: COND["order>=300%rev"](x) and x["t3"] >= 2}
        rare = [cnd for cnd in names if bin(mask[cnd]).count("1") < 12] + list(extra)
        say("## 16. Rare data points: every pick, returns (12m/24m/36m buy-and-hold) and Rs1L profit with stop -20%, sell 36m")
        for cnd in rare:
            f = extra.get(cnd) or COND[cnd]
            sel = [x for x in P if f(x)]
            if not sel: say(f"   {cnd}: 0 picks"); continue
            cells = []
            for d in (365, 730, 1095):
                h = [v for v in (hold(x, d) for x in sel) if v is not None]
                cells.append(f"{100*st.mean(h):+.0f}%({100*st.median(h):+.0f}%) n{len(h)}" if h else "-")
            say(f"   {cnd} | {len(sel)} picks | Rs{1e5*st.mean(x['p36'] for x in sel):,.0f}/1L | " + " | ".join(cells))
            say("      " + ", ".join(f"{x['label']} {str(x['year'])[2:]} {100*x['p36']:+.0f}%" for x in sel)[:300])
        sys.exit(0)
    names = [cnd for cnd in names if bin(mask[cnd]).count("1") >= 8]
    SPL = {s: sum(1 << i for i, x in enumerate(P) if x["split"] == s) for s in ("train", "valid", "hold")}
    def idx(b):
        out = []
        while b:
            l = b & -b; out.append(l.bit_length() - 1); b ^= l
        return out
    def med(b, ex):
        ii = idx(b)
        if not ii: return 0, None, None
        e = [ex[i] for i in ii]; return len(ii), st.median(e), sum(v > 0 for v in e) / len(e)
    EX = [x["ex"] for x in P]
    say(f"\n## 14. Deep search: {len(names)} conditions with >=8 picks (dropped {len(COND)-len(names)} too rare)")
    say("   rare / dropped: " + ", ".join(f"{k}({bin(mask.get(k,0)).count('1')})" for k in COND if k not in names)[:400])
    combos = [(a,) for a in names] + list(itertools.combinations(names, 2)) + list(itertools.combinations(names, 3))
    def run(ex):
        out, seen = [], set()
        for cb in combos:
            b = -1
            for a in cb: b &= mask[a]
            if b == 0 or b in seen: continue
            seen.add(b)
            n1, m1, w1 = med(b & SPL["train"], ex)
            if n1 < 10 or m1 <= 0 or w1 < 0.55: continue
            n2, m2, _ = med(b & SPL["valid"], ex)
            if n2 < 4 or m2 <= 0: continue
            n3, m3, _ = med(b & SPL["hold"], ex)
            if n3 < 5 or m3 <= 0: continue
            out.append((cb, b, (n1, m1), (n2, m2), (n3, m3)))
        return out
    real = run(EX)
    random.seed(11); fake = []
    for _ in range(5):
        ex2 = EX[:]
        for s in SPL:
            ii = idx(SPL[s]); vals = [ex2[i] for i in ii]; random.shuffle(vals)
            for i, v in zip(ii, vals): ex2[i] = v
        fake.append(len(run(ex2)))
    say(f"   combos tested {len(combos)}; beat the index in ALL THREE periods: {len(real)}; with shuffled returns (luck): {fake}")
    def hold(x, days):
        s = x["s"]; k0 = x["k"]; t1 = s.d[k0] + timedelta(days=days)
        if t1 > s.d[-1]: return None
        return s.p[s.at(t1)] / s.p[k0] - 1 - COST
    rows = []
    for cb, b, a1, a2, a3 in real:
        sel = [P[i] for i in idx(b)]
        rows.append((st.mean(x["p36"] for x in sel), cb, b, a1, a2, a3, sel))
    rows.sort(key=lambda r: -r[0])
    say("\n## 15. Top 30 distinct all-period combos, ranked by avg profit per Rs1L " + (f"(QUICK: {QRULE})" if QRULE else "(stop -20%, hold up to 36m)"))
    if QRULE: say(f"   ALL picks: {len(P)} | Rs{1e5*st.mean(x['p36'] for x in P):,.0f} | hit {100*sum(x['qhit'] for x in P)/len(P):.0f}%")
    say("   combo | buys | profit/1L 36m | 12m avg(med) | 24m avg(med) | 36m avg(med) | med vs SC 21-23/24/25-26 (n)")
    shown = []
    for p36, cb, b, a1, a2, a3, sel in rows:
        if any(bin(b & s2).count("1") / bin(b | s2).count("1") >= 0.6 for s2 in shown): continue
        shown.append(b)
        cells = []
        for d in (365, 730, 1095):
            h = [v for v in (hold(x, d) for x in sel) if v is not None]
            cells.append(f"{100*st.mean(h):+.0f}%({100*st.median(h):+.0f}%) n{len(h)}" if h else "-")
        if QRULE: cells = [f"hit {100*sum(x['qhit'] for x in sel)/len(sel):.0f}% in med {st.median([x['qdays'] for x in sel if x['qhit']] or [0]):.0f}d"]
        say(f"   {' + '.join(cb)[:70]:70s} | {len(sel):2d} | Rs{1e5*p36:,.0f} | " + " | ".join(cells)
            + f" | {100*a1[1]:+.0f}%({a1[0]}) {100*a2[1]:+.0f}%({a2[0]}) {100*a3[1]:+.0f}%({a3[0]})")
        if len(shown) >= 30: break
    sys.exit(0)

if len(sys.argv) > 2 and sys.argv[2] == "menu":
    for x in P:
        q = x["p"]; x["mgmt"] = fnum(q.get("mgmt_target_x"))
    up = lambda v: v is not None and v > 0
    keep = lambda v: v is not None and v >= 0
    T = lambda x: x["t3"] >= 2
    M = {
        "M1 FII up YoY + promoter up YoY": lambda x: up(x["fii"]) and up(x["prom"]),
        "M2 FII up YoY + promoter not cut YoY": lambda x: up(x["fii"]) and keep(x["prom"]),
        "M3 M2 + tech>=2/3": lambda x: up(x["fii"]) and keep(x["prom"]) and T(x),
        "M4 order>=100%rev + FII up YoY": lambda x: ge(x["size"], 100) and up(x["fii"]),
        "M5 score>=4 + FII up YoY + prom not cut": lambda x: ge(x["score"], 4) and up(x["fii"]) and keep(x["prom"]),
        "M6 P/S<1.5 + mcap<2000 + FII up YoY": lambda x: lt(x["ps"], 1.5) and lt(x["mcap"], 2000) and up(x["fii"]),
        "M7 FII up QoQ + promoter not cut QoQ": lambda x: up(x["fii_q"]) and keep(x["prom_q"]),
        "M8 M7 + tech>=2/3": lambda x: up(x["fii_q"]) and keep(x["prom_q"]) and T(x),
        "M9 order>=25%rev + FII up QoQ + tech": lambda x: ge(x["size"], 25) and up(x["fii_q"]) and T(x),
        "M10 order>=50% + 12m orders>=50% + tech": lambda x: ge(x["size"], 50) and ge(x["o12"], 50) and T(x),
        "M11 order>=100%rev + tech + liquid": lambda x: ge(x["size"], 100) and T(x) and ge(x["liq"], 0.5),
        "M12 mcap>=2000 + FII up QoQ + tech": lambda x: ge(x["mcap"], 2000) and up(x["fii_q"]) and T(x),
        "M13 order>=25%rev + OPM<10% + tech": lambda x: ge(x["size"], 25) and lt(x["opm"], 0.10) and T(x),
        "M14 FII up YoY (alone)": lambda x: up(x["fii"]),
        "M15 FII up QoQ (alone)": lambda x: up(x["fii_q"]),
        "M00 all picks": lambda x: True,
    }
    def hold(x, days):
        s = x["s"]; k0 = x["k"]; t1 = s.d[k0] + timedelta(days=days)
        if t1 > s.d[-1]: return None
        k1 = s.at(t1); p = s.p[k1] / s.p[k0] - 1 - COST
        return p, p - (sc(s.d[k1]) / sc(s.d[k0]) - 1)
    say("## 13. Menu. Buy-and-hold returns (only picks old enough), avg / median, positive share; then Rs1L each with stop -20%")
    say("   combo | n | 12m avg med pos | 24m avg med beatSC | 36m avg med beatSC | Rs1L stop-20%: sell 24m avg profit | sell 36m avg profit | 24m median vs SC by period")
    for name, f in M.items():
        sel = [x for x in P if f(x)]
        cells = []
        for d in (365, 730, 1095):
            h = [hold(x, d) for x in sel]; h = [v for v in h if v]
            if not h: cells.append(" n=0"); continue
            r = [a for a, _ in h]; e = [b for _, b in h]
            third = f"{sum(v > 0 for v in r)}/{len(r)} up" if d == 365 else f"{100*sum(v>0 for v in e)/len(e):.0f}% beat"
            cells.append(f"n{len(r)} {100*st.mean(r):+.0f}% {100*st.median(r):+.0f}% {third}")
        p24 = [outcome(x, dict(stop=0.20))["mult"] - 1 for x in sel]
        p36 = [outcome(x, dict(stop=0.20, maxd=1095))["mult"] - 1 for x in sel]
        per = []
        for sp in ("train", "valid", "hold"):
            e = [outcome(x, dict(stop=0.20))["ex"] for x in sel if x["split"] == sp]
            per.append(f"{100*st.median(e):+.0f}%({len(e)})" if e else "-")
        say(f"   {name[:40]:40s} | {len(sel):3d} | " + " | ".join(cells)
            + (f" | Rs{1e5*st.mean(p24):,.0f} | Rs{1e5*st.mean(p36):,.0f} | " if sel else " | - | - | ") + " ".join(per))
    sys.exit(0)

if len(sys.argv) > 2 and sys.argv[2] == "search":
    import itertools, random
    RULE = dict(stop=0.20)  # stop -20% on close, else sell at 24m (validated earlier)
    for x in P:
        o = outcome(x, RULE); x["ret"], x["ex"], x["open"] = o["mult"] - 1, o["ex"], o["open"]
        q = x["p"]
        x["ob_yoy"] = fnum(q.get("order_book.book_yoy_pct")); x["inflow_yoy"] = fnum(q.get("order_book.inflow_yoy_pct"))
        x["mgmt"] = fnum(q.get("mgmt_target_x")); x["prom_buy"] = fnum(q.get("promoter_net_cr")); x["inst_buy"] = fnum(q.get("inst_net_cr"))
    pct = max((abs(x["revg"]) for x in P if x["revg"] is not None), default=0) > 5   # revg in % or fraction
    g = lambda v: v / 100 if (v is not None and pct) else v
    o_pct = max((abs(x["opm"]) for x in P if x["opm"] is not None), default=0) > 2
    m = lambda v: v / 100 if (v is not None and o_pct) else v
    COND = {
        "order>=25%rev": lambda x: ge(x["size"], 25), "order>=50%rev": lambda x: ge(x["size"], 50),
        "order>=100%rev": lambda x: ge(x["size"], 100), "order>=200%rev": lambda x: ge(x["size"], 200),
        "order>=25%mcap": lambda x: ge(x["o_mc"], 0.25), "order>=50%mcap": lambda x: ge(x["o_mc"], 0.5),
        "order>=100%mcap": lambda x: ge(x["o_mc"], 1.0),
        "12m orders>=50%rev": lambda x: ge(x["o12"], 50), "12m orders>=100%rev": lambda x: ge(x["o12"], 100),
        "yr1 exec>=25%rev": lambda x: ge(x["oy1"], 25), "yr1 exec>=50%rev": lambda x: ge(x["oy1"], 50),
        "order book growing": lambda x: gt(x["ob_yoy"], 0) or gt(x["inflow_yoy"], 0),
        "order book +30%": lambda x: ge(x["ob_yoy"], 30) or ge(x["inflow_yoy"], 30),
        "mcap<500cr": lambda x: lt(x["mcap"], 500), "mcap<2000cr": lambda x: lt(x["mcap"], 2000),
        "mcap<5000cr": lambda x: lt(x["mcap"], 5000), "mcap>=2000cr": lambda x: ge(x["mcap"], 2000),
        "P/S<0.75": lambda x: lt(x["ps"], 0.75), "P/S<1.5": lambda x: lt(x["ps"], 1.5), "P/S<3": lambda x: lt(x["ps"], 3),
        "P/S>=3": lambda x: ge(x["ps"], 3),
        "OPM<10%": lambda x: lt(m(x["opm"]), 0.10), "OPM>=15%": lambda x: ge(m(x["opm"]), 0.15), "loss-making": lambda x: lt(m(x["opm"]), 0),
        "OPM rising": lambda x: gt(m(x["opm_chg"]), 0.01),
        "rev growing": lambda x: gt(x["revg"], 0), "rev growth>20%": lambda x: gt(g(x["revg"]), 0.20),
        "firm order": lambda x: x["firm"], "routine order": lambda x: x["routine"], "not routine": lambda x: not x["routine"],
        "FII up YoY": lambda x: gt(x["fii"], 0), "FII up QoQ": lambda x: gt(x["fii_q"], 0),
        "promoter not cut YoY": lambda x: ge(x["prom"], 0), "promoter up YoY": lambda x: gt(x["prom"], 0),
        "promoter not cut QoQ": lambda x: ge(x["prom_q"], 0),
        "promoter bought": lambda x: ge(x["prom_buy"], 1), "institutions bought": lambda x: ge(x["inst_buy"], 1),
        "mgmt target>=1.5x rev": lambda x: ge(x["mgmt"], 1.5),
        "tech>=2/3": lambda x: x["t3"] >= 2, "tech 3/3": lambda x: x["t3"] == 3,
        "6m run-up>30%": lambda x: gt(x["runup6"], 0.30), "6m run-up<0": lambda x: lt(x["runup6"], 0),
        "liquid>=0.5cr/day": lambda x: ge(x["liq"], 0.5), "liquid>=2cr/day": lambda x: ge(x["liq"], 2),
        "score>=3": lambda x: ge(x["score"], 3), "score>=4": lambda x: ge(x["score"], 4),
    }
    names = list(COND)
    mask = {c: sum(1 << i for i, x in enumerate(P) if COND[c](x)) for c in names}
    SPL = {s: sum(1 << i for i, x in enumerate(P) if x["split"] == s) for s in ("train", "valid", "hold")}
    def idx(b):
        out = []
        while b:
            l = b & -b; out.append(l.bit_length() - 1); b ^= l
        return out
    def stats(b, ex):
        ii = idx(b)
        if not ii: return None
        e = [ex[i] for i in ii]; r = [P[i]["ret"] for i in ii]
        return dict(n=len(ii), mex=st.median(e), beat=sum(v > 0 for v in e) / len(e), mret=st.median(r), avg=st.mean(r),
                    worst=min(r))
    EX = [x["ex"] for x in P]
    say(f"conditions {len(names)}; revg in % = {pct}; OPM in % = {o_pct}")
    say("\n## 9. Single conditions (stop -20% else 24m). n / median vs SC / beat% for train<=2023 | 2024 | 2025-26")
    for c in names:
        cells = []
        for s in ("train", "valid", "hold"):
            z = stats(mask[c] & SPL[s], EX)
            cells.append(f"{z['n']:3d} {100*z['mex']:+4.0f}% {100*z['beat']:3.0f}%" if z else "  0")
        say(f"   {c:22s} " + " | ".join(cells))
    combos = [(c,) for c in names] + list(itertools.combinations(names, 2)) + list(itertools.combinations(names, 3))
    def run(ex):
        found, seen_b = [], set()
        for cb in combos:  # shortest combos first, so a longer one picking the same stocks is skipped
            b = -1
            for c in cb: b &= mask[c]
            if b == 0 or b in seen_b: continue
            seen_b.add(b)
            tr = stats(b & SPL["train"], ex)
            if not tr or tr["n"] < 10 or tr["mex"] <= 0 or tr["beat"] < 0.55: continue
            va = stats(b & SPL["valid"], ex)
            if not va or va["n"] < 4 or va["mex"] <= 0: continue
            found.append((min(tr["mex"], va["mex"]), cb, tr, va, b))
        found.sort(key=lambda f: -f[0])
        return found
    found = run(EX)
    say(f"\n## 10. Combos of 1-3 conditions tested: {len(combos)}. Passing train (n>=10, median beats index, >=55% beat) AND 2024 (n>=4, median beats index): {len(found)}")
    random.seed(7)
    fake = []
    for _ in range(10):  # chance baseline: shuffle returns within each split, rerun the same search
        ex2 = EX[:]
        for s in SPL:
            ii = idx(SPL[s]); vals = [ex2[i] for i in ii]; random.shuffle(vals)
            for i, v in zip(ii, vals): ex2[i] = v
        f2 = run(ex2)
        hp = [stats(f[4] & SPL["hold"], ex2) for f in f2[:25]]
        fake.append((len(f2), sum(1 for h in hp if h and h["mex"] > 0) / max(1, len(hp))))
    say("   by chance (returns shuffled, 10 runs): passing combos " + ", ".join(str(a) for a, _ in fake)
        + " | share of top-25 also beating index in 2025-26: " + ", ".join(f"{100*b:.0f}%" for _, b in fake))
    say("\n## 11. Top 40 passing combos, ranked on train+2024 only; 2025-26 shown as the untouched test")
    say("   combo | train n med beat | 2024 n med beat | 2025-26 n med beat avg-return | picks/yr")
    seen = 0
    for sc_, cb, tr, va, b in found[:40]:
        ho = stats(b & SPL["hold"], EX)
        per = len(idx(b)) / 5.8
        hs = f"{ho['n']:3d} {100*ho['mex']:+4.0f}% {100*ho['beat']:3.0f}% avg {100*ho['avg']:+4.0f}%" if ho else "  0"
        say(f"   {' + '.join(cb)[:62]:62s} | {tr['n']:3d} {100*tr['mex']:+4.0f}% {100*tr['beat']:3.0f}% | {va['n']:3d} {100*va['mex']:+4.0f}% {100*va['beat']:3.0f}% | {hs} | {per:.0f}")
    ok = [(f, stats(f[4] & SPL["hold"], EX)) for f in found]
    ok = [(f, h) for f, h in ok if h and h["n"] >= 5 and h["mex"] > 0]
    say(f"\n## 12. Of the {len(found)} passing combos, {len(ok)} also beat the index in 2025-26 (n>=5). Top 15 by worst-of-three median:")
    ok.sort(key=lambda fh: -min(fh[0][2]["mex"], fh[0][3]["mex"], fh[1]["mex"]))
    for f, h in ok[:15]:
        _, cb, tr, va, b = f
        allr = [P[i]["ret"] for i in idx(b)]
        say(f"   {' + '.join(cb)[:62]:62s} | {tr['n']} {100*tr['mex']:+.0f}% | {va['n']} {100*va['mex']:+.0f}% | {h['n']} {100*h['mex']:+.0f}% | "
            f"Rs1L each: {len(allr)} buys, avg profit Rs{1e5*st.mean(allr):,.0f}, win {100*sum(r>0 for r in allr)/len(allr):.0f}%")
        say("      " + ", ".join(f"{P[i]['label']} {str(P[i]['year'])[2:]}" for i in idx(b))[:240])
    with open(os.path.join(DIR, "combo_search.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["combo", "train_n", "train_med_ex", "valid_n", "valid_med_ex", "hold_n", "hold_med_ex"])
        for sc_, cb, tr, va, b in found:
            ho = stats(b & SPL["hold"], EX)
            w.writerow([" + ".join(cb), tr["n"], round(tr["mex"], 3), va["n"], round(va["mex"], 3), ho["n"] if ho else 0, round(ho["mex"], 3) if ho else ""])
    sys.exit(0)

if len(sys.argv) > 2 and sys.argv[2] == "combo":
    say("holding columns:", [c for c in picks[0] if "change" in c or "fii" in c.lower() or "promoter" in c.lower()][:12])
    say("promoter+FII YoY known by year:", {y: sum(1 for x in P if x["year"] == y and x["prom"] is not None and x["fii"] is not None) for y in range(2021, 2027)})
    up = lambda v: v is not None and v > 0
    keep = lambda v: v is not None and v >= 0
    T2 = lambda x: (x["tech"] if x["tech"] is not None else x["t3"]) >= 2
    C = {
        "C0 all picks": lambda x: True,
        "C1 promoter up + FII up": lambda x: up(x["prom"]) and up(x["fii"]),
        "C2 FII up + promoter not reduced": lambda x: up(x["fii"]) and keep(x["prom"]),
        "C3 C2 + technicals >=2/3": lambda x: up(x["fii"]) and keep(x["prom"]) and T2(x),
        "C4 order >=100% rev + FII up": lambda x: ge(x["size"], 100) and up(x["fii"]),
        "C5 score>=4 + FII up + promoter not reduced": lambda x: ge(x["score"], 4) and up(x["fii"]) and keep(x["prom"]),
        "C6 P/S<1.5 + mcap<2000 + FII up": lambda x: lt(x["ps"], 1.5) and lt(x["mcap"], 2000) and up(x["fii"]),
        "C7 FII up (alone)": lambda x: up(x["fii"]),
        "C8 FII down or flat (known)": lambda x: x["fii"] is not None and not up(x["fii"]),
        "C9 C2 + technicals own t3>=2": lambda x: up(x["fii"]) and keep(x["prom"]) and x["t3"] >= 2,
        "C10 C2 using quarter-on-quarter change": lambda x: up(x["fii_q"]) and keep(x["prom_q"]),
    }
    say("\n## 6. Combos per pick (splits: train<=2023, valid 2024, hold 2025-26). exit hold 12m / 24m")
    for name, f in C.items():
        say(name)
        for lab, rule in (("12m", EXITS["E1 hold 12m"]), ("24m", EXITS["E2 hold 24m"])):
            for sp in ("train", "valid", "hold"):
                rows = [outcome(x, rule) for x in P if x["split"] == sp and f(x)]
                say(f"   {lab} {sp:5s} {summarise(rows)}")
        yrs = defaultdict(list)
        for x in P:
            if f(x): yrs[x["year"]].append(outcome(x, EXITS["E1 hold 12m"]))
        say("   12m by year (n, median vs SC, closed only): " + "  ".join(
            f"{y}:{len([r for r in v if not r['open']])},{100*st.median([r['ex'] for r in v if not r['open']]):+.0f}%" if any(not r['open'] for r in v) else f"{y}:0"
            for y, v in sorted(yrs.items())))
        if not name.startswith(("C0", "C7", "C8")):
            say("   names: " + ", ".join(f"{x['label']} {str(x['year'])[2:]}" for x in P if f(x))[:300])
    say("\n## 7. Exit rules on combos (per pick, all years)")
    ER = {"hold 24m": dict(maxd=730), "stop -15% else 24m": dict(stop=0.15), "stop -20% else 24m": dict(stop=0.20),
          "stop -25% else 24m": dict(stop=0.25), "stop -20% else 36m": dict(stop=0.20, maxd=1095),
          "stop -20%, half at 2x, trail 30%, 36m": dict(stop=0.20, half=2.0, trail=0.30, arm=1.0, maxd=1095),
          "stop -20% until +50%, trail 30%, 36m": dict(stop=0.20, trail=0.30, arm=0.50, maxd=1095),
          "trail 30% from peak, 36m": dict(trail=0.30, maxd=1095)}
    for cname in ("C2 FII up + promoter not reduced", "C3 C2 + technicals >=2/3", "C1 promoter up + FII up", "C4 order >=100% rev + FII up"):
        say(cname)
        for en, rule in ER.items():
            say(f"   {en:38s} train+valid {summarise([outcome(x, rule) for x in P if x['split'] != 'hold' and C[cname](x)])}")
            say(f"   {'':38s} hold        {summarise([outcome(x, rule) for x in P if x['split'] == 'hold' and C[cname](x)])}")
    say("\n## 8. Portfolio on combos")
    for start, lab in ((date(2022, 1, 1), "2022-now"), (date(2024, 1, 1), "2024-now"), (date(2025, 1, 1), "2025-now")):
        for cname in ("C0 all picks", "C2 FII up + promoter not reduced", "C3 C2 + technicals >=2/3", "C1 promoter up + FII up", "C4 order >=100% rev + FII up", "C7 FII up (alone)"):
            for size, mx in ((0.05, 20), (0.10, 10)):
                for en in ("stop -20% else 24m", "stop -20%, half at 2x, trail 30%, 36m"):
                    say(f"   {lab} {cname[:32]:32s} {int(size*100):2d}%x{mx:2d} {en[:26]:26s} {portfolio(C[cname], ER[en], start, size, mx)}")
    sys.exit(0)
# ---------- 1. selection (hold 24m) ----------
say("\n## 1. Selection rules, exit = hold 24m (2025-26 mostly still open)")
base = EXITS["E2 hold 24m"]
for name, f in SEL.items():
    say(name)
    for sp in ("train", "valid", "hold"):
        rows = [outcome(x, base) for x in P if x["split"] == sp and f(x)]
        say(f"   {sp:5s} {summarise(rows)}")

say("\n## 1b. Same, exit = hold 12m, train / valid / holdout medians vs SC")
for name, f in SEL.items():
    cells = []
    for sp in ("train", "valid", "hold"):
        rows = [outcome(x, EXITS['E1 hold 12m']) for x in P if x["split"] == sp and f(x)]
        cells.append(f"{sp} n={len(rows)} {100*st.median([r['ex'] for r in rows]):+.0f}%" if rows else f"{sp} n=0")
    say(f"   {name:45s} " + " | ".join(cells))

# ---------- 2. exits on S0 and S1 ----------
for sname in ("S0 all picks", "S1 firm + revenue growing", "S5 S1 + cheap or thin (P/S<1.5 or OPM<10%)"):
    say(f"\n## 2. Exit rules on {sname}")
    f = SEL[sname]
    for ename, rule in EXITS.items():
        say(ename)
        for sp in ("train", "valid", "hold"):
            say(f"   {sp:5s} {summarise([outcome(x, rule) for x in P if x['split'] == sp and f(x)])}")

# ---------- 3. entry timing ----------
say("\n## 3. Entry timing on S1 (hold 24m): buy Monday after review week (+7d) vs +14d vs wait for close above 50DMA")
f = SEL["S1 firm + revenue growing"]
for x in P:
    s = x["s"]; k = x["k7"]; x["k50"] = None
    for j in range(k, min(len(s.d), k + 60)):
        m = s.sma(j, 50)
        if m and s.p[j] > m and (s.d[j] - s.d[k]).days <= 60: x["k50"] = j; break
for label, entry in (("+7d", "k7"), ("+14d", "k"), ("above 50DMA within 60d", "k50")):
    for sp in ("train", "valid", "hold"):
        rows = [outcome(x, base, entry=entry) for x in P if x["split"] == sp and f(x) and x[entry] is not None]
        skipped = sum(1 for x in P if x["split"] == sp and f(x) and x[entry] is None)
        say(f"   {label:24s} {sp:5s} {summarise(rows)} skipped {skipped}")


say("\n## 4. Portfolio: 5% per stock, max 20, idle cash earns 0")
for start, lab in ((date(2021, 1, 1), "2021-now"), (date(2024, 1, 1), "2024-now"), (date(2025, 1, 1), "2025-now (holdout)")):
    for sname in ("S0 all picks", "S1 firm + revenue growing", "S4 S1 + score>=4", "S5 S1 + cheap or thin (P/S<1.5 or OPM<10%)", "S8 S1 + technicals 2-3/3"):
        for ename in ("E2 hold 24m", "E4 stop -20%, else 24m", "E7 stop -20% until +30%, then trail 25%, max 36m",
                      "E11 stop -25% until 2x; sell half at 2x; trail 30%; 36m", "E12 stop -25% until +50%, then trail 30%, max 36m"):
            say(f"   {lab:18s} {sname[:28]:28s} {ename[:30]:30s} {portfolio(SEL[sname], EXITS[ename], start)}")
say("\n## 4b. Position size check (S1, E12): 10% x 10 vs 5% x 20")
for start in (date(2021, 1, 1), date(2025, 1, 1)):
    for size, mx in ((0.05, 20), (0.10, 10)):
        say(f"   from {start} {int(size*100)}% x {mx}: {portfolio(S1, EXITS['E12 stop -25% until +50%, then trail 30%, max 36m'], start, size, mx)}")

# ---------- trades ----------
with open(os.path.join(DIR, "trades.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["label", "week", "split", "firm", "revg", "ps", "opm", "score", "t3", "o_mc", "liq"] + list(EXITS))
    for x in P:
        w.writerow([x["label"], x["wk"], x["split"], x["firm"], x["revg"], x["ps"], x["opm"], x["score"], x["t3"], x["o_mc"], x["liq"]]
                   + [round(outcome(x, r)["mult"], 3) for r in EXITS.values()])
say("\nwrote trades.csv")
