"""Live lists for the shortlisted long-term momentum strategies (identification only; nothing is ever ordered).

    strategy_lists.py --asof YYYY-MM-DD [--dry]       needs alpha_model/v1_frozen/run_<asof>/ (run_pipeline.py builds it)

Scores come from the frozen v1 model plus the rules in the shortlist (strategies.md, strategy-tweaks/report.md):
  blend   = mean percentile of v1, 12-1 momentum and momentum / 63-day volatility, on the as-of cross-section
  MB4     = mean of (1 - percentile) of opm_level, int_cover, ivol, pat_ttm_cr
  ATH     = a month-end close above all earlier month-ends (24m+ history), old high set more than 12 months before
  P/S     = price-to-sales < 1 and revenue up 20%+ year on year
Each strategy keeps a book in live/books/<key>.json: the month's decision is made once, by the first run of a new month,
from the previous month's holdings. Books start from a replay of the research panel, so the first live month has a
realistic "held" list. Later runs in the same month refresh prices and ranks but do not change the decision.

Writes live/strategies.json for the dashboard. Read-only on the database.
"""
import argparse, json, os, pickle, sys
from collections import defaultdict
from datetime import date, datetime

import numpy as np
import psycopg

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
V1 = f"{J}/alpha_model/v1_frozen"
LIVE = f"{J}/live"
BOOKS = f"{LIVE}/books"
DSN = os.environ.get("INFLECTION_DSN", "postgresql:///inflection")
N, POS_CR, SECTOR_CAP = 20, 0.10, 5          # 20 names, Rs 2 cr book, position at most 10% of ADV20, 5 per statistical sector
SEED_FROM = date(2024, 1, 1)

# Same-engine figures, Jan 2021 - Sep 2026, before tax (strategy-tweaks/report.md, Part 4)
STRATEGIES = {
    "stack_a": dict(name="Stack A (blend + MB4 + ATH + P/S, keep top 10%)", keep=0.10, cagr="+54.2%", since24="+38.8%", dd="-29%",
                    rule="Blend + 0.15 x (MB4 - 0.5) + 0.10 x ATH-after-base (12m) + 0.05 x (P/S<1 and revenue +20%). Top 20 monthly, sell when it leaves the top 10%."),
    "blend": dict(name="Live blend (#1)", keep=0.20, cagr="+43.4%", since24="+24.6%", dd="-32%",
                  rule="Average percentile of v1, 12-1 momentum and volatility-scaled momentum. Top 20 monthly, sell when it leaves the top 20%."),
    "mb4": dict(name="Blend + MB4 tilt (#2)", keep=0.20, cagr="+52.6%", since24="+31.3%", dd="-30%",
                rule="Blend + 0.15 x (MB4 - 0.5), favouring small, thin-margin, steadily climbing companies. Top 20 monthly, keep while in the top 20%."),
    "ath": dict(name="Blend + ATH-after-base (#3)", keep=0.20, cagr="+47.5%", since24="+29.3%", dd="-29%",
                rule="Blend + 0.10 for 12 months after a new all-time month-end high whose old high is over a year old. Top 20 monthly, keep while in the top 20%."),
    "ps": dict(name="Blend + P/S cheap-grower (#5)", keep=0.20, cagr="+44.7%", since24="+23.4%", dd="-32%",
               rule="Blend + 0.05 when P/S is below 1 and revenue is up 20%+ year on year. Top 20 monthly, keep while in the top 20%."),
    "delivery": dict(name="Delivery momentum (#7)", keep=0.20, cagr="+34.0%", since24="+15.9%", dd="-28%",
                     rule="126-day return counted only on days with above-median delivery %. Top 20 monthly, keep while in the top 20%."),
    "super_opps": dict(name="Super-opps long-term hold (#4)", keep=None, cagr="+38.8%", since24="+33.4%", dd="-25%",
                       rule="ATH-after-base in the last 3 months, latest quarter PAT +100%, revenue +30%, SUE 1+, traded Rs 0.5 cr+/day. Buy every new qualifier, sell after 13 months, no stop."),
}
DEFAULT = "stack_a"


def month_key(d):
    return f"{d.year}-{d.month:02d}"


def ym(o):
    d = date.fromordinal(int(o))
    return d.year * 12 + d.month - 1


def ym_key(v):
    return f"{v // 12}-{v % 12 + 1:02d}"


def percentile(v):
    out = np.full(len(v), np.nan)
    idx = np.where(~np.isnan(v))[0]
    if len(idx):
        out[idx] = (np.argsort(np.argsort(v[idx])) + 0.5) / len(idx)
    return out


def scores(col, ens, ath12, dm):
    """Every strategy's score on one month's cross-section. `col` reads a panel column (vol63 and ivol are stored negated)."""
    m12, vol = col("mom_12_1"), -col("vol63")
    with np.errstate(divide="ignore", invalid="ignore"):
        vm = np.where(vol > 0, m12 / vol, np.nan)
    blend = np.nanmean(np.vstack([percentile(ens), percentile(m12), percentile(vm)]), 0)
    mb4 = np.nanmean(np.vstack([1 - percentile(col(c)) for c in ("opm_level", "int_cover", "ivol", "pat_ttm_cr")]), 0)
    psb = (np.nan_to_num(col("ps"), nan=9e9) < 1) & (np.nan_to_num(col("rev_yoy"), nan=-9) >= 0.2)
    mb, at, ps = 0.15 * (mb4 - 0.5), 0.10 * ath12, 0.05 * psb
    return dict(stack_a=blend + mb + at + ps, blend=blend, mb4=blend + mb, ath=blend + at, ps=blend + ps, delivery=percentile(dm)), blend, mb4, psb


def decide(score, adv20, sector, issuers, prev, keep):
    """The simulator's month step: rank the liquid names, keep holdings still in the top `keep`, fill from the top."""
    ok = ~np.isnan(score) & (np.nan_to_num(adv20) * 0.10 >= POS_CR)
    idx = np.where(ok)[0]
    order = idx[np.argsort(-score[idx])]
    rank = {issuers[i]: r for r, i in enumerate(order)}
    row = {issuers[i]: i for i in idx}
    port = [h for h in prev if h in rank and rank[h] < keep * len(idx)]
    per = defaultdict(int)
    for h in port:
        per[sector[row[h]]] += 1
    for i in order:
        if len(port) >= N:
            break
        h = issuers[i]
        if h in port or (sector[i] >= 0 and per[sector[i]] >= SECTOR_CAP):
            continue
        port.append(h)
        per[sector[i]] += 1
    return sorted(port, key=lambda h: rank[h]), rank, len(idx)


def qualifies_super(col, adv20, ath3):
    n = lambda c, fill: np.nan_to_num(col(c), nan=fill)
    return ath3 & (n("pat_q_yoy", -9) >= 1.0) & (n("rev_yoy", -9) >= 0.30) & (n("sue", -9) >= 1.0) & (np.nan_to_num(adv20) >= 0.5)


def roll_super(entries, month, new):
    """entries = [{issuer, month}]; 13-month hold; a stock counts at most once every 6 months."""
    def age(e):
        return (int(month[:4]) * 12 + int(month[5:])) - (int(e["month"][:4]) * 12 + int(e["month"][5:]))
    held = [e for e in entries if age(e) < 13]
    sold = [e for e in entries if age(e) >= 13]
    recent = {e["issuer"] for e in entries if age(e) < 6}
    added = [dict(issuer=h, month=month) for h in new if h not in recent]
    return held + added, sold, added


def seed_books():
    """First run only: replay the research panel so each book has a realistic state for the last research month."""
    Z = np.load(f"{J}/alpha_model/panel.npz")
    meta = pickle.load(open(f"{J}/alpha_model/meta.pkl", "rb"))
    ens = np.load(f"{J}/alpha_model/preds.npz")["ens"]
    F = pickle.load(open(f"{J}/strategy_tweaks/code/feats.pkl", "rb"))
    iss, cols, X, months = meta["issuer"], meta["cols"], Z["X"], Z["month"]
    if len(F["DM"]) != len(iss):
        raise SystemExit("feats.pkl does not line up with the research panel")
    YM = F["YM"]
    ath_rows = lambda back: np.fromiter(((any(YM[i] - k in F["ev"].get(iss[i], ()) for k in range(1, back + 1))) for i in range(len(iss))), bool, len(iss))
    F["ev"] = {h: set(v) for h, v in F["ATHev"].items()}
    a12, a3 = ath_rows(12), ath_rows(3)
    book, entries = {k: [] for k in STRATEGIES if k != "super_opps"}, []
    hist = defaultdict(list)
    for m in sorted(int(x) for x in np.unique(months)):
        if date.fromordinal(m) < SEED_FROM:
            continue
        r = np.where(months == m)[0]
        col = lambda c: X[r, cols.index(c)]
        names = [iss[i] for i in r]
        sc = scores(col, ens[r], a12[r], F["DM"][r])[0]
        mk = month_key(date.fromordinal(m))
        for k in book:
            book[k] = decide(sc[k], Z["adv20"][r], Z["sector"][r], names, book[k], STRATEGIES[k]["keep"])[0]
            hist[k].append(dict(month=mk, holdings=book[k], decided_on="research replay"))
        q = qualifies_super(col, Z["adv20"][r], a3[r])
        entries = roll_super(entries, mk, [names[i] for i in np.where(q)[0]])[0]
        hist["super_opps"].append(dict(month=mk, entries=list(entries), decided_on="research replay"))
    os.makedirs(BOOKS, exist_ok=True)
    for k, v in hist.items():
        write_json(f"{BOOKS}/{k}.json", dict(history=v[-6:]))


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, default=str, allow_nan=False)
    os.replace(tmp, path)


def ath_events(p, oh):
    """Months with an ATH-after-base month-end close, on clean price segments (same logic as the research code)."""
    d = np.asarray(p["d"])
    c = np.asarray(p["c"], float)
    br = np.asarray(list(p["breaks"]) + list(oh.get("unrec", [])), dtype=np.int64)
    yms = np.array([ym(v) for v in d])
    u, st = np.unique(yms, return_index=True)
    en = np.r_[st[1:], len(d)] - 1
    mc, seg, out = c[en], np.zeros(len(u), int), []
    for b in br:
        kb = int(np.searchsorted(d, b))
        seg[np.searchsorted(u, yms[min(kb, len(d) - 1)]):] += 1
    for t in range(1, len(u)):
        a0 = t
        while a0 > 0 and seg[a0 - 1] == seg[t]:
            a0 -= 1
        if t - a0 >= 24:
            prior = mc[a0:t]
            if mc[t] > prior.max() and prior[-12:].max() < prior.max():
                out.append(int(u[t]))
    return out


def delivery_scores(cn, issuers, PR, OH, entry):
    sym = defaultdict(list)
    for h, code in cn.execute("""select distinct on (s.issuer_id, h.value) s.issuer_id::text, h.value from securities s
                                 join identifier_history h using(security_id) where h.kind='SYMBOL' and h.exchange='NSE'"""):
        sym[code].append(h)
    dl = defaultdict(dict)
    for code, day, pct in cn.execute("""select code, trade_date, delivery_pct::float from bhavcopy_rows
                                        where exchange='NSE' and series in ('EQ','BE') and delivery_pct is not null
                                          and trade_date >= current_date - 240"""):
        for h in sym.get(code, ()):
            dl[h][day.toordinal()] = pct
    out = np.full(len(issuers), np.nan)
    for i, h in enumerate(issuers):
        p = PR.get(h)
        if p is None or h not in dl:
            continue
        d, c = np.asarray(p["d"]), np.asarray(p["c"], float)
        a = int(np.searchsorted(d, int(entry[i]), side="right")) - 1
        if a < 126:
            continue
        lr = np.r_[np.nan, np.diff(np.log(c))]
        br = np.asarray(list(p["breaks"]) + list(OH.get(h, {}).get("unrec", [])), dtype=np.int64)
        if len(br):
            lr[np.isin(d, br)] = np.nan
        x = np.array([dl[h].get(int(v), np.nan) for v in d[a - 125:a + 1]], float)
        x[x > 100] = np.nan
        if np.isnan(x).mean() > 0.3:
            continue
        out[i] = np.nansum(np.where(x > np.nanmedian(x), lr[a - 125:a + 1], 0))
    return out


def run(asof, dry):
    run_dir = f"{V1}/run_{asof}"
    M = pickle.load(open(f"{V1}/model_v1.pkl", "rb"))
    Z = np.load(f"{run_dir}/panel.npz")
    meta = pickle.load(open(f"{run_dir}/meta.pkl", "rb"))
    X0, iss, c0 = Z["X"], meta["issuer"], meta["cols"]
    X = np.full((len(X0), len(M["cols"])), np.nan, dtype=np.float32)
    for j, c in enumerate(M["cols"]):
        if c in c0:
            X[:, j] = X0[:, c0.index(c)]
    fi, ri = [M["cols"].index(c) for c in M["FC"]], [M["cols"].index(c) for c in M["REGC"]]
    R = np.full((len(X), len(fi)), 0.5, dtype=np.float32)
    for k, j in enumerate(fi):
        v = X[:, j]
        ok = ~np.isnan(v)
        if ok.sum() > 1:
            R[ok, k] = (np.argsort(np.argsort(v[ok])) + 0.5) / ok.sum()
    w = np.array([M["lin_weights"][c] for c in M["FC"]])
    lin, gbm = (R - 0.5) @ w, M["gbm"].predict(np.hstack([R, X[:, ri]]))
    ens = (np.argsort(np.argsort(lin)) + np.argsort(np.argsort(gbm))) / 2.0
    col = lambda c: X[:, M["cols"].index(c)]
    adv, sector, entry = Z["adv20"], Z["sector"], Z["entry"]

    PR = pickle.load(open(f"{J}/ranking_model/prices.pkl", "rb"))
    OH = pickle.load(open(f"{J}/alpha_model/audit/ohlc.pkl", "rb"))
    m_now = asof.year * 12 + asof.month - 1
    ath12, ath3 = np.zeros(len(iss), bool), np.zeros(len(iss), bool)
    ath_when = {}
    for i, h in enumerate(iss):
        if h in PR:
            ev = [e for e in ath_events(PR[h], OH.get(h, {})) if e < m_now]
            if ev:
                ath_when[h] = ev[-1]
                ath12[i] = ev[-1] >= m_now - 12
                ath3[i] = ev[-1] >= m_now - 3
    cn = psycopg.connect(DSN, options="-c default_transaction_read_only=on")
    dm = delivery_scores(cn, iss, PR, OH, entry)
    sc, blend, mb4, psb = scores(col, ens, ath12, dm)
    q_super = qualifies_super(col, adv, ath3)

    sym = dict(cn.execute("""select distinct on (s.issuer_id) s.issuer_id::text, h.value from securities s join identifier_history h using(security_id)
                             where h.kind='SYMBOL' order by s.issuer_id, (h.exchange='NSE') desc, h.valid_to is null desc""").fetchall())
    legal = dict(cn.execute("select issuer_id::text, legal_name from issuers").fetchall())
    row_of = {h: i for i, h in enumerate(iss)}
    pe, mcap = percentile(ens), col("mcap_cr")
    mc = defaultdict(list)
    for i, h in enumerate(iss):
        if not np.isnan(mcap[i]):
            mc[sector[i]].append((float(mcap[i]), sym.get(h) or ""))
    sector_label = {s: "/".join(n for _, n in sorted(v, reverse=True)[:3]) for s, v in mc.items()}

    def fl(i, v):
        x = v[i]
        return None if np.isnan(x) else round(float(x), 4)

    def describe(h, status, rank=None, of=None, **extra):
        i = row_of.get(h)
        base = dict(issuer_id=h, symbol=sym.get(h), name=legal.get(h), status=status, rank=rank + 1 if rank is not None else None, of=of)
        if i is None:
            return {**base, "note": "no longer in the ranked universe", **extra}
        p, oh = PR.get(h), OH.get(h)
        close, close_date, circuit = None, None, False
        if p is not None and oh is not None:
            j = min(int(np.searchsorted(p["d"], int(entry[i]))), len(p["d"]) - 1)
            close, close_date = round(float(oh["raw_c"][j]), 2), date.fromordinal(int(p["d"][j])).isoformat()
            circuit = bool(j > 0 and ((oh["h"][j] <= oh["l"][j] * 1.0001 and p["c"][j] > p["c"][j - 1])
                                      or (p["c"][j] >= p["c"][j - 1] * 1.049 and p["c"][j] >= oh["h"][j] * 0.9999)))
        flags = [t for t, c in (("pledge >20%", "flag_pledge"), ("auditor event", "flag_auditor"), ("dilution", "flag_dilution"), ("finance cost > PAT", "flag_fincost"))
                 if c in M["cols"] and (col(c)[i] or 0) > 0]
        if circuit:
            flags.append("last close at upper circuit: buy only if tradable at the open")
        return {**base, "mcap_cr": fl(i, np.round(mcap)), "close": close, "close_date": close_date, "adv20_cr": fl(i, adv),
                "sector": sector_label.get(sector[i], ""), "v1_pct": fl(i, pe), "blend": fl(i, blend), "mom_12_1": fl(i, col("mom_12_1")),
                "mb4": fl(i, mb4), "ath_month": ym_key(ath_when[h]) if h in ath_when and ath12[i] else None, "ps_bonus": bool(psb[i]),
                "rev_yoy": fl(i, col("rev_yoy")), "pat_q_yoy": fl(i, col("pat_q_yoy")), "sue": fl(i, col("sue")), "flags": flags, **extra}

    mk = month_key(asof)
    if not dry and not os.path.exists(f"{BOOKS}/stack_a.json"):
        seed_books()
    out = {}
    price_date = date.fromordinal(int(np.max(entry))).isoformat()
    for k, cfg in STRATEGIES.items():
        book = json.load(open(f"{BOOKS}/{k}.json")) if os.path.exists(f"{BOOKS}/{k}.json") else dict(history=[])
        hist = book["history"]
        info = {x: cfg[x] for x in ("name", "rule", "cagr", "since24", "dd")}
        if k == "super_opps":
            new = [iss[i] for i in np.where(q_super)[0]]
            if hist and hist[-1]["month"] == mk:
                entries, prev_entries = hist[-1]["entries"], hist[-2]["entries"] if len(hist) > 1 else []
            else:
                prev_entries = hist[-1]["entries"] if hist else []
                entries = roll_super(prev_entries, mk, new)[0]
                if not dry:
                    hist.append(dict(month=mk, entries=entries, decided_on=date.today().isoformat()))
            held_ids = {e["issuer"] for e in entries}
            added = {e["issuer"] for e in entries if e["month"] == mk}
            rows = [describe(e["issuer"], "BUY" if e["issuer"] in added else "HOLD", entry_month=e["month"], sell_after=add_months(e["month"], 13)) for e in entries]
            rows.sort(key=lambda r: (r["status"] != "BUY", r["entry_month"]), reverse=False)
            sells = [describe(e["issuer"], "SELL", entry_month=e["month"]) for e in prev_entries if e["issuer"] not in held_ids]
            out[k] = {**info, "month": mk, "rows": rows, "sells": sells, "qualifiers_now": [sym.get(h) or h for h in new]}
        else:
            if hist and hist[-1]["month"] == mk:
                port, prev = hist[-1]["holdings"], hist[-2]["holdings"] if len(hist) > 1 else []
                rank, total = decide(sc[k], adv, sector, iss, port, cfg["keep"])[1:]
            else:
                prev = hist[-1]["holdings"] if hist else []
                port, rank, total = decide(sc[k], adv, sector, iss, prev, cfg["keep"])
                if not dry:
                    hist.append(dict(month=mk, holdings=port, decided_on=date.today().isoformat()))
            held = set(port)
            rows = [describe(h, "HOLD" if h in prev else "BUY", rank.get(h), total, score=fl(row_of[h], sc[k]) if h in row_of else None) for h in port]
            rows.sort(key=lambda r: r["rank"] or 10 ** 6)
            sells = [describe(h, "SELL", rank.get(h), total) for h in prev if h not in held]
            out[k] = {**info, "month": mk, "rows": rows, "sells": sells, "keep": cfg["keep"], "universe": total}
        out[k]["decided_on"] = hist[-1]["decided_on"] if hist else None
        if not dry:
            book["history"] = hist[-6:]
            write_json(f"{BOOKS}/{k}.json", book)
    result = dict(as_of=asof.isoformat(), price_date=price_date, generated=datetime.now().isoformat(timespec="seconds"), default=DEFAULT,
                  order=list(STRATEGIES), strategies=out)
    if dry:
        return result
    os.makedirs(LIVE, exist_ok=True)
    write_json(f"{LIVE}/strategies.json", result)
    return result


def add_months(key, n):
    t = int(key[:4]) * 12 + int(key[5:]) - 1 + n
    return f"{t // 12}-{t % 12 + 1:02d}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True)
    ap.add_argument("--dry", action="store_true", help="compute only; do not touch books or live/strategies.json")
    a = ap.parse_args()
    res = run(date.fromisoformat(a.asof), a.dry)
    for k, s in res["strategies"].items():
        print(k, len(s["rows"]), "held,", sum(r["status"] == "BUY" for r in s["rows"]), "new,", len(s["sells"]), "sell")
    if a.dry:
        print(json.dumps([r["symbol"] for r in res["strategies"]["blend"]["rows"]]))
