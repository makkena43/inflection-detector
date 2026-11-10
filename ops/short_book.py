"""Sized-up short-term book: dip rule + dividend run-up, 7 positions, identification only (nothing is ever ordered).

Rules: short-term-research-2/SHORTLISTED.md and super-strategy/report.md (2026-11-09).
Universe: 20-day median traded value at least Rs 2 cr, price at least Rs 30, no one-day jump above 35% in 260 days.
Breadth: share of that universe closing above its 50-day average. Each new position is 1/5 of the account when breadth on the
signal day is at least 50%, otherwise 1/7. At most 7 positions; more candidates than slots go to the highest 3-month return.
Dip: top 5% by 3-month return, above the 50-day average, 5-day return below -8%, red day. Buy next open unless locked or more
than 8% above the previous close. Exit next open after a close above the 5-day average (from the day after buying), at a 3 x ATR
stop, or at the close 5 trading days after buying, as the study did. Dividend: announced, at least 2% of the prior close. Final: buy 10 trading days before the ex-date, skipped if results
fall in the window. Interim: 7 days before, not before the day after the latest results. Sell at the close before the ex-date.

Writes live/short_book.json (today's actions, breadth) and live/short_book_history.json (every simulated trade). Read-only on the DB.
Dates beyond the last trading day assume weekdays are trading days, so a market holiday can shift a planned date by one.
"""
import bisect, json, os, pickle, re
from datetime import date, datetime, timedelta

import numpy as np
import psycopg

from swing_scan import ffill, roll, shift

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
DSN = os.environ.get("INFLECTION_DSN", "postgresql:///inflection")
START, DAYS = date(2020, 7, 1), 2700
SLOTS, FULL, SMALL, BRAKE = 7, 1 / 5, 1 / 7, 0.50
CASH, BORROW = 1.065 ** (1 / 250) - 1, 1.14 ** (1 / 250) - 1
AMOUNT = re.compile(r"(?:Rs\.?|Re\.?|INR)\s*([0-9]+(?:\.[0-9]+)?)", re.I)
STRATEGY = dict(key="sized_up", name="Dip + dividend, sized up (7 positions)", cagr="+84.0%", since24="+78.2%", dd="-22%",  # audited on real announcement times (round 11, 10 Nov 2026)
                rule="Dip in a leader plus dividend run-up, at most 7 positions. Each new position is 1/5 of the account when market breadth is at least 50%, otherwise 1/7. "
                     "The size is set by breadth automatically. Above 100% invested, the extra is broker margin (MTF). Expect a 30-40% drop in a 2020-style crash.")


def load():
    """The study's own price base: split- and bonus-adjusted caches per issuer (refreshed by the Refresh ranking data step)."""
    PR = pickle.load(open(f"{J}/ranking_model/prices.pkl", "rb"))
    OH = pickle.load(open(f"{J}/alpha_model/audit/ohlc.pkl", "rb"))
    U = sorted(PR)
    alld = np.unique(np.concatenate([PR[h]["d"] for h in U]))
    alld = alld[alld >= date(2019, 6, 1).toordinal()]
    T, N = len(alld), len(U)
    M = {k: np.full((T, N), np.nan, np.float32) for k in "ohlcrv"}
    BR = np.zeros((T, N), bool)
    for u, h in enumerate(U):
        p, o = PR[h], OH[h]
        d = np.asarray(p["d"])
        k = np.searchsorted(alld, d)
        ok = (k < T) & (alld[np.minimum(k, T - 1)] == d)
        M["c"][k[ok], u], M["r"][k[ok], u], M["v"][k[ok], u] = np.asarray(p["c"])[ok], np.asarray(o["raw_c"])[ok], np.asarray(p["tv"])[ok]
        for x in "ohl":
            M[x][k[ok], u] = np.asarray(o[x], float)[ok]
        br = np.asarray(p["breaks"])
        if len(br):
            kb = np.searchsorted(alld, br)
            BR[kb[kb < T], u] = True
    del PR, OH
    with psycopg.connect(DSN, options="-c default_transaction_read_only=on") as cn:
        pairs = cn.execute("""select distinct on (s.issuer_id) s.issuer_id::text, h.value from securities s join identifier_history h using(security_id)
                              where h.kind='SYMBOL' order by s.issuer_id, (h.exchange='NSE') desc, h.valid_to is null desc""").fetchall()
        nse = dict(cn.execute("""select distinct on (h.value) h.value, s.issuer_id::text from identifier_history h join securities s using(security_id)
                                 where h.kind='SYMBOL' and h.exchange='NSE' order by h.value, h.valid_to is null desc""").fetchall())
        names = dict(cn.execute("select issuer_id::text, legal_name from issuers").fetchall())
        divs = cn.execute("""select details->'raw'->>'symbol', ex_date, details->'raw'->>'subject', details->'raw'->>'recDate' from corporate_actions where kind='DIVIDEND' and ex_date >= '2020-01-01'""").fetchall()
        results = cn.execute("""select issuer_id::text, min((available_at at time zone 'Asia/Kolkata')::date) from financial_facts_asof
                                where metric='revenue' and available_at >= '2019-06-01' group by issuer_id, period_end""").fetchall()
    dates = [date.fromordinal(int(x)) for x in alld]
    return dates, U, M, BR, dict(pairs), nse, names, divs, results


def calendar(dates):
    """Trading days, then weekdays for the next 90 days, for planning dividend entries."""
    cal, d = list(dates), dates[-1]
    for _ in range(90):
        d += timedelta(days=1)
        if d.weekday() < 5:
            cal.append(d)
    return cal


def dividends(divs, cal, code_at):
    grouped = {}
    for code, ex, subject, rec in divs:
        if code not in code_at or not subject:
            continue
        found = AMOUNT.findall(subject)
        if not found:
            continue
        k = bisect.bisect_left(cal, ex)
        if k <= 30 or k >= len(cal):
            continue
        g = grouped.setdefault((code_at[code], k), dict(amt=0.0, interim=False, ex=ex, record=rec))
        g["amt"] += sum(float(v) for v in found)
        g["interim"] |= "interim" in subject.lower()
    return grouped


def build():
    dates, issuers, M, BR, sym, nse, names, divs, results = load()
    O, H, L, C, RAW, TV = (M[k].astype(float) for k in "ohlcrv")
    del M
    T, last, cal = len(dates), len(dates) - 1, calendar(dates)
    Cf, PC = ffill(C), shift(ffill(C), 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        R, R63, R5 = C / PC - 1, Cf / shift(Cf, 63) - 1, Cf / shift(Cf, 5) - 1
    adv = roll(TV, 20, 16, np.nanmedian)
    with np.errstate(invalid="ignore", divide="ignore"):
        day_bad = (np.nan_to_num(np.abs(R)) > 0.35) | (np.nan_to_num(np.abs(O / PC - 1)) > 0.35) | BR   # split errors and data artefacts
    bad = roll(day_bad.astype(float), 260, 1, np.nanmax) > 0
    S50, S5, S200 = roll(Cf, 50, 40, np.nanmean), roll(Cf, 5, 4, np.nanmean), roll(Cf, 200, 160, np.nanmean)
    TR = np.nanmax(np.stack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0)
    ATR = roll(TR, 14, 11, np.nanmean)
    with np.errstate(invalid="ignore"):
        E = ~np.isnan(C) & (Cf >= 30) & (np.nan_to_num(adv) >= 2) & ~bad
        above = C > S50
    with np.errstate(invalid="ignore", divide="ignore"):
        breadth = np.where(E.sum(1) > 0, (E & above & ~np.isnan(S50)).sum(1) / np.maximum(E.sum(1), 1), np.nan)
    universe = E & ~np.isnan(S200)                              # breadth uses E; ranks and signals also need 200-day history, as in the study
    rs = np.full(C.shape, np.nan)
    for t in range(T):
        idx = np.where(universe[t] & ~np.isnan(R63[t]))[0]
        if len(idx):
            rs[t, idx] = (np.argsort(np.argsort(R63[t][idx])) + 1) / len(idx)
    locked = lambda e, u: H[e, u] <= L[e, u] * 1.0005
    cost = lambda t, u: 0.0055 if adv[t, u] >= 10 else 0.0085   # 0.25% statutory plus 0.15% or 0.3% slippage per side, as in the study
    first = bisect.bisect_left(dates, START)

    def label(u):
        return dict(symbol=sym.get(issuers[u]), issuer_id=issuers[u], name=names.get(issuers[u]))

    trades = []
    for t in range(first, T):                                   # dip rule: signal at close t, buy open t+1
        with np.errstate(invalid="ignore"):
            sig = universe[t] & (np.nan_to_num(rs[t]) >= 0.95) & (C[t] > S50[t]) & (R5[t] < -0.08) & (R[t] < 0)
        for u in np.where(sig)[0]:
            trades.append(dict(kind="Dip", t=t, u=int(u), e=t + 1))
    idx_of = {h: i for i, h in enumerate(issuers)}
    code_at = {c: idx_of[h] for c, h in nse.items() if h in idx_of}
    avail = {}
    for iss, day in results:
        avail.setdefault(iss, []).append(day)
    for v in avail.values():
        v.sort()
    upcoming = []
    for (u, k), g in dividends(divs, cal, code_at).items():
        ds = avail.get(issuers[u], [])
        i = bisect.bisect_left(ds, cal[k]) - 1
        if i < 0:
            continue
        dk = bisect.bisect_left(cal, ds[i])
        if g["interim"]:
            e = max(k - 7, dk + 1)
        else:
            if k - dk <= 10:
                continue
            e = k - 10
        x = k - 1
        if x - e < 3 or e < 2 or e - 1 > last:
            if e - 1 > last and x - e >= 3 and last - 30 < e:
                p = RAW[last, u]
                if p >= 30 and g["amt"] / p >= 0.02 and g.get("record"):   # live rule: amount and record date both announced
                    upcoming.append(dict(label(u), ex_date=g["ex"].isoformat(), buy_date=cal[e].isoformat(), sell_date=cal[x].isoformat(), kind="Final" if not g["interim"] else "Interim",
                                         amount=round(g["amt"], 2), yield_pct=round(g["amt"] / p, 4), record_date=g["record"], last_close=round(float(p), 2)))
            continue
        t = e - 1
        if t < first or not universe[t, u] or not RAW[t, u] > 0 or g["amt"] / RAW[t, u] < 0.02:
            continue
        trades.append(dict(kind="Interim div" if g["interim"] else "Final div", t=t, u=u, e=e, x_plan=x, ex=g["ex"].isoformat(), amount=g["amt"], yield_pct=g["amt"] / RAW[t, u], record=g["record"]))

    def outcome(tr):
        """Fill in entry, exit and status from prices alone, independent of the portfolio."""
        t, u, e = tr["t"], tr["u"], tr["e"]
        if e > last:
            return dict(entry=None, status="BUY NEXT OPEN")
        entry = O[e, u]
        if np.isnan(entry) or locked(e, u) or (tr["kind"] == "Dip" and entry > PC[e, u] * 1.08):
            return None
        out = dict(entry=float(entry))
        if tr["kind"] == "Dip":
            stop = entry - 3 * ATR[t, u]
            out["stop"] = float(stop)
            for k in range(e, min(last, e + 5) + 1):
                if np.isnan(C[k, u]):
                    continue
                if L[k, u] <= stop and not locked(k, u):
                    return {**out, "x": k, "exit": float(min(O[k, u], stop)), "reason": "Stop hit"}
                if k > e and C[k, u] > S5[k, u]:                    # the buy day's own close does not count
                    if k < last:
                        return {**out, "x": k + 1, "exit": float(O[k + 1, u] if not np.isnan(O[k + 1, u]) else C[k, u]), "reason": "Close above 5-day average"}
                    return {**out, "x": last + 1, "due": "SELL NEXT OPEN", "reason": "Closed above its 5-day average"}
            if e + 5 <= last:
                kk = e + 5
                while kk > e and np.isnan(C[kk, u]):
                    kk -= 1
                return {**out, "x": kk, "exit": float(C[kk, u]), "reason": "5-day limit"}
            due = "SELL AT CLOSE" if last + 1 == e + 5 else None
            return {**out, "x": e + 5, "due": due, "reason": "5-day limit" if due else None}
        x = tr["x_plan"]
        if day_bad[min(e, last):min(x, last) + 1, u].any():
            return None
        if x <= last:
            while x > e and np.isnan(C[x, u]):
                x -= 1
            return {**out, "x": x, "exit": float(C[x, u]), "reason": "Close before ex-date"}
        return {**out, "x": x, "due": "SELL AT CLOSE" if x == last + 1 else None, "reason": f"Sell at the close before ex-date {tr['ex']}"}

    by_entry, busy = {}, {}
    for tr in sorted(trades, key=lambda r: r["t"]):
        res = outcome(tr)
        if res is None:
            continue
        if res.get("x") is not None and day_bad[min(tr["e"], last):min(res["x"], last) + 1, tr["u"]].any():
            continue
        if tr["kind"] == "Dip" and busy.get(tr["u"], -1) >= tr["t"]:
            continue
        if tr["kind"] == "Dip":
            busy[tr["u"]] = res.get("x", tr["e"] + 5)
        tr.update(res)
        tr["rank"] = float(np.nan_to_num(rs[tr["t"], tr["u"]]))
        by_entry.setdefault(tr["e"], []).append(tr)

    eq, cash, opened, book, curve = 1.0, 1.0, [], [], []
    for k in range(first + 1, T + 1):
        still = []
        for p in opened:
            if p["x"] == k and "exit" in p:
                cash += p["alloc"] * (1 + p["net"])
            else:
                still.append(p)
        opened = still
        if k < T:
            cash *= 1 + (CASH if cash > 0 else BORROW)
        size = FULL if breadth[k - 1] >= BRAKE else SMALL
        added = 0
        for tr in sorted(by_entry.get(k, []), key=lambda r: -r["rank"]):
            taken = sum(1 for p in opened if not (k > last and p.get("due") and p["x"] <= k)) + added   # slots freed by exits due at this open or close
            if any(p["u"] == tr["u"] for p in opened):
                tr["status"] = "ALREADY HELD"
                book.append(tr)
                continue
            if taken >= SLOTS:
                tr["status"] = "NO SLOT"
                book.append(tr)
                continue
            tr["size"] = size
            if k <= last:
                tr["alloc"] = eq * size
                tr["net"] = (tr["exit"] / tr["entry"] - 1 - cost(tr["t"], tr["u"])) if "exit" in tr else None
                cash -= tr["alloc"]
                opened.append(tr)
                tr["status"] = "CLOSED" if "exit" in tr else (tr.get("due") or "HOLD")
            else:
                added += 1
            book.append(tr)
        if k < T:
            mtm = sum(p["alloc"] * Cf[k, p["u"]] / p["entry"] for p in opened)
            eq = cash + mtm
            curve.append((dates[k].isoformat(), eq, len(opened), mtm / eq))

    def row(tr):
        u = tr["u"]
        e = tr["e"]
        planned_exit = cal[min(tr["x_plan"], len(cal) - 1)] if tr["kind"] != "Dip" else cal[min(e + 5, len(cal) - 1)]
        out = dict(label(u), kind=tr["kind"], signal_date=dates[tr["t"]].isoformat(), status=tr["status"], size=round(tr["size"], 4) if tr.get("size") else None,
                   size_label=("1.4x (1/5)" if tr["size"] == FULL else "1x (1/7)") if tr.get("size") else None, entry_date=cal[e].isoformat(), planned_exit=planned_exit.isoformat(),
                   record_date=tr.get("record"),
                   signal_close=round(float(RAW[tr["t"], u]), 2), ret_63d=round(float(R63[tr["t"], u]), 4), ret_5d=round(float(R5[tr["t"], u]), 4),
                   adv20_cr=round(float(adv[tr["t"], u]), 1), reason=tr.get("reason"), ex_date=tr.get("ex"), yield_pct=round(tr["yield_pct"], 4) if tr.get("yield_pct") else None)
        if tr["e"] <= last:
            out.update(buy_date=dates[tr["e"]].isoformat(), entry=round(tr["entry"], 2))
            if tr.get("stop") is not None and not np.isnan(tr["stop"]):
                out["stop"] = round(tr["stop"], 2)
        elif tr["kind"] == "Dip":
            out["stop_est"] = round(float(C[tr["t"], u] - 3 * ATR[tr["t"], u]), 2)
        if tr.get("entry") and tr.get("status") != "CLOSED":
            close = float(Cf[last, u])
            out.update(last_close=round(close, 2), pnl=round(close / tr["entry"] - 1, 4), days_held=last - tr["e"])
        if "exit" in tr and tr["x"] <= last:
            out.update(exit_date=dates[tr["x"]].isoformat(), exit=round(tr["exit"], 2), pnl=round(tr["net"], 4) if tr.get("net") is not None else None)
        return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in out.items()}

    rows = [row(tr) for tr in book]
    rows.sort(key=lambda r: r["signal_date"], reverse=True)
    series = [dict(date=dates[t].isoformat(), breadth=round(float(breadth[t]), 4)) for t in range(max(0, T - 120), T)]
    today = float(breadth[last])
    live = [r for r in rows if r["status"] in ("HOLD", "SELL NEXT OPEN", "SELL AT CLOSE")]
    res = dict(strategy=STRATEGY, price_date=dates[last].isoformat(), generated=datetime.now().isoformat(timespec="seconds"),
               breadth=dict(value=round(today, 4), date=dates[last].isoformat(), full_size=today >= BRAKE, size=round(FULL if today >= BRAKE else SMALL, 4), size_label="1.4x (1/5)" if today >= BRAKE else "1x (1/7)", next_open=cal[last + 1].isoformat(), eligible=int(E[last].sum()), series=series),
               buy=[r for r in rows if r["status"] == "BUY NEXT OPEN"], sell=[r for r in live if r["status"] != "HOLD"], hold=[r for r in live if r["status"] == "HOLD"],
               blocked=[r for r in rows if r["signal_date"] == dates[last].isoformat() and r["status"] in ("NO SLOT", "ALREADY HELD")],
               upcoming=sorted(upcoming, key=lambda r: r["buy_date"]), held=len(live), dividends_through=max((d[1] for d in divs), default=None), slots=SLOTS, gross=round(curve[-1][3], 4), months=sorted({r["signal_date"][:7] for r in rows}))
    os.makedirs(f"{J}/live", exist_ok=True)
    for name, obj in (("short_book.json", res), ("short_book_history.json", rows)):
        path = f"{J}/live/{name}"
        with open(path + ".tmp", "w") as f:
            json.dump(obj, f, default=str, allow_nan=False)
        os.replace(path + ".tmp", path)
    return res, curve, rows


if __name__ == "__main__":
    res, curve, rows = build()
    eq = np.array([c[1] for c in curve])
    print("price date", res["price_date"], "breadth", res["breadth"]["value"], "buy", len(res["buy"]), "sell", len(res["sell"]), "hold", len(res["hold"]), "upcoming", len(res["upcoming"]))
    print("CAGR %.1f%%  max DD %.1f%%  avg gross %.0f%%  max gross %.0f%%" % (100 * (eq[-1] ** (250 / len(eq)) - 1), 100 * (eq / np.maximum.accumulate(eq) - 1).min(), 100 * np.mean([c[3] for c in curve]), 100 * max(c[3] for c in curve)))
    years = {}
    for d, e, *_ in curve:
        years[d[:4]] = e
    prev = 1.0
    for y, e in years.items():
        print(y, "%+.0f%%" % (100 * (e / prev - 1)))
        prev = e
