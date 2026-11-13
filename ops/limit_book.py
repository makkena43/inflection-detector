"""Limit-order version of the short-term book: dip rule + dividend run-up, identification only (nothing is ever ordered).

Same signals as short_book.py. Three things differ (study: Library short-term-5-10/report.md, rounds 1 and 4, 13 Nov 2026):
1. Dip entry is a resting BUY LIMIT 4% below the signal close, good for the next 2 trading days. It fills at the open if the stock
   opens below the limit, otherwise at the limit once the day's low trades 0.1% through it. About half the signals never fill.
2. Dip exit adds a resting SELL LIMIT 5% above the entry price from the day after the buy day (filled at the open if it opens
   above). The other exits stay: 3 x ATR stop, next open after a close above the 5-day average, close 5 trading days after buying.
3. An order is placed only when a slot is free for it, and an unfilled order keeps its slot until it expires.
Size: Smallcap 250 above its 50-day average on the day before the fill: 1/5 of the account, at most 7 positions, so up to 140%
invested (the part above 100% is broker margin). Otherwise 1/14 and no margin. Dividend leg unchanged (buy at the open).

Writes live/limit_book.json (orders for the next session, open positions, back-test summary), live/limit_book_history.json (every
simulated order) and live/limit_book.txt (a plain order sheet). Read-only on the DB.
"""
import bisect, json, os, pickle
from datetime import date, datetime

import numpy as np

import psycopg

from short_book import J, DSN, START, CASH, BORROW, load, calendar, dividends
from swing_scan import ffill, roll, shift

SLOTS, FULL, SMALL, MAX_GROSS = 7, 1 / 5, 1 / 14, 1.4
LIMIT, VALID, TARGET, THROUGH, STOP_ATR, MAX_DAYS = 0.04, 2, 0.05, 0.001, 3.0, 5
STRATEGY = dict(key="limit_book", name="Dip + dividend with limit orders (7 positions)",
                rule="Dip in a leader: buy limit 4% below the signal close for 2 days, sell limit 5% above entry, usual stop and exits. Dividend run-up unchanged. "
                     "1/5 of the account per position when Smallcap 250 is above its 50-day average (up to 140% invested), otherwise 1/14.")


def tick(p):
    return round(round(p / 0.05) * 0.05, 2)


def index_series():
    """Smallcap 250 closes: the daily index table, with the older ranking cache underneath for dates before the table starts."""
    out = {}
    path = f"{J}/ranking_model/sc.pkl"
    if os.path.exists(path):
        d, v = pickle.load(open(path, "rb"))
        out.update((int(a), float(b)) for a, b in zip(d, v) if b == b)
    with psycopg.connect(DSN, options="-c default_transaction_read_only=on") as cn:
        out.update((d.toordinal(), float(c)) for d, c in cn.execute("select trade_date, close from index_closes where index_name='Nifty Smallcap 250' and close is not null"))
    days = sorted(out)
    return np.array(days), np.array([out[d] for d in days])


def walk_dip(O, H, L, C, S5, locked, t, last, limit_px, atr):
    """One dip order for one stock, from prices alone. Arrays are that stock's daily series; t is the signal day.

    Returns None while nothing can be said, or a dict with status PENDING / EXPIRED, or with entry day e and price, and then
    either exit day x and price, a `due` action for the next session, or neither (still held)."""
    e = entry = None
    for v in range(1, VALID + 1):
        k = t + v
        if k > last:
            return dict(status="PENDING", days_left=VALID - v + 1)
        if np.isnan(O[k]) or locked(k):
            continue
        if O[k] <= limit_px:
            e, entry = k, float(O[k])
            break
        if L[k] < limit_px * (1 - THROUGH):
            e, entry = k, float(limit_px)
            break
    if e is None:
        return dict(status="EXPIRED")
    stop, target = entry - STOP_ATR * atr, entry * (1 + TARGET)
    out = dict(e=e, entry=entry, stop=float(stop), target=float(target))
    for k in range(e, min(last, e + MAX_DAYS) + 1):
        if np.isnan(C[k]):
            continue
        if L[k] <= stop and not locked(k):
            return {**out, "x": k, "exit": float(min(O[k], stop) if k > e else stop), "reason": "Stop hit"}
        if k > e:
            if O[k] >= target:
                return {**out, "x": k, "exit": float(O[k]), "reason": "Sell limit filled at the open"}
            if H[k] > target * (1 + THROUGH):
                return {**out, "x": k, "exit": float(target), "reason": "Sell limit filled"}
            if C[k] > S5[k]:
                if k < last:
                    return {**out, "x": k + 1, "exit": float(O[k + 1] if not np.isnan(O[k + 1]) else C[k]), "reason": "Close above 5-day average"}
                return {**out, "x": last + 1, "due": "SELL NEXT OPEN", "reason": "Closed above its 5-day average"}
    if e + MAX_DAYS <= last:
        k = e + MAX_DAYS
        while k > e and np.isnan(C[k]):
            k -= 1
        return {**out, "x": k, "exit": float(C[k]), "reason": "5-day limit"}
    if last + 1 == e + MAX_DAYS:
        return {**out, "x": e + MAX_DAYS, "due": "SELL AT CLOSE", "reason": "5-day limit"}
    return {**out, "x": e + MAX_DAYS}


def build(data=None, index=None, write=True):
    dates, issuers, M, BR, sym, nse, names, divs, results, *_ = data or load()   # newer load() returns extra values
    O, H, L, C, RAW, TV = (M[k].astype(float) for k in "ohlcrv")
    T, last, cal = len(dates), len(dates) - 1, calendar(dates)
    Cf, PC = ffill(C), shift(ffill(C), 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        R, R63, R5 = C / PC - 1, Cf / shift(Cf, 63) - 1, Cf / shift(Cf, 5) - 1
        day_bad = (np.nan_to_num(np.abs(R)) > 0.35) | (np.nan_to_num(np.abs(O / PC - 1)) > 0.35) | BR
    adv = roll(TV, 20, 16, np.nanmedian)
    bad = roll(day_bad.astype(float), 260, 1, np.nanmax) > 0
    S50, S5, S200 = roll(Cf, 50, 40, np.nanmean), roll(Cf, 5, 4, np.nanmean), roll(Cf, 200, 160, np.nanmean)
    ATR = roll(np.nanmax(np.stack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0), 14, 11, np.nanmean)
    with np.errstate(invalid="ignore"):
        universe = ~np.isnan(C) & (Cf >= 30) & (np.nan_to_num(adv) >= 2) & ~bad & ~np.isnan(S200)
    rs = np.full(C.shape, np.nan)
    for t in range(T):
        idx = np.where(universe[t] & ~np.isnan(R63[t]))[0]
        if len(idx):
            rs[t, idx] = (np.argsort(np.argsort(R63[t][idx])) + 1) / len(idx)
    cost = lambda t, u: 0.0055 if adv[t, u] >= 10 else 0.0085
    first = bisect.bisect_left(dates, START)

    # Smallcap 250 against its 50-day average, known at each close
    scd, scv = index or index_series()
    scd, scv = np.asarray(scd), np.asarray(scv, float)
    ords = np.array([d.toordinal() for d in dates])
    ix = scv[np.maximum(np.searchsorted(scd, ords, side="right") - 1, 0)]
    sma = np.convolve(ix, np.ones(50) / 50, "full")[:T]
    strong = np.zeros(T, bool)
    strong[49:] = ix[49:] > sma[49:]
    strong &= ords >= scd[0]                                     # no index data yet: small size
    index_date = date.fromordinal(int(scd[np.searchsorted(scd, ords[last], side="right") - 1])) if scd[0] <= ords[last] else None

    def label(u):
        return dict(symbol=sym.get(issuers[u]), issuer_id=issuers[u], name=names.get(issuers[u]))

    trades = []
    for t in range(first, T):
        with np.errstate(invalid="ignore"):
            sig = universe[t] & (np.nan_to_num(rs[t]) >= 0.95) & (C[t] > S50[t]) & (R5[t] < -0.08) & (R[t] < 0)
        for u in np.where(sig)[0]:
            trades.append(dict(kind="Dip", t=t, u=int(u), limit=float(C[t, u] * (1 - LIMIT))))

    # dividend leg, exactly as short_book.py
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
                if p >= 30 and g["amt"] / p >= 0.02 and g.get("record"):
                    upcoming.append(dict(label(u), ex_date=g["ex"].isoformat(), buy_date=cal[e].isoformat(), sell_date=cal[x].isoformat(), kind="Final" if not g["interim"] else "Interim",
                                         amount=round(g["amt"], 2), yield_pct=round(g["amt"] / p, 4), record_date=g["record"], last_close=round(float(p), 2)))
            continue
        t = e - 1
        if t < first or not universe[t, u] or not RAW[t, u] > 0 or g["amt"] / RAW[t, u] < 0.02:
            continue
        trades.append(dict(kind="Interim div" if g["interim"] else "Final div", t=t, u=u, x_plan=x, ex=g["ex"].isoformat(), amount=g["amt"], yield_pct=g["amt"] / RAW[t, u], record=g["record"]))

    def outcome(tr):
        t, u = tr["t"], tr["u"]
        if tr["kind"] == "Dip":
            return walk_dip(O[:, u], H[:, u], L[:, u], C[:, u], S5[:, u], lambda k: H[k, u] <= L[k, u] * 1.0005, t, last, tr["limit"], ATR[t, u])
        e, x = t + 1, tr["x_plan"]
        if e > last:
            return dict(status="PENDING", days_left=1)
        entry = O[e, u]
        if np.isnan(entry) or H[e, u] <= L[e, u] * 1.0005 or day_bad[e:min(x, last) + 1, u].any():
            return dict(status="EXPIRED")
        out = dict(e=e, entry=float(entry))
        if x <= last:
            while x > e and np.isnan(C[x, u]):
                x -= 1
            return {**out, "x": x, "exit": float(C[x, u]), "reason": "Close before ex-date"}
        return {**out, "x": x, "due": "SELL AT CLOSE" if x == last + 1 else None, "reason": f"Sell at the close before ex-date {tr['ex']}"}

    by_signal = {}
    for tr in trades:
        res = outcome(tr)
        if res is None:
            continue
        if res.get("x") is not None and day_bad[min(res["e"], last):min(res["x"], last) + 1, tr["u"]].any():
            continue
        tr.update(res)
        tr["rank"] = float(np.nan_to_num(rs[tr["t"], tr["u"]]))
        by_signal.setdefault(tr["t"], []).append(tr)

    eq, cash, opened, orders, book, curve = 1.0, 1.0, [], [], [], []
    for k in range(first + 1, T):
        live = []
        for tr in orders:                                        # fills today
            if tr.get("e") == k:
                invested = sum(p["alloc"] * Cf[k, p["u"]] / p["entry"] for p in opened)
                size = FULL if strong[k - 1] else SMALL
                alloc = min(eq * size, MAX_GROSS * eq - invested) if strong[k - 1] else min(eq * size, cash)
                if alloc <= eq * 0.01:
                    tr["status"] = "NO CASH"
                    continue
                tr.update(alloc=alloc, size=size, net=(tr["exit"] / tr["entry"] - 1 - cost(tr["t"], tr["u"])) if "exit" in tr else None)
                tr["status"] = "CLOSED" if "exit" in tr else (tr.get("due") or "HOLD")
                cash -= alloc
                opened.append(tr)
            elif tr.get("status") == "PENDING" or (tr.get("e", 0) > k) or (tr.get("status") == "EXPIRED" and k < tr["t"] + (VALID if tr["kind"] == "Dip" else 1)):
                live.append(tr)
        orders = live
        still = []
        for p in opened:                                         # exits today
            if p.get("x") is not None and p["x"] <= k and "exit" in p:
                cash += p["alloc"] * (1 + p["net"])
            else:
                still.append(p)
        opened = still
        cash *= 1 + (CASH if cash > 0 else BORROW)
        mtm = sum(p["alloc"] * Cf[k, p["u"]] / p["entry"] for p in opened)
        eq = cash + mtm
        curve.append((dates[k].isoformat(), eq, len(opened), mtm / eq))
        free = SLOTS - len(opened) - len(orders)                 # this evening: new orders only where a slot is free
        busy = {p["u"] for p in opened} | {o["u"] for o in orders}
        for tr in sorted(by_signal.get(k, []), key=lambda r: -r["rank"]):
            if tr["u"] in busy:
                tr["status"] = "ALREADY HELD"
            elif free < 1:
                tr["status"] = "NO SLOT"
            else:
                orders.append(tr)
                busy.add(tr["u"])
                free -= 1
            book.append(tr)

    size_now = FULL if strong[last] else SMALL

    def row(tr):
        u, t = tr["u"], tr["t"]
        dip = tr["kind"] == "Dip"
        out = dict(label(u), kind=tr["kind"], signal_date=dates[t].isoformat(), status=tr["status"], signal_close=round(float(RAW[t, u]), 2),
                   ret_63d=round(float(R63[t, u]), 4), ret_5d=round(float(R5[t, u]), 4), adv20_cr=round(float(adv[t, u]), 1), reason=tr.get("reason"),
                   ex_date=tr.get("ex"), record_date=tr.get("record"), yield_pct=round(tr["yield_pct"], 4) if tr.get("yield_pct") else None)
        if dip:
            out.update(buy_limit=tick(float(RAW[t, u]) * (1 - LIMIT)), valid_until=cal[min(t + VALID, len(cal) - 1)].isoformat(), stop_est=round(float(RAW[t, u] * (1 - LIMIT) - STOP_ATR * ATR[t, u]), 2))
        if tr.get("entry") is not None:
            out.update(buy_date=dates[tr["e"]].isoformat(), entry=round(tr["entry"], 2), size=round(tr["size"], 4) if tr.get("size") else None)
            if dip:
                out.update(sell_limit=tick(tr["target"]), stop=round(tr["stop"], 2), last_day=cal[min(tr["e"] + MAX_DAYS, len(cal) - 1)].isoformat())
            if tr["status"] in ("HOLD", "SELL NEXT OPEN", "SELL AT CLOSE"):
                out.update(last_close=round(float(Cf[last, u]), 2), pnl=round(float(Cf[last, u]) / tr["entry"] - 1, 4), days_held=last - tr["e"])
        if "exit" in tr and tr.get("x") is not None and tr["x"] <= last and tr.get("net") is not None:
            out.update(exit_date=dates[tr["x"]].isoformat(), exit=round(tr["exit"], 2), pnl=round(tr["net"], 4))
        return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in out.items()}

    rows = sorted((row(tr) for tr in book), key=lambda r: r["signal_date"], reverse=True)
    place = [row(tr) for tr in orders if tr.get("status") == "PENDING"]
    for r in place:
        r.update(size=round(size_now, 4), action="BUY LIMIT" if r["kind"] == "Dip" else "BUY NEXT OPEN")
    held = [row(p) for p in opened]
    eqs = np.array([c[1] for c in curve])
    years, prev = {}, 1.0
    for d, e, *_ in curve:
        years[d[:4]] = e
    by_year = {}
    for y, e in years.items():
        by_year[y] = round(float(e / prev - 1), 4)
        prev = e
    closed = [r for r in rows if r["status"] == "CLOSED" and r.get("pnl") is not None]
    summary = dict(cagr=round(float(eqs[-1] ** (250 / len(eqs)) - 1), 4), max_dd=round(float((eqs / np.maximum.accumulate(eqs) - 1).min()), 4), by_year=by_year, trades=len(closed),
                   avg_trade=round(float(np.mean([r["pnl"] for r in closed])), 4) if closed else None, win_rate=round(float(np.mean([r["pnl"] > 0 for r in closed])), 4) if closed else None,
                   avg_gross=round(float(np.mean([c[3] for c in curve])), 4), max_gross=round(float(max(c[3] for c in curve)), 4), start=curve[0][0])
    res = dict(strategy=STRATEGY, price_date=dates[last].isoformat(), next_session=cal[last + 1].isoformat(), generated=datetime.now().isoformat(timespec="seconds"),
               market=dict(above_50d=bool(strong[last]), index_date=index_date.isoformat() if index_date else None, size=round(size_now, 4), size_label="1/5, margin to 140%" if strong[last] else "1/14, no margin"),
               place=place, hold=held, blocked=[r for r in rows if r["signal_date"] == dates[last].isoformat() and r["status"] in ("NO SLOT", "ALREADY HELD")],
               upcoming=sorted(upcoming, key=lambda r: r["buy_date"]), slots=SLOTS, free_slots=SLOTS - len(opened) - len(orders), backtest=summary)
    if write:
        os.makedirs(f"{J}/live", exist_ok=True)
        for name, obj in (("limit_book.json", res), ("limit_book_history.json", rows)):
            path = f"{J}/live/{name}"
            with open(path + ".tmp", "w") as f:
                json.dump(obj, f, default=str, allow_nan=False)
            os.replace(path + ".tmp", path)
        with open(f"{J}/live/limit_book.txt", "w") as f:
            f.write(sheet(res))
    return res, curve, rows


def sheet(res):
    """Plain order sheet for the next session."""
    m = res["market"]
    out = [f"Limit book, prices to {res['price_date']}, orders for {res['next_session']}",
           f"Smallcap 250 ({m['index_date']}) is {'above' if m['above_50d'] else 'below'} its 50-day average: each new position {m['size_label']}. Free slots: {res['free_slots']} of {res['slots']}.", "",
           "PLACE BEFORE THE OPEN"]
    for r in res["place"]:
        if r["kind"] == "Dip":
            out.append(f"  BUY LIMIT {r['symbol'] or r['name']}  at {r['buy_limit']:.2f}  (signal close {r['signal_close']:.2f} on {r['signal_date']}; cancel after {r['valid_until']})")
        else:
            out.append(f"  BUY AT OPEN {r['symbol'] or r['name']}  ({r['kind']}, ex-date {r['ex_date']})")
    if not res["place"]:
        out.append("  nothing")
    out += ["", "OPEN POSITIONS"]
    for r in res["hold"]:
        if r["kind"] == "Dip":
            act = r["status"] if r["status"] != "HOLD" else f"keep SELL LIMIT {r['sell_limit']:.2f}, stop {r['stop']:.2f}, last day {r['last_day']}"
            if r.get("buy_date") == res["price_date"] and r["status"] == "HOLD":
                act = f"bought today: from tomorrow SELL LIMIT {r['sell_limit']:.2f}, stop {r['stop']:.2f}, last day {r['last_day']}"
        else:
            act = r["status"] if r["status"] != "HOLD" else (r.get("reason") or "hold")
        out.append(f"  {r['symbol'] or r['name']}  entry {r['entry']:.2f} on {r['buy_date']}  now {r.get('last_close', 0):.2f} ({100 * r.get('pnl', 0):+.1f}%)  {act}")
    if not res["hold"]:
        out.append("  none")
    b = res["backtest"]
    out += ["", f"Back-test since {b['start']}: {100 * b['cagr']:+.0f}% a year, worst drawdown {100 * b['max_dd']:.0f}%, {b['trades']} trades, "
                f"average {100 * (b['avg_trade'] or 0):+.1f}%, winners {100 * (b['win_rate'] or 0):.0f}%.", "Identification only. Nothing is ordered by this job.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    res, curve, rows = build()
    print(sheet(res))
    print("by year", " ".join(f"{y} {100 * v:+.0f}%" for y, v in res["backtest"]["by_year"].items()))
