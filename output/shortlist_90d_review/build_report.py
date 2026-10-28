import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'sources'
OLD = ROOT.parent / 'shortlist_deep_review' / 'sources'

# Independent research assessments; market observations are loaded separately.
rows = [
 dict(id='526775', company='Valiant Communications', verdict='WATCH', conviction=3,
  summary='Strongest operating evidence, but the fresh-entry return case at this valuation needs more proof.',
  evidence=['VALIANT_FY26','VALIANT_Q1','VALIANT_ORDER','VALIANT_NEW_ORDER'],
  paragraphs=[
   'The ₹40.25 crore power-sector award is firm, but includes taxes, services and AMC and runs to 31 December 2028. The contractual customer is a private system integrator, with an Indian power utility as end user. A further ₹14.76 crore supply award disclosed on 27 October runs to 31 October 2027. Do not recognise the entire ₹40.25 crore in the next four quarters, or automatically add awards without checking overlap.',
   'Consolidated June-quarter revenue rose to ₹25.42 crore from ₹18.32 crore and PAT to ₹7.79 crore from ₹4.72 crore: approximately 39% and 65% growth. FY26 operating cash flow was ₹32.45 crore against PAT of ₹24.18 crore, helped by a ₹5.51 crore inventory release. This is substantially stronger evidence than an order announcement alone. FY26 investment gains of ₹3.23 crore before tax mean reported profit is not entirely operating earnings.',
   'Using June paid-up capital, the indicated market value is roughly ₹1,869 crore and reported consolidated TTM PAT ₹27.25 crore: approximately 69 times earnings and 20 times sales. Another 350,000 warrants were outstanding at June-end; later conversion must be checked before sizing. Fresh-entry reassessment: WATCH, 3/5. At approximately 69 times trailing earnings, even 50% profit growth and a subsequent 40-times multiple would imply a price near Rs 1,400, assuming unchanged shares. This is an illustrative sensitivity, not a forecast or fair-value target. My earlier BUY, 4/5 overweighted business momentum relative to the entry-price risk. High valuation and the prior rally alone are not reasons to reject an accelerating business.'],
  red_flag='No demonstrated hard veto in the reviewed financial/order evidence; expensive reported earnings and warrant overhang constrain sizing.',
  trigger='Add conviction after the next results show order conversion, sustained operating margins and collections without a disproportionate receivables build.',
  breaks='Order delay/cancellation, deterioration in cash conversion, or profit growth dominated by investment gains.',
  risks=['High valuation and multiple compression','Power-sector execution and collections','Warrants and non-operating income'], months=12),
 dict(id='544440', company='Cryogenic OGS', verdict='WATCH', conviction=3,
  summary='Meaningful short-cycle awards and cash generation; verify new-product margins, delivery and borrowing classification.',
  evidence=['CRYO_FY26','CRYO_ORDER','CRYO_NEW_ORDER'],
  paragraphs=[
   'The export piping-spool order is USD 2.023 million, approximately ₹19.36 crore at the filing exchange rate, or 47% of FY26 revenue of ₹40.82 crore. Delivery is stated as 12–20 weeks. A separate 30 September metering-skid award is ₹5.08 crore including GST, also over 12–20 weeks. The counterparties are described, but not named, so credit quality cannot be independently established from these announcements.',
   'FY26 PAT of ₹10.18 crore includes a ₹1.24 crore pre-tax exceptional plot-sale gain. Operating cash flow of ₹7.99 crore and capital expenditure of ₹2.96 crore are encouraging. The balance sheet explicitly reports ₹8.25 crore long-term borrowings, alongside ₹32.78 crore cash/bank balances including ₹18.92 crore other deposits; calling the company debt-free would be inaccurate. The borrowing does not reconcile transparently to cash financing movements in this short results filing and merits a note-level explanation.',
   'At ₹356.50, equity value is approximately ₹509 crore and reported FY26 P/E about 50; the multiple is higher after normalising the exceptional gain. New piping revenue cannot safely be assigned the historic blended margin. Price is below its 50-day average but above its 200-day average; the recent rally is not the objection.'],
  red_flag='No established hard veto; new-vertical profitability, customer disclosure and the borrowing reconciliation remain unresolved.',
  trigger='Upgrade after delivery/billing evidence, profitable new-order execution and an explanation of the ₹8.25 crore borrowing and usable deposits.',
  breaks='Material delay beyond the stated delivery window, margin dilution or cash absorbed without corresponding collections.',
  risks=['New-vertical execution and margin','Unnamed counterparties','Borrowing/deposit reconciliation and SME trading conditions'], months=9),
 dict(id='517417', company='Patels Airtemp', verdict='WATCH', conviction=3,
  summary='Large, identified refinery order and reasonable historic valuation; funding and the weak latest quarter need resolution.',
  evidence=['PATELS_ORDER','PATELS_FY26','PATELS_Q1'],
  paragraphs=[
   'The customer is Dangote Petroleum Refinery and Petrochemicals in Nigeria. The firm, fixed-price air-cooled heat-exchanger order is USD 23.664 million, approximately ₹226.13 crore, for execution over 12 months. This is approximately 89% of FY26 revenue of ₹252.94 crore, rather than the UI’s 122% against a different/stale revenue denominator. The customer and execution term are disclosed, so they should not be labelled unknown.',
   'FY26 PAT was ₹10.27 crore and operating cash flow ₹22.80 crore. However, inventory release contributed ₹32.48 crore while receivables absorbed ₹15.34 crore. Current borrowings were ₹88.14 crore, cash ₹33.66 crore, inventory ₹82.67 crore and current receivables ₹106.66 crore. Finance cost was ₹9.95 crore. A large order has to be financed before it becomes free cash.',
   'June-quarter revenue was only ₹15.52 crore with a ₹0.62 crore loss. Current market value around ₹190 crore implies approximately 18.5 times FY26 earnings, but those earnings are not a reliable near-term run rate after this weak quarter. The stock is above both measured moving averages. The catalyst is substantial; the missing investment evidence is a credible funded delivery and cash-collection path.'],
  red_flag='Working-capital exposure, material borrowings and a loss-making latest quarter require monitoring.',
  trigger='Upgrade on advance/payment-security and funding evidence, procurement progress and a return to quarterly operating profitability.',
  breaks='Unfunded procurement, adverse FX/input costs on the fixed-price export contract, or delayed collections.',
  risks=['Working-capital funding','Fixed-price export and currency exposure','Latest-quarter revenue/profit weakness'], months=12),
 dict(id='544554', company='KVS Castings', verdict='WATCH', conviction=3,
  summary='Credible incremental order; first-year impact is smaller than the headline, while new capacity absorbs cash.',
  evidence=['KVS_ORDER','KVS_FY26'],
  paragraphs=[
   'The ₹20 crore order is from SAMM Corporation, a Delhi merchant exporter, for ultimate supply to Russian Railways. It is not a direct contract with Russian Railways. The disclosed delivery allocation is ₹8 crore in FY27 and ₹12 crore in FY28: only about 16% of FY26 revenue in the first financial year, rather than an immediate 39% step-up.',
   'FY26 revenue was approximately ₹51.40 crore and PAT ₹7.05 crore. The 18.753 million year-end shares imply market value around ₹123 crore and roughly 17.4 times FY26 earnings at ₹65.42. FY26 operating cash flow was ₹4.75 crore, against ₹49.54 crore purchases of fixed assets. Financing included ₹23.74 crore share-capital/premium proceeds and ₹19.70 crore long-term borrowing inflow. Capacity growth is partly funded, but it increases the burden of utilisation and cash conversion.',
   'Price is below the 50-day average and marginally below the measured 200-day average. A modestly priced company with an order is interesting, but delivery evidence and returns on the enlarged asset base matter more than the total award headline.'],
  red_flag='Large capital spending relative to operating cash, plus merchant-exporter execution exposure.',
  trigger='Upgrade after FY27 deliveries, collections and evidence that new capacity produces profitable sales without another funding round.',
  breaks='Capacity under-utilisation, weak exporter collections, or debt rising faster than operating earnings.',
  risks=['Capacity ramp and debt','Indirect export counterparty','SME lot sizes and liquidity'], months=15),
 dict(id='511144', company='Axis Solutions', verdict='WATCH', conviction=2,
  summary='Large water-project award; cash conversion and subcontracting economics remain the main tests.',
  evidence=['AXIS_ORDER','AXIS_ORDER_DETAIL','AXIS_FY26','AXIS_Q1'],
  paragraphs=[
   'The ₹400 crore rural-water implementation award is from NKG Primus JV, with single-village work due by March 2027 and multi-village work by March 2028. A 3% performance guarantee implies ₹12 crore. The company says roughly 38–40% is in-house engineered technology, with civil work executed through third parties. This does not mean only 40% can be recognised as revenue: it means the headline order is not all proprietary, high-margin economic content.',
   'FY26 consolidated revenue was ₹240.67 crore. Consolidated operating cash flow was negative ₹22.00 crore, following negative ₹19.90 crore in the prior year. Receivables absorbed ₹40.25 crore and other current assets ₹30.79 crore; current borrowings increased ₹43.97 crore. These are concrete funding concerns, although a funded mobilisation advance could improve the assessment.',
   'The stock is below its 50-day average. Only 137 adjusted sessions are available in the collected history, so a valid 200-day trend cannot be claimed. The old Asya Infosoft/restructuring history requires careful comparability; it does not establish that the current business is insolvent.'],
  red_flag='Two years of negative operating cash and increased borrowing to finance working capital.',
  trigger='Upgrade after mobilisation/advance receipts, guarantee funding, clear subcontract economics and collections that reduce receivable dependence.',
  breaks='Execution funded predominantly by fresh borrowing/equity while operating cash remains negative.',
  risks=['Receivables and funding','Subcontracting margins','Restructuring comparability and short price history'], months=15),
 dict(id='526614', company='Expo Engineering and Projects', verdict='WATCH', conviction=2,
  summary='ONGC award is meaningful, but low margins, inventory and negative cash flow limit conviction.',
  evidence=['EXPO_FY26','EXPO_DECK'],
  paragraphs=[
   'The company presentation identifies a ₹44.66 crore ONGC floating-roof storage-tank maintenance award at the Gandhinagar CPF, including GST. Against FY26 revenue of ₹68.23 crore, it is material; an inclusive-of-tax contract should not be divided into tax-exclusive revenue without adjustment. Order value alone does not establish incremental profit or collection timing.',
   'FY26 PAT was ₹1.74 crore and operating cash flow negative ₹6.41 crore. Inventory absorbed approximately ₹9.20 crore. The presentation shows inventory ₹49.99 crore, short-term borrowings ₹32.35 crore and cash/bank balances ₹2.96 crore. This is a thin-margin business taking on a larger execution obligation with meaningful funding needs.',
   'Price is below its 50-day average but above the 200-day average. Median trading value is only about ₹8.10 lakh per day in the measured BSE window; a ₹1 lakh position is over 12% of that. This adds a practical entry/exit constraint to the financial doubts.'],
  red_flag='Negative operating cash, high inventory and borrowings relative to the profit base.',
  trigger='Upgrade after ONGC billing/collections, a positive operating cash cycle and inventory reduction with sustainable margins.',
  breaks='Inventory and finance costs rise while order conversion fails to improve cash or profit.',
  risks=['Working capital','Thin project margins','Trading liquidity'], months=12),
 dict(id='NIBE', company='NIBE', verdict='WATCH', conviction=2,
  summary='Signed Army contract supports the opportunity; advance receipt, guarantees and recurring profitability are unproven.',
  evidence=['NIBE_CONTRACT','NIBE_Q1'],
  paragraphs=[
   'The Indian Army contract is signed and quantified at ₹563.35 crore including taxes and duties. Supply is 30 loiter-munition systems with 300 munitions and associated equipment. Delivery is in tranches within 12 months from release of the advance payment, not automatically 12 months from the announcement. A 10% performance-cum-warranty guarantee and a separate AMC guarantee are specified.',
   'The June quarter recorded a consolidated net loss of approximately ₹12.00 crore, with approximately ₹11.03 crore attributable to owners. FY26 group PAT was only about ₹0.06 crore, while owner-attributable profit was approximately ₹5.63 crore; these scopes should not be mixed. Order size is substantial, but neither its reported gross amount nor an assumed defence margin proves near-term owner earnings.',
   'The supplied BSE close of ₹1,168 is below both measured moving averages. NSE liquidity is appreciably greater than the BSE-only series, so the BSE liquidity estimate must not be presented as company-wide trading volume.'],
  red_flag='Latest-quarter losses and execution/funding dependence before a large new supply programme.',
  trigger='Upgrade on disclosed advance receipt, bank guarantees/funding, delivery acceptance and positive recurring owner earnings.',
  breaks='Advance/delivery delays, guarantee funding strain, or persistent losses despite revenue recognition.',
  risks=['Defence qualification and delivery','Advance/guarantee funding','Cash and owner-profit conversion'], months=15),
 dict(id='ITI', company='ITI', verdict='AVOID', conviction=1,
  summary='Audit/review limitations and underlying losses outweigh tiny institutional ownership changes.',
  evidence=['ITI_Q1','ITI_ANNUAL'],
  paragraphs=[
   'The C7 signal rests on very small year-on-year institutional changes: FII +0.01 percentage point and MF +0.02 point in the supplied selection. These movements do not establish a funded earnings inflection. The company’s large existing programme pipeline should not repeatedly be counted as fresh incremental orders.',
   'The June filing shows FY26 standalone profit of ₹292.79 crore after ₹449.15 crore exceptional income; before exceptional items it lost ₹156.36 crore. June standalone loss was ₹32.47 crore and consolidated loss approximately ₹32.25 crore. Underlying profitability has not been established.',
   'More seriously, the June review refers repeatedly to the FY26 auditor’s disclaimer of opinion and continuing limitations on verifying inventories, transactions and balances, as well as governance non-compliances. It reports overdue provident-fund contributions at a unit. These are concrete governance and financial-reporting concerns, not a valuation objection. Price is below both moving averages.'],
  red_flag='Auditor disclaimer/review limitations, statutory-dues issues and losses before exceptional income.',
  trigger='Reconsider after material audit limitations are resolved, statutory dues are regularised and recurring profit/cash improves.',
  breaks='Further reporting qualifications, government-support dependence or continuing underlying losses.',
  risks=['Reliability of reported accounts','Statutory dues and funding','Project billing and collections'], months=None),
 dict(id='531411', company='Tuni Textile Mills', verdict='AVOID', conviction=1,
  summary='Earnings have improved, but cash absorption, fresh share-count reset and poor liquidity block fresh entry.',
  evidence=['TUNI_ORDER','TUNI_H1','TUNI_RIGHTS'],
  paragraphs=[
   'The September textile purchase orders total approximately ₹29.5–30.2 crore and are ordinary-course business. H1 FY27 revenue rose to ₹58.50 crore from ₹52.62 crore and PAT to ₹1.52 crore from ₹0.78 crore. It would be wrong to dismiss that improvement or to call the order unquantified.',
   'However, H1 operating cash flow remained negative ₹2.73 crore after FY26 negative ₹10.19 crore. H1 receivables absorbed approximately ₹16.36 crore and inventory ₹13.70 crore, largely financed by payables. The 27 October filing confirms allotment of 469.18 million rights shares at ₹1, raising approximately ₹46.92 crore gross. Shares rise from 130.63 million to 599.81 million, about 4.59 times. Funding has improved; the earlier incomplete-rights issue concern is now stale.',
   'At the supplied ₹2.13 quote, the post-allotment share count indicates market value around ₹127.76 crore, subject to listing/tradability and quote timing. Old share-count P/E calculations are invalid, and historical chart returns need rights-aware treatment. Median trading value of only ₹2.57 lakh per day makes a ₹1 lakh trade about 39% of a typical day. The present objection is cash/earnings-per-new-share uncertainty and execution liquidity, not the prior rally.'],
  red_flag='Negative operating cash and extremely low liquidity; post-rights earnings and price comparability require recalculation.',
  trigger='Reconsider after rights shares are reflected consistently in prices/EPS, proceeds deployment is clear and collections/liquidity improve.',
  breaks='Fresh capital remains tied up in inventories/receivables without proportionate per-share earnings.',
  risks=['Cash conversion','Rights-adjusted per-share economics','Trading liquidity'], months=None),
 dict(id='538521', company='Yaan Enterprises', verdict='AVOID', conviction=1,
  summary='Quantified maize order has disclosed payment terms, but tiny profits and trading liquidity limit investability.',
  evidence=['YAAN_ORDER','YAAN_FY26','YAAN_Q1'],
  paragraphs=[
   'The ₹15.86 crore yellow-maize order is from State Agri Horticultural Development Co-operative Society, Thiruvananthapuram. The filing gives a two-month supply period, 20% advance and balance within 45 days of completion and quality certification. The order therefore has more commercial detail than the screening summary suggests; it should not be labelled anonymous or non-firm.',
   'FY26 revenue was ₹24.43 crore and PAT ₹0.78 crore. June revenue was ₹1.15 crore and PAT only ₹2.17 lakh, against finance cost ₹13.44 lakh. No disclosed order-level gross margin establishes that this large commodity turnover converts into meaningful owner earnings. Market value using the reported share count is approximately ₹48.65 crore, or about 62 times FY26 earnings.',
   'Median traded value is only approximately ₹91,000 per day in the collected BSE window. A proposed ₹1 lakh allocation exceeds that entire-day median. This is a concrete suitability problem for the UI’s equal-allocation strategy even though the price is above its measured moving averages.'],
  red_flag='Extremely low liquidity, very small latest-quarter profit and finance cost material relative to profit.',
  trigger='Reconsider after supply/collection evidence, disclosed sustainable margins and materially deeper trading liquidity.',
  breaks='The order expands turnover without improving cash earnings or exit liquidity.',
  risks=['Commodity trading margin','Working capital and collection','Trading liquidity'], months=None),
 dict(id='531911', company='Galaxy Agrico Exports', verdict='AVOID', conviction=1,
  summary='Headline award is huge against a tiny base, but exceptional income and reporting comparability obscure earnings power.',
  evidence=['GALAXY_ORDER','GALAXY_FY26','GALAXY_Q1'],
  paragraphs=[
   'The ₹10 crore commodity order is from Shrynax Trading Private Limited. Its 382% ratio comes from dividing by just ₹2.62 crore FY26 revenue. That denominator makes the headline look transformational, but it does not establish procurement funding, margin or cash realisation. Delivery is described by purchase-order terms rather than a clearly quantified public timetable.',
   'FY26 had a pre-exceptional loss of approximately ₹1.09 crore; a ₹5.25 crore exceptional credit supported reported PAT of approximately ₹3.82 crore. June revenue improved to ₹3.52 crore and PAT to about ₹0.50 crore, but other income was approximately ₹0.39 crore against PBT ₹0.68 crore. The recent improvement deserves acknowledgement, yet recurring operating earnings remain much smaller than headline profit.',
   'The reviewed result tables also do not provide a readily reconcilable current share-capital bridge. I therefore exclude automated P/E and market-cap conclusions rather than choose a convenient share count. These are accounting-comparability and earnings-quality questions; the research does not establish wrongdoing or that the order is false.'],
  red_flag='Exceptional income dominates FY26 profit, while share-capital comparability and cash economics remain unresolved.',
  trigger='Reconsider after reconciled financial/share-capital disclosures and evidence of procurement, delivery and collections at positive operating margins.',
  breaks='Profits continue to depend on exceptional/other income rather than repeat operating cash.',
  risks=['Earnings quality and comparability','Commodity counterparty/procurement','Small operating base'], months=None),
 dict(id='523732', company='Ecoboard Industries', verdict='AVOID', conviction=1,
  summary='Larger new order does not yet resolve operating losses and cash burn.',
  evidence=['ECO_FY26','ECO_Q1','ECO_NEW_ORDER'],
  paragraphs=[
   'A September filing identifies a ₹20.50 crore order from Sri Balaji Bio Energies Organics, newer and larger than the order behind the original pick. This supports business activity, but a contract amount is not evidence that it can be executed profitably and funded.',
   'FY26 revenue was ₹23.91 crore, net loss ₹10.08 crore and operating cash outflow ₹17.54 crore. June revenue was ₹11.21 crore with a further ₹3.65 crore loss. These are concrete operating and cash red flags even if headline revenue is accelerating.',
   'Price is around its 50-day average and above the 200-day average, so chart weakness is not the main objection. Median trading value is only ₹3.69 lakh per day; a ₹1 lakh allocation would represent approximately 27% of a typical day.'],
  red_flag='Persistent operating losses, substantial negative operating cash and poor trading liquidity.',
  trigger='Reconsider after positive operating contribution, funded execution and a demonstrated improvement in operating cash.',
  breaks='Revenue growth continues alongside losses and repeated capital raising.',
  risks=['Loss-making execution','Funding and dilution','Trading liquidity'], months=None),
 dict(id='SWANDEF', company='Swan Defence and Heavy Industries', verdict='AVOID', conviction=1,
  summary='Backlog and financing are real, but reported profit is a tax write-back rather than recurring earnings.',
  evidence=['SWAN_H1_RESULTS','SWAN_H1_DECK'],
  paragraphs=[
   'The company presentation describes roughly ₹6,500 crore backlog extending through FY31. The H1 balance sheet includes ₹1,150 crore NaBFID borrowing and substantial preference-share capital pending allotment. This is a funded industrial restart with long execution and capital-structure complexity; it is not a near-term conversion of the entire backlog into sales.',
   'H1 consolidated revenue was approximately ₹99.46 crore and pre-tax loss ₹38.37 crore. Headline PAT of ₹524.78 crore is explained by a ₹563.15 crore write-back of earlier tax provisions. That write-back does not establish recurring operating profitability or cash earnings. Merger/restatement changes also require like-for-like comparisons.',
   'The stock is above the measured moving averages and institutional ownership changes supported the original screen. Those positives do not resolve the loss-making earnings base. The current AVOID is for fresh entry pending operating proof, not a claim that the shipyard or backlog has no value.'],
  red_flag='Underlying pre-tax losses masked by a large tax-provision write-back, with capital-intensive multi-year execution.',
  trigger='Reconsider after delivery-linked revenue, recurring operating profit and cash conversion become visible on a comparable basis.',
  breaks='Backlog conversion is delayed while finance costs and working capital absorb cash.',
  risks=['Shipbuilding execution and funding','Non-recurring reported profit','Merger and preference-capital comparability'], months=None),
]

manifest=json.loads((SOURCE/'manifest.json').read_text())
old_manifest=json.loads((OLD/'manifest.json').read_text())
evidence={}
for r in rows:
    packet=json.loads((ROOT/(r['id']+'.json')).read_text())
    r['asof']='2026-10-28'
    r['market']=packet['market']
    r['market']['venue']=packet['exchange']
    r['one_lakh_pct_median_daily_turnover']=round(.01/r['market']['raw_turnover_median_60_cr']*100,2)
    r['thesis']=' '.join(r['paragraphs'])
    r['rerating_months']=r.pop('months')
    r['evidence_ids']=r.pop('evidence')
    for key in r['evidence_ids']:
        path=(SOURCE if (SOURCE/(key+'.pdf')).exists() else OLD)/(key+'.pdf')
        assert path.exists(), key
        evidence[key]={'path':str(path),'url':manifest.get(key,old_manifest.get(key)), 'type':'issuer/exchange original PDF'}
    assert r['market']['date']=='2026-10-27'

assert len(rows)==13 and len({r['id'] for r in rows})==13
assert {r['id'] for r in rows}=={'ITI','526775','531411','544440','538521','517417','531911','523732','526614','NIBE','511144','544554','SWANDEF'}

out={'asof':'2026-10-28','price_date':'2026-10-27','scope':'Exact 13 companies pasted from last-90-days UI; current fresh-entry research, not a historical backtest rerun.',
 'method':'v2 economic framework applied to newly assembled primary-source research packets; latest information through 28 October, not original pick-date decisions.',
 'conviction_scale':{'5':'Full position today','4':'Strong current investment case with a material open question','3':'Good opportunity with real doubts','2':'Weak current case','1':'Barely any current investment case'},
 'limitations':['Ownership/pledge verification is incomplete across these companies; absent local holdings are not zero holdings.','Benchmark-relative strength against Smallcap 250 was not verified and is unscored.','Turnover is median close times volume across the latest 60 available sessions on the stated venue, not executable order-book depth.','Some valuation inputs are June/March disclosed shares, not a separately reconciled fully diluted share register as of today.','No probability of success or expected return is inferred from these ordinal convictions.'],
 'recommendations':rows,'evidence':evidence}
(ROOT/'recommendations.json').write_text(json.dumps(out,indent=2,ensure_ascii=False))

lines=['# Research of your 13 last-90-days picks',
 'As of 28 October 2026. Reference prices: 27 October 2026. Horizon: 1–3 years. These are current fresh-entry decisions; AVOID does not constitute a researched sell instruction for an existing holding.',
 '**Updated result: 0 BUY, 7 WATCH, 6 AVOID for fresh entry. Valiant remains the strongest operating case, but its earlier BUY, 4/5 is revised to WATCH, 3/5 after explicitly testing the earnings growth needed at Rs 1,600. Cryogenic OGS and Patels Airtemp are the next research priorities, followed by KVS Castings.**',
 'I used the economic questions and conviction definitions in your v2 prompt. This is a fresh research exercise with new company/exchange filings, rather than the original masked-PDF experiment or a pick-date backtest. Historical signal rows are preserved separately. A price rally or high valuation alone does not trigger an AVOID.',
 'Conviction measures willingness to invest today: 5 = full position; 4 = strong case with one material open question; 3 = good case with real doubts; 2 = weak case; 1 = barely a current case. It is an analyst judgement, not the model confidence field, a calibrated probability or confidence in an AVOID verdict.',
 '| Company | Close ₹ | Decision | Conviction /5 | Main reason |',
 '|:--|--:|:--|--:|:--|']
for r in rows:
    lines.append(f"| {r['company']} | {r['market']['close']:,.2f} | {r['verdict']} | {r['conviction']} | {r['summary']} |")
lines+=['','## What changes the screen’s interpretation',
 'The order’s tax basis, recognised revenue scope, delivery schedule and cash funding matter more than a single order/revenue ratio. Patels’ Dangote customer and 12-month schedule are disclosed. KVS has ₹8 crore scheduled in FY27 and ₹12 crore in FY28. Valiant’s ₹40.25 crore award extends into December 2028, whereas its 27 October ₹14.76 crore supply award has an October 2027 deadline. NIBE’s clock starts on release of its advance.',
 'Tuni completed a major rights allotment on 27 October. This supplies funding but resets the share count. Old EPS, old share-count market capitalisation and price momentum not adjusted for the rights event should not be treated as comparable current investment inputs.',
 'Positive reported profit also needs decomposition. Swan’s H1 profit is driven by a tax-provision write-back; ITI’s FY26 profit includes exceptional income and the auditor’s reporting concerns remain material; Galaxy’s FY26 profit depends on an exceptional credit. Cryogenic’s plot-sale gain is smaller, but should still be normalised.',
 '## Company decisions and upgrade conditions']
for index,r in enumerate(rows,1):
    lines += [f"### {index}. {r['company']} — {r['verdict']}, {r['conviction']}/5",*r['paragraphs'],f"**Concrete concern:** {r['red_flag']}",f"**Next decision trigger:** {r['trigger']}",f"**Thesis fails if:** {r['breaks']}"]
    m=r['market']
    def fmt(n): return 'unavailable' if n is None else f'₹{n:,.2f}'
    lines.append(f"**Price context ({m['venue']}):** close {fmt(m['close'])}; 50-session mean {fmt(m.get('sma50'))}; 200-session mean {fmt(m.get('sma200'))}. These are observations, not price targets or guaranteed support.")
    refs=[]
    for key in r['evidence_ids']:
        e=evidence[key]
        refs.append(f"[{key}]({e['url'] or e['path']})")
    lines.append('**Primary evidence:** '+', '.join(refs)+'.')
    primary=evidence[r['evidence_ids'][0]]['path']
    lines.append(f':codex-file-citation{{path="{primary}" purpose="source"}}')

lines+=['## Why ₹1 lakh in every pick is problematic',
 'Daily trading value was calculated from raw close × volume, using the median of the latest 60 available sessions on the collected venue. It is a capacity indicator, not order-book depth or guaranteed liquidity. For NIBE, the supplied pick is on BSE; the NSE venue has materially greater activity and should be assessed separately.',
 '| Company | Venue | Median daily traded value ₹ lakh | ₹1 lakh as % of median day |',
 '|:--|:--|--:|--:|']
for r in sorted(rows,key=lambda x:x['market']['raw_turnover_median_60_cr']):
    m=r['market']
    lines.append(f"| {r['company']} | {m['venue']} | {m['raw_turnover_median_60_cr']*100:,.2f} | {r['one_lakh_pct_median_daily_turnover']:.1f}% |")
lines += ['A ₹1 lakh allocation exceeds Yaan’s measured median entire-day turnover and is a substantial fraction for Tuni, Ecoboard and Expo. A closing-price stop cannot ensure a sale at a 20% loss when gaps, circuit limits or an empty buy side intervene. SME market lots may also prevent the assumed exact allocation. Stops should reference actual acquisition cost and be adjusted for applicable corporate actions; sell-by dates should start from the actual entry date.',
 '## Filtering changes justified by this review',
 '1. Separate a candidate signal from an executable BUY. Keep the core combos as discovery signals, then assess concrete vetoes and investment conviction.',
 '2. Store order value excluding tax where disclosed, firm/LOI/L1 status, direct customer versus end customer, delivery start condition, delivery schedule and amendments. Estimate the next-four-quarter portion only when public scheduling supports it; otherwise mark it unknown. Deduplicate overlapping/amended awards.',
 '3. Refresh revenue denominators and label standalone versus consolidated. Show recurring operating profit, pre-exceptional PBT, owner-attributable PAT and operating cash separately. A positive reported PAT or OPM is not a substitute for cash and earnings-quality checks.',
 '4. Require a working-capital bridge for large awards: advances received, guarantee requirements, available cash excluding restricted deposits, borrowing capacity and collection milestones.',
 '5. Reconcile current shares, warrants, rights allotments and quote adjustments before calculating valuation or momentum. Flag short price histories rather than fabricate a 200-day trend.',
 '6. Link permissible position size to measured venue liquidity and market lots. Require individual review where the position would be a material part of a typical day; validate any numeric threshold before treating it as a proven return filter.',
 'These are research-based proposals. I have not changed the application, production data, trading rules or backtest, and this review does not demonstrate that the proposed filters improve historical returns.',
 '## Coverage and remaining uncertainty',
 'Reviewed 13/13 supplied names. Original issuer/exchange PDFs, extracted page text, the original signal rows and market snapshots are saved alongside this report. NIBE and Swan primary documents are reused from the earlier review and linked to their existing source files. Financial table images were inspected where extraction needed checking, including Cryogenic borrowings, Patels cash/working capital and Yaan quarterly results.',
 'The study is not a complete forensic due-diligence exercise. Current promoter/pledge trends are not independently reconciled across all 13 names; missing holdings rows do not mean zero holdings or no pledges. Benchmark-relative strength against Smallcap 250 was not verified, so it is unscored. No clean current P/E is assigned where the capital structure is unresolved or earnings are loss-making. Current market snapshots are local stored observations dated 27 October, not live exchange quotes. Reported orders are company disclosures, not independent confirmations from customers.',
 'There are no numerical price targets or promised returns. Watch-list review windows are judgemental periods for evidence to emerge, not forecast rerating dates. AVOID entries have no assigned rerating period.']
report_text=re.sub(r'(?m)(^\|.*\|)\n\n(?=\|)', r'\1\n', '\n\n'.join(lines))
(ROOT/'report.md').write_text(report_text+'\n')
(SOURCE/'verification_status.json').write_text(json.dumps({k:{'exists':Path(v['path']).exists(),'bytes':Path(v['path']).stat().st_size,'page_text_exists':Path(v['path']).with_suffix('.json').exists()} for k,v in evidence.items()},indent=2))
print(json.dumps({'companies':len(rows),'counts':{v:sum(r['verdict']==v for r in rows) for v in ['BUY','WATCH','AVOID']},'source_pdfs':len(evidence),'report':str(ROOT/'report.md')},indent=2))
