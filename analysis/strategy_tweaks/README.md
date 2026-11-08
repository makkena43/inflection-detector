# Strategy tweaks: new data points test (8 Nov 2026)
Run on the Mac (single process, gentle):
```
cd ~/inflection-jobs/strategy_tweaks/code   # copy of this folder
ENG_D=~/inflection-jobs nice -n 10 ~/PycharmProjects/inflection-detector/.venv/bin/python t9.py > t9.log 2>&1
```
Needs ~/inflection-jobs/{ranking_model,alpha_model,alternatives3,pv_setups} caches and ~/inflection-jobs/strategy_tweaks/data/{bulk_block_deals,insider_trades}.csv.gz.
feats.pkl / feats2.pkl are prebuilt (delivery momentum, ATH-after-base, price flags) for the 2026-11-05 panel. Full report: project file strategy-tweaks/report.md.

MF portfolios test (after ~/inflection-jobs/mf_portfolios/parsed/*.csv.gz exist):
```
ENG_D=~/inflection-jobs nice -n 10 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 t10.py > t10.log 2>&1
```
