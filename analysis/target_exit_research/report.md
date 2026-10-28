# First-touch +50% / +100% exit simulation

Latest price: 2026-10-09. Tested 12 core screens plus all 180 previously searched ownership/category combinations (some duplicates).

## Rules

Use the first qualifying shortlist entry per company per screen, with ownership data published before entry. Buy at the first positive adjusted close within ten days of week start +14 days. From the NEXT trading day, sell at +50% or +100% when adjusted daily high first touches the target. Otherwise sell at the last available close on/before entry +182 calendar days. Require a completed 182-day market window and terminal quote no more than seven calendar days old. Pending/stale and missing entries are separately recorded, even if a partial window already touched target. No stop loss. No capital recycling. Returns are equal-weight averages per trade, not annualised portfolio returns.

High touching target is an indicative limit-order opportunity, not proof an order filled. To avoid assuming gap-up windfalls, fills are capped at exactly the target. Costs/taxes/slippage/dividends are excluded; a 0.5 percentage-point round-trip cost would reduce each quoted average by 0.5 pp. Close-hit counts provide a second, more conservative confirmation; this is NOT a separately simulated close-based execution strategy. Adverse excursions use prior-day lows and omit the exit-day low because OHLC does not reveal whether it happened before or after the target. They can understate actual pre-exit drawdowns.

## Main results

| Screen | Complete n | +50% hits | +50% exit strategy average | Median days to +50% (hits only) | +100% hits | +100% exit strategy average |
|---|---|---|---|---|---|
|Promoter + FII YoY increase|10|7/10 (70.0%)|+36.5%|71|4/10 (40.0%)|+56.6%|
|Technicals>=2 + promoter YoY >=0.5pp|10|7/10 (70.0%)|+39.0%|137|2/10 (20.0%)|+46.5%|
|Score4+ + FII up + promoter not reduced|10|6/10 (60.0%)|+34.6%|85.5|3/10 (30.0%)|+50.6%|
|Above + technicals>=2|17|9/17 (52.9%)|+36.5%|113|3/17 (17.6%)|+45.6%|
|Score>=4|54|28/54 (51.9%)|+27.2%|108.5|8/54 (14.8%)|+29.8%|
|Buying>=1cr|17|9/17 (52.9%)|+29.1%|101|5/17 (29.4%)|+39.8%|
|12m orders>=200%rev|13|5/13 (38.5%)|+25.3%|99|3/13 (23.1%)|+35.2%|
|Value smallcap|57|26/57 (45.6%)|+23.3%|112.0|8/57 (14.0%)|+26.0%|
|All shortlist|183|69/183 (37.7%)|+17.5%|108|25/183 (13.7%)|+22.8%|

## Both promoter and FII rising YoY: individual cases

| Symbol | Entry | +50% hit after days | +100% hit after days | Six-month hold return |
|---|---|---|---|---|
|JWL|2022-11-21|71|Not hit|+43.9%|
|FCL|2023-02-13|Not hit|Not hit|+14.0%|
|TEXRAIL|2023-05-22|37|66|+169.8%|
|ITI|2023-06-05|99|126|+152.7%|
|TECHNOE|2024-01-08|137|169|+89.6%|
|WELENT|2024-03-11|84|Not hit|+77.3%|
|MANAKCOAT|2024-10-14|56|Not hit|+29.2%|
|REMSONSIND|2025-05-26|Not hit|Not hit|-13.7%|
|POWERMECH|2026-01-19|Not hit|Not hit|+15.2%|
|STLTECH|2026-02-02|21|67|+430.1%|
|NITCO|Pending/missing full window|–|–|–|

## Findings and limits

Both YoY increasing reached +50% in 7/10 completed cases, and +100% in 4/10; all seven +50% cases also closed above that target at some point, while three of four +100% cases did. Median successful-hit time: 71 days for +50%, 96.5 for +100%. Only one of ten reached +50% within 30 days, none doubled within 30 days. Thus this is not a reliable one-month doubling setup.

Technicals>=2 plus promoter YoY increase >=0.5 pp also had 7/10 +50% hits, but median hit time was slower at 137 days; only six closed above target. Seven of its ten cases entered in 2024, with no 2025 cases, so regime concentration is material.

The both-up +50% strategy average is +36.5%, not +50%, because target misses remain invested until timeout. Its +100% strategy average is +56.6%. Six-month buy-and-hold mean for the same ten is +100.8%, so taking early profit did not maximise average return in this sample; early exits cap large winners. The different six-month hold figure versus stored outcomes reflects the actual entry date and last close on/before day 182 rather than the first available close after a fixed target date.

A real retracement example is TECHNOE: +100% first touched on day 169, but the six-month closing return was +89.6%; it fell approximately 23% below entry on an earlier day before target touch. Hitting a profit target can require tolerating losses first. No stop-loss strategy was tested here.

Recent samples weaken the apparently strongest rules: both-up 2025 has 0/1 +50% hits; its two 2026 cases have 1/2. Score4+ plus FII up/promoter not down has 0/1 in 2025 and 0/2 in 2026. All results are exploratory and selected from historical screens. No independent prospective validation, full corporate-action audit, liquidity/fill validation, delisting-loss correction or statistical multiple-testing adjustment has been completed. Missing BSE-only prices are not modelled as zero returns. Ownership coverage is incomplete. Recorded corporate-action warning and no-warning sensitivities are in results.json; absence of a warning does not validate a price series.
