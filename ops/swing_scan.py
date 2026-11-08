"""Daily "dip in a leader" swing scan (shortlist #6, rule frozen 2026-11-07; identification only, nothing is ordered).

Signal at the close: NSE EQ/BE, close >= Rs 30, 20-day median traded value >= Rs 2 cr, no >35% one-day jump in 260 days;
63-day return in the top 5% of that universe; close above the 50-day average; 5-day return below -8%; today a down day.
Buy at the next open (skip if it opens more than 8% above the signal close or is locked at circuit). Exit, first of: the
next open after a close above the 5-day average; 3 x ATR(14) below entry; the close 5 trading days after the buy day.
10 equal slots; extra signals ranked by 63-day return.

Prices are raw bhavcopy prices; splits and bonuses are removed by the jump filter. Writes live/swing.json. Read-only on the DB.
"""
import json, os, warnings
from datetime import datetime

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import psycopg

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
DSN = os.environ.get("INFLECTION_DSN", "postgresql:///inflection")
SLOTS, MAX_DAYS, LOOKBACK_SIGNALS = 10, 5, 30

STRATEGY = dict(name="Dip in a leader (5-day max)", cagr="+31.9%", since24="+34.0%", dd="-14%",
                rule="63-day return in the top 5%, close above the 50-day average, 5-day return worse than -8%, a down day. "
                     "Buy next open. Exit at the next open after a close above the 5-day average, at a 3x ATR stop, or at the close 5 trading days after buying.")


def load():
    with psycopg.connect(DSN, options="-c default_transaction_read_only=on") as cn:
        rows = cn.execute("""select trade_date, code, open::float, high::float, low::float, close::float, volume::float
                             from bhavcopy_rows where exchange='NSE' and series in ('EQ','BE') and trade_date >= current_date - 520""").fetchall()
        ids = dict(cn.execute("""select distinct on (h.value) h.value, s.issuer_id::text from identifier_history h join securities s using(security_id)
                                 where h.kind='SYMBOL' and h.exchange='NSE' order by h.value, h.valid_to is null desc""").fetchall())
        names = dict(cn.execute("select issuer_id::text, legal_name from issuers").fetchall())
    dates, codes = sorted({r[0] for r in rows}), sorted({r[1] for r in rows})
    di, ci = {d: i for i, d in enumerate(dates)}, {c: i for i, c in enumerate(codes)}
    A = np.full((5, len(dates), len(codes)), np.nan)
    for d, c, *vals in rows:
        A[:, di[d], ci[c]] = [np.nan if v is None else v for v in vals]
    return dates, codes, A, ids, names


def ffill(a):
    out = a.copy()
    for t in range(1, len(out)):
        m = np.isnan(out[t])
        out[t][m] = out[t - 1][m]
    return out


def shift(a, n):
    out = np.full(a.shape, np.nan)
    out[n:] = a[:-n]
    return out


def roll(a, n, min_periods, fn):
    w = sliding_window_view(a, n, axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        v = fn(w, axis=-1)
    v[(~np.isnan(w)).sum(-1) < min_periods] = np.nan
    out = np.full(a.shape, np.nan)
    out[n - 1:] = v
    return out


def scan():
    dates, codes, (O, H, L, C, V), ids, names = load()
    Cf = ffill(C)
    PC = shift(Cf, 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        R, R63, R5 = C / PC - 1, Cf / shift(Cf, 63) - 1, Cf / shift(Cf, 5) - 1
    adv = roll(C * V / 1e7, 20, 16, np.nanmedian)
    jump = np.nan_to_num(np.abs(R)) > 0.35
    bad = roll(jump.astype(float), 260, 1, np.nanmax) > 0
    S50, S5 = roll(Cf, 50, 40, np.nanmean), roll(Cf, 5, 5, np.nanmean)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        TR = np.nanmax(np.stack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0)
    ATR = roll(TR, 14, 11, np.nanmean)

    events = []
    for t in range(len(dates) - LOOKBACK_SIGNALS, len(dates)):
        elig = ~np.isnan(C[t]) & (np.nan_to_num(C[t]) >= 30) & (np.nan_to_num(adv[t]) >= 2) & ~bad[t] & ~np.isnan(S50[t]) & ~np.isnan(R63[t])
        rs = np.full(len(codes), np.nan)
        idx = np.where(elig)[0]
        rs[idx] = (np.argsort(np.argsort(R63[t][idx])) + 1) / len(idx)
        with np.errstate(invalid="ignore"):
            sig = elig & (rs >= 0.95) & (C[t] > S50[t]) & (R5[t] < -0.08) & (R[t] < 0)
        for j in np.where(sig)[0]:
            events.append((t, j, float(R63[t, j]), float(R5[t, j]), float(rs[j]), float(adv[t, j]), float(ATR[t, j])))

    last = len(dates) - 1
    out, open_slots = [], {}
    for t, col, r63, r5, rs, a20, atr in sorted(events, key=lambda e: (e[0], -e[2])):
        code, sig_close = codes[col], float(C[t, col])
        row = dict(signal_date=dates[t].isoformat(), symbol=code, issuer_id=ids.get(code), name=names.get(ids.get(code)), signal_close=round(sig_close, 2),
                   ret_63d=round(r63, 4), ret_5d=round(r5, 4), rs_pct=round(rs, 3), adv20_cr=round(a20, 1))
        open_slots = {c: e for c, e in open_slots.items() if e > t}
        if t == last:
            row.update(status="BUY NEXT OPEN", stop_est=round(sig_close - 3 * atr, 2), note="Skip if it opens more than 8% above the signal close or is locked at circuit")
            if len(open_slots) >= SLOTS or code in open_slots:
                row.update(status="NO SLOT" if code not in open_slots else "ALREADY HELD", stop_est=None)
            out.append(row)
            continue
        e = t + 1
        entry, hi, lo = O[e, col], H[e, col], L[e, col]
        if np.isnan(entry):
            continue
        if entry > sig_close * 1.08 or (hi <= lo * 1.0001 and entry > sig_close):
            row.update(status="SKIPPED", note="Opened too far above the signal close, or locked")
            out.append(row)
            continue
        if len(open_slots) >= SLOTS or code in open_slots:
            row.update(status="NO SLOT" if code not in open_slots else "ALREADY HELD")
            out.append(row)
            continue
        stop = entry - 3 * atr
        row.update(buy_date=dates[e].isoformat(), entry=round(float(entry), 2), stop=round(float(stop), 2), status="HOLD", exit_by=None)
        exit_i, exit_px, reason = None, None, None
        for k in range(e, min(last, e + MAX_DAYS) + 1):
            if L[k, col] <= stop:
                exit_i, exit_px, reason = k, stop, "Stop hit"
                break
            close = C[k, col]
            if close > S5[k, col]:
                if k < last:
                    exit_i, exit_px, reason = k + 1, O[k + 1, col], "Close above 5-day average"
                else:
                    row.update(status="SELL NEXT OPEN", note="Closed above its 5-day average")
                break
            if k == e + MAX_DAYS:
                exit_i, exit_px, reason = k, close, "5-day limit"
                break
        close_now = float(Cf[last, col])
        if exit_i is None:
            days = last - e
            row.update(last_close=round(close_now, 2), pnl=round(close_now / entry - 1, 4), days_held=days, exit_by=dates[min(e + MAX_DAYS, last)].isoformat() if e + MAX_DAYS <= last else f"{MAX_DAYS - days} more trading days")
            if row["status"] == "HOLD" and days == MAX_DAYS:
                row.update(status="SELL AT CLOSE")
            open_slots[code] = last + 1
        else:
            row.update(status="CLOSED", exit_date=dates[exit_i].isoformat(), exit=round(float(exit_px), 2), pnl=round(float(exit_px) / entry - 1, 4), reason=reason)
            open_slots[code] = exit_i
        out.append(row)
    out.sort(key=lambda r: r["signal_date"], reverse=True)
    res = dict(strategy=STRATEGY, price_date=dates[last].isoformat(), generated=datetime.now().isoformat(timespec="seconds"), rows=out,
               held=sum(r["status"] in ("HOLD", "SELL NEXT OPEN", "SELL AT CLOSE") for r in out), signals_today=sum(r["signal_date"] == dates[last].isoformat() for r in out))
    os.makedirs(f"{J}/live", exist_ok=True)
    tmp = f"{J}/live/swing.json.tmp"
    json.dump(res, open(tmp, "w"), default=str, allow_nan=False)
    os.replace(tmp, f"{J}/live/swing.json")
    return res


if __name__ == "__main__":
    res = scan()
    print(res["price_date"], "signals today:", res["signals_today"], "held:", res["held"], "rows:", len(res["rows"]))
    for r in res["rows"][:12]:
        print(r["signal_date"], r["symbol"], r["status"], r.get("pnl"))
