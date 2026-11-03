"""Source-qualified order-book observations; legacy raw figures remain immutable audit input."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from psycopg.types.json import Jsonb

from .asof import IST
from .commercial.extract import split_page, window_end
from .documents import publication_member_sql

EXTRACTOR_VERSION='orderbook-3'
SERIES_VERSION='orderbook-series-6'
BOOK=re.compile(r'\b(?:order\s*(?:book|backlog)|unexecuted orders?|outstanding orders?|pending orders?|backlog)\b',re.I)
INFLOW=re.compile(r'\b(?:order\s+(?:inflows?|intake|bookings?)|orders?\s+received|new\s+orders?|fresh\s+orders?)\b',re.I)
AMOUNT=re.compile(r'(?P<currency>INR|Rs\.?|₹)?\s*(?P<value>\d[\d,]*(?:\.\d+)?)\s*'
                  r'(?P<scale>crores?|cr\.?|bn|billion|mn|million|lakhs?|lacs?)\b',re.I)
FACTORS={'crore':1,'crores':1,'cr':1,'cr.':1,'bn':100,'billion':100,'mn':Decimal('.1'),
         'million':Decimal('.1'),'lakh':Decimal('.01'),'lakhs':Decimal('.01'),'lac':Decimal('.01'),'lacs':Decimal('.01')}
FOREIGN=re.compile(r'\b(?:USD|US\s*\$|EUR|GBP|AUD|CAD|JPY|CNY)\b|[$€£]',re.I)
FOREIGN_PREFIX=re.compile(r'(?:USD|US\s*\$|EUR|GBP|AUD|CAD|JPY|CNY|[$€£])\s*~?\s*$',re.I)
RUPEES=re.compile(r'\bINR\b|\bRs\.?|₹',re.I)
SEGMENT=re.compile(r'\b(?:segment|division|vertical|business unit|defen[cs]e order book|export order book|domestic order book)\b',re.I)
FORECAST=re.compile(r'\b(?:targets?|targeted|expect(?:ed|s)?(?!\s+to\s+(?:continue|execute|be executed))|'
                     r'forecast|potential|pipeline|aim(?:s|ing)?|will|shall)\b',re.I)
FISCAL=re.compile(r'\bQ[1-4]\s*(?:of\s+)?FY\s*[’\x27]?\d{2,4}(?:\s*-\s*\d{2,4})?\b|\bFY\s*[’\x27]?\d{2,4}(?:\s*-\s*\d{2,4})?\b',re.I)
END_DATE=re.compile(r'\b(?:as\s+(?:at|of|on)|ended|ending|to)\s*[:\-]?\s*'
                    r'(?P<day>\d{1,2})(?:st|nd|rd|th)?[\s/\-]+'
                    r'(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
                    r'[\s, /\-]+(?P<year>\d{4})\b',re.I)
DATE_PREFIX=r'\b(?:as\s+(?:at|of|on)|ended|ending|to)\s*[:\-]?\s*'
END_NUMERIC=re.compile(DATE_PREFIX+r'(?:(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})|'
                       r'(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{4}))\b',re.I)
END_MONTH_FIRST=re.compile(DATE_PREFIX+r'(?P<month>Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)'
                           r'\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?[,]?\s+(?P<year>\d{4})\b',re.I)


def period_basis(text):
    for name,pattern in [('NINE_MONTHS',r'nine months|9\s*months|9m\b'),
                         ('HALF_YEAR',r'half[- ]year|six months|6\s*months|h[12]\b')]:
        if re.search(pattern,text or '',re.I):return name
    quarter=bool(re.search(r'quarter|three months',text or '',re.I))
    annual=bool(re.search(r'annual|full[- ]year|(?:for|during|in) (?:the )?(?:financial |fiscal )?year\b',text or '',re.I))
    if quarter and annual:return 'UNKNOWN'
    if annual:return 'ANNUAL'
    if quarter or re.search(r'\bq[1-4]\b',text or '',re.I):return 'QUARTER'
    return 'UNKNOWN'


def reporting_dates(text,quarterly=False):
    dates=set();explicit=set()
    # A Q4 FY25 token must not also become an unrelated FY25 annual token.
    for m in FISCAL.finditer(text or ''):
        if quarterly and not m.group().upper().startswith('Q'):continue
        value=window_end(re.sub(r'\bof\s+', '',m.group(),flags=re.I).replace('’',"'"))
        if value:dates.add(value)
    for pattern in (END_DATE,END_MONTH_FIRST):
        for m in pattern.finditer(text or ''):
            try:explicit.add(date(int(m['year']),list(calendar.month_abbr).index(m['month'][:3].title()),int(m['day'])))
            except ValueError:continue
    for m in END_NUMERIC.finditer(text or ''):
        try:explicit.add(date(int(m['year'] or m['y']),int(m['month'] or m['m']),int(m['day'] or m['d'])))
        except ValueError:continue
    return explicit or dates


def _scope(text):
    if re.search(r"\b(?:customer['’]s|customers['’]|client['’]s|industry|sector)\s+(?:\w+\s+){0,2}order\s*book",text,re.I):
        return 'THIRD_PARTY'
    if SEGMENT.search(text):return 'SEGMENT'
    if re.search(r'\bstandalone\b',text,re.I):return 'STANDALONE'
    if re.search(r'\bconsolidated\b',text,re.I):return 'CONSOLIDATED'
    return 'COMPANY'


def extract_points(body,*,published=None,title='',context='',source_complete=True):
    """Extract amounts with explicit currency and source-dated periods. Unknown periods stay NULL."""
    observations=[];issues=Counter()
    currency_context=body+' '+context
    inherited_inr=bool(RUPEES.search(currency_context) and not FOREIGN.search(currency_context))
    snippets=[part.strip() for sentence in split_page(1,body)
              for part in re.split(r';|\bwhereas\b|\bwhile\b|\band\s+(?=(?:the\s+)?(?:annual|quarterly|Q[1-4]\b))',sentence.text,flags=re.I)
              if part.strip()]
    for text in snippets:
        if text.endswith('?') or re.search(r'\bsafe harbou?r\b|forward[- ]looking statements',text,re.I):continue
        for kind,rx in [('BOOK',BOOK),('INFLOW',INFLOW)]:
            cue=rx.search(text)
            if not cue:continue
            if re.search(r'\b(?:IPO|public issue|share subscription)\s+(?:\w+\s+){0,3}order\s*book\b',text,re.I):
                issues['NON_OPERATING_BOOK']+=1;continue
            if kind=='BOOK' and cue.group().lower()=='backlog' and not (
                re.search(r'\borders?\b|\b(?:firm|executable|confirmed|project)\s+backlog\b',text,re.I)
                or re.search(r'\border\s*(?:book|backlog)\b',title,re.I)):
                issues['UNTYPED_BACKLOG']+=1;continue
            amounts=[]
            for m in AMOUNT.finditer(text):
                if not (-80<=m.start()-cue.start() and m.start()-cue.end()<=80):continue
                prefix=text[:m.start()]
                if FOREIGN_PREFIX.search(prefix):issues['FOREIGN_CURRENCY']+=1;continue
                if prefix.rstrip().endswith('-'):issues['NEGATIVE_AMOUNT']+=1;continue
                if not m['currency'] and not inherited_inr:issues['CURRENCY_UNVERIFIED']+=1;continue
                value=Decimal(m['value'].replace(',',''))*Decimal(FACTORS[m['scale'].lower()])
                distance=m.start()-cue.end() if m.start()>=cue.end() else cue.start()-m.start()+20
                amounts.append((distance,value,m.start()))
            if not amounts:continue
            _,value,amount_start=min(amounts)
            basis='POINT_IN_TIME' if kind=='BOOK' else period_basis(text)
            quarterly=basis=='QUARTER'
            inherited=reporting_dates(title+' '+context,quarterly=quarterly)
            inherited_date=next(iter(inherited)) if len(inherited)==1 else None
            local_dates=reporting_dates(text,quarterly=quarterly)
            named=set(re.findall(r'\b(?:quarter\s*([1-4])|q([1-4])|(first|second|third|fourth)\s+quarter)\b',text,re.I))
            if len(named)>1:local_dates={None,date.min}   # "quarter 1 was ... quarter 2 was": which is which is not stated
            end=next(iter(local_dates)) if len(local_dates)==1 else (inherited_date if not local_dates else None)
            quality='VERIFIED'
            if end is None:quality='UNVERIFIED_PERIOD'
            elif end.month not in (3,6,9,12) or end.day!=calendar.monthrange(end.year,end.month)[1]:quality='UNVERIFIED_PERIOD'
            elif published and end>published.astimezone(IST).date():quality='FUTURE_PERIOD'
            qualifier=text[max(0,amount_start-30):amount_start]
            amount_basis='EXACT'
            if re.search(r'<=?\s*$|\b(?:up to|at most|less than|no more than|below)\s*$',qualifier,re.I):amount_basis='UPPER_BOUND'
            elif re.search(r'>=?\s*$|\b(?:at least|more than|over|above|exceeding|exceeded|exceeds|crossed)\s*$',qualifier,re.I):amount_basis='LOWER_BOUND'
            elif re.search(r'~\s*$|\b(?:approximately|around|about)\s*$',qualifier,re.I):amount_basis='APPROXIMATE'
            if amount_basis in ('UPPER_BOUND','LOWER_BOUND'):quality='BOUND_NOT_COMPARABLE'
            scope=_scope(text)
            if scope in ('SEGMENT','THIRD_PARTY'):quality='SEGMENT_ONLY'
            clause_start=max(text.rfind(',',0,cue.start())+1,cue.start()-100,0)
            if FORECAST.search(text[clause_start:max(cue.end(),amount_start)]):quality='FORECAST_OR_PIPELINE'
            if not source_complete and quality in ('VERIFIED','UNVERIFIED_PERIOD'):quality='PARTIAL_SOURCE'
            if basis=='UNKNOWN' and quality=='VERIFIED':quality='UNVERIFIED_PERIOD'
            observations.append(dict(kind=kind,period_end=end,period_basis=basis,amount_cr=value,
                currency='INR',scope=scope,quality=quality,quote=text,
                metadata=dict(period_from='SENTENCE' if local_dates else 'DOCUMENT_CONTEXT',
                              source_complete=source_complete,amount_basis=amount_basis)))
    return observations,dict(issues)


def scan(conn,start,end,publication_ids=None,limit=None):
    """Read new/changed available source text; checkpoint each publication independently."""
    if publication_ids==[]:return dict(scanned=0,inserted=0)
    from .orderbook import CATS
    lo=datetime.combine(start,datetime.min.time(),IST)
    hi=datetime.combine(end+timedelta(days=1),datetime.min.time(),IST)
    # Source membership is publication-specific: a direct PDF never inherits ZIP siblings.
    rows=conn.execute(f'''SELECT p.publication_id,p.issuer_id,p.published_at,p.title,
         p.processing_issues,a.text_artifact_id,a.status,a.text_sha256,p.ingested_at,a.created_at,root.document_version_id
       FROM document_publications p JOIN document_versions root USING(document_version_id)
       JOIN document_versions member ON {publication_member_sql('root','member')}
       JOIN LATERAL (SELECT * FROM text_artifacts a WHERE a.document_version_id=member.document_version_id
          AND a.status IN ('COMPLETE','PARTIAL') ORDER BY a.created_at DESC,a.text_artifact_id DESC LIMIT 1) a ON true
       WHERE p.issuer_id IS NOT NULL AND (%s::uuid[] IS NOT NULL OR lower(p.original_category)=ANY(%s))
         AND p.published_at>=%s AND p.published_at<%s
         AND (%s::uuid[] IS NULL OR p.publication_id=ANY(%s::uuid[]))
       ORDER BY p.published_at,p.publication_id,a.text_artifact_id''',(publication_ids,CATS,lo,hi,publication_ids,publication_ids)).fetchall()
    groups=defaultdict(list)
    for row in rows:groups[row[0]].append(row)
    cached=dict(conn.execute('''SELECT publication_id,input_fingerprint FROM orderbook_scans
                WHERE extractor_version=%s AND publication_id=ANY(%s::uuid[])''',
                (EXTRACTOR_VERSION,list(groups))).fetchall()) if groups else {}
    counts=Counter();issue_counts=Counter()
    for pid,parts in groups.items():
        fingerprint=hashlib.sha256(json.dumps([
            x.astimezone(timezone.utc).isoformat() if isinstance(x,datetime) else str(x)
            for row in parts for x in row],sort_keys=True).encode()).hexdigest()
        if cached.get(pid)==fingerprint:continue
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('orderbook:'+str(pid),))
            previous=conn.execute('SELECT input_fingerprint,source_document_version_id,available_at FROM orderbook_scans WHERE publication_id=%s AND extractor_version=%s',
                                  (pid,EXTRACTOR_VERSION)).fetchone()
            if previous and previous[0]==fingerprint:continue
            observations=[];problems=Counter()
            publication_complete=all(row[6]=='COMPLETE' and not row[4] for row in parts)
            if not publication_complete:problems['PARTIAL_SOURCE']+=1
            available=parts[0][2]
            if previous:
                available=max(available,previous[2])
                if previous[1]!=parts[0][10]:available=max(available,parts[0][8] or datetime.now(timezone.utc))
            for _,issuer,published,title,processing_issues,tid,status,_,ingested,created,root_version in parts:
                pages=conn.execute('SELECT page_no,body FROM text_pages WHERE text_artifact_id=%s ORDER BY page_no',(tid,)).fetchall()
                context=' '.join(body for _,body in pages[:2])[:2000]
                for page,body in pages:
                    found,issues=extract_points(body,published=published,title=title or '',context=context,
                                               source_complete=publication_complete)
                    problems.update(issues)
                    for observation in found:
                        observation.update(text_artifact_id=str(tid),page_no=page)
                        observation['metadata'].update(source_ingested_at=ingested.isoformat() if ingested else None,
                            text_created_at=created.isoformat(),source_document_version_id=str(root_version))
                        observations.append(observation)
            for o in observations:
                digest=hashlib.sha256(json.dumps(o,sort_keys=True,default=str).encode()).hexdigest()
                n=conn.execute('''INSERT INTO orderbook_observations(issuer_id,publication_id,text_artifact_id,page_no,
                      kind,period_end,period_basis,amount_cr,currency,scope,quality,published_at,quote,metadata,
                      extractor_version,input_fingerprint,content_hash)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING''',(parts[0][1],pid,o['text_artifact_id'],o['page_no'],o['kind'],o['period_end'],
                    o['period_basis'],o['amount_cr'],o['currency'],o['scope'],o['quality'],available,o['quote'],
                    Jsonb(o['metadata']),EXTRACTOR_VERSION,fingerprint,digest)).rowcount
                counts['inserted']+=n;counts[o['quality']]+=1
            values=(pid,EXTRACTOR_VERSION,fingerprint,parts[0][10],available,
                    'SCANNED' if observations else 'NO_MATCH',len(observations),Jsonb(dict(problems)))
            conn.execute('''INSERT INTO orderbook_scan_history(publication_id,extractor_version,input_fingerprint,
                 source_document_version_id,available_at,status,observations,issues) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',values)
            conn.execute('''INSERT INTO orderbook_scans(publication_id,extractor_version,input_fingerprint,
                 source_document_version_id,available_at,status,observations,issues)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(publication_id,extractor_version) DO UPDATE
                 SET input_fingerprint=EXCLUDED.input_fingerprint,status=EXCLUDED.status,
                     source_document_version_id=EXCLUDED.source_document_version_id,available_at=EXCLUDED.available_at,
                     observations=EXCLUDED.observations,issues=EXCLUDED.issues,scanned_at=clock_timestamp()''',values)
            issue_counts.update(problems);counts['scanned']+=1
        if limit and counts['scanned']>=limit:break
    return dict(counts)|dict(issues=dict(issue_counts))


def effective_points(conn,issuer_id,cutoff=None,mode='PUBLIC_INFORMATION_RECONSTRUCTION',verified_only=False):
    """One eligible reading per source, followed by latest credible source per period/duration."""
    if cutoff is None:cutoff=datetime.now(timezone.utc)
    actual=mode=='ACTUAL_SYSTEM_REPLAY'
    rows=conn.execute('''SELECT o.kind,o.period_end,o.period_basis,o.amount_cr,o.scope,o.quality,o.published_at,
          o.publication_id,o.quote,o.text_artifact_id,o.page_no,o.recorded_at
        FROM orderbook_observations o JOIN LATERAL (
            SELECT s.input_fingerprint FROM orderbook_scan_history s WHERE s.publication_id=o.publication_id
             AND s.extractor_version=o.extractor_version AND s.available_at<=%s
             AND (NOT %s OR s.scanned_at<=%s) ORDER BY s.scanned_at DESC,s.scan_id DESC LIMIT 1) s ON true
        JOIN document_publications p USING(publication_id) LEFT JOIN text_artifacts t USING(text_artifact_id)
        WHERE o.issuer_id=%s AND o.extractor_version=%s AND o.input_fingerprint=s.input_fingerprint
          AND o.published_at<=%s
          AND (NOT %s OR (o.recorded_at<=%s AND (o.metadata->>'source_ingested_at')::timestamptz<=%s
                         AND (o.metadata->>'text_created_at')::timestamptz<=%s))''',
        (cutoff,actual,cutoff,issuer_id,EXTRACTOR_VERSION,cutoff,actual,cutoff,cutoff,cutoff)).fetchall()
    points=[dict(kind=k,period_end=e,period_basis=b,amount_cr=Decimal(v),scope=sc,quality=q,published_at=at,
                 publication_id=str(pid),quote=quote,text_artifact_id=str(tid),page_no=page)
            for k,e,b,v,sc,q,at,pid,quote,tid,page,_ in rows]
    legacy=conn.execute('''SELECT f.kind,f.quarter_end,f.amount_cr,f.published_at,f.publication_id,f.sentence,
             f.extractor_version,p.title
        FROM order_book_figures f JOIN document_publications p USING(publication_id)
        WHERE f.issuer_id=%s AND f.published_at<=%s
          AND f.extractor_version IN ('orderbook-1','orderbook-2','haiku-check-1')
          AND (NOT %s OR (f.recorded_at<=%s AND p.ingested_at<=%s))
          AND NOT EXISTS(SELECT 1 FROM orderbook_scan_history s WHERE s.publication_id=f.publication_id
             AND s.extractor_version=%s AND s.available_at<=%s AND (NOT %s OR s.scanned_at<=%s))
        ORDER BY f.published_at,f.figure_id''',(issuer_id,cutoff,actual,cutoff,cutoff,EXTRACTOR_VERSION,cutoff,actual,cutoff)).fetchall()
    source={}
    for kind,end,value,pub,pid,quote,version,title in legacy:
        key=(str(pid),kind)
        rank={'orderbook-1':0,'orderbook-2':1,'haiku-check-1':2}[version]
        if key not in source or rank>=source[key][0]:source[key]=(rank,(kind,end,value,pub,pid,quote,version,title))
    for _,(kind,end,value,pub,pid,quote,version,title) in source.values():
        if Decimal(value)==0 and version=='haiku-check-1':continue  # correction belongs only to this source
        parsed,_=extract_points(quote,published=pub,title=title or '')
        matched=[p for p in parsed if p['kind']==kind]
        matched=[p for p in matched if p['amount_cr']==Decimal(value)]
        if not matched:continue  # Do not relabel an unsupported legacy currency/amount as INR.
        q=matched[0]
        points.append(dict(kind=kind,period_end=q['period_end'] or end,period_basis=q['period_basis'],
             amount_cr=Decimal(value),scope=q['scope'],quality=q['quality'],published_at=pub,publication_id=str(pid),
             quote=quote,legacy_inferred_period=q['period_end'] is None))
    # Multiple differing figures for the same source and reporting basis require
    # verification. Do not hide the conflict by picking the largest number.
    grouped=defaultdict(list)
    for p in points:
        if re.search(r'\b(?:inclusive of|including|incl\.?)\s+(?:all\s+)?(?:gst|taxes|tax|duties)\b',p['quote'],re.I):
            p=dict(p,quality='UNVERIFIED_TAX_BASIS')
        if p['quality'] in ('FORECAST_OR_PIPELINE','SEGMENT_ONLY','FUTURE_PERIOD'):continue
        if p['period_end'] is None or p['period_end']>cutoff.astimezone(IST).date():continue
        grouped[(p['publication_id'],p['kind'],p['period_end'],p['period_basis'],p['scope'])].append(p)
    per_source=[]
    for group in grouped.values():
        eligible=[p for p in group if p['quality']=='VERIFIED']
        pool=eligible or group
        selected=pool[0].copy()
        if len({p['amount_cr'] for p in pool})>1:selected['quality']='CONFLICTING_VALUES'
        per_source.append(selected)
    # Several filings state the same period. The figure most of them agree on wins over a lone later one:
    # Skipper's Q2 FY25 release, presentation and results all say 1,660 crore; a call a week later recalls
    # "quarter 1 was ... only about INR700 crores", which the rules date to Q2.
    support=Counter((p['kind'],p['period_end'],p['period_basis'],p['scope'],p['amount_cr'])
                    for p in per_source if p['quality']=='VERIFIED')
    chosen={}
    for p in per_source:
        key=(p['kind'],p['period_end'],p['period_basis'],p['scope'])
        rank=(p['quality']=='VERIFIED',support[key+(p['amount_cr'],)],p['published_at'],p['publication_id'])
        if key not in chosen or rank>chosen[key][0]:chosen[key]=(rank,p)
    out=[]
    for _,p in chosen.values():
        equivalent=[x for x in per_source if x['quality']=='VERIFIED' and
            all(x[k]==p[k] for k in ('kind','period_end','period_basis','amount_cr','scope'))]
        first=min(equivalent,key=lambda x:x['published_at']) if equivalent else p
        p['first_published_at']=first['published_at']
        p['first_publication_id']=first['publication_id']
        p['fingerprint']=hashlib.sha256('|'.join(str(p[k]) for k in ('kind','period_end','period_basis','amount_cr','scope')).encode()).hexdigest()
        out.append(p)
    comparable=defaultdict(list)
    for p in out:
        if p['quality']=='VERIFIED':comparable[(p['kind'],p['period_basis'],p['scope'])].append(p)
    for group in comparable.values():
        group.sort(key=lambda p:p['period_end'])
        for before,current,after in zip(group,group[1:],group[2:]):
            value=current['amount_cr'];neighbours=[before['amount_cr'],after['amount_cr']]
            if value<min(neighbours)*Decimal('.5') or value>max(neighbours)*2:
                current['quality']='OUTLIER_REQUIRES_REVIEW'
    if verified_only:out=[p for p in out if p['quality']=='VERIFIED']
    return sorted(out,key=lambda p:(p['period_end'],p['kind'],p['period_basis']))


def awards_totals(conn,issuer_id,cutoff,mode='PUBLIC_INFORMATION_RECONSTRUCTION'):
    """Grounded firm awards counted once at first commitment, not a repeated update date."""
    from .commercial import vocabulary as V
    from .commercial.extract import extract_document
    actual=mode=='ACTUAL_SYSTEM_REPLAY'
    from .temporal import future_event_parent_sql
    from .commercial.readings import ready_sql
    from .commercial.readings import superseded_sql
    withdrawn=superseded_sql('support.text_artifact_id','e.rules_version','e.issuer_id','e.event_id',
        '%(version)s','%(at)s',"CASE WHEN %(actual)s THEN %(at)s ELSE 'infinity'::timestamptz END")
    rows=conn.execute(f'''SELECT latest.magnitude,latest.magnitude_currency,latest.magnitude_scale,
          latest.commercial_stage,latest.observation_status,latest.amount_basis,latest.ownership_scope,
          latest.details,first_firm.published_at,
          ARRAY(SELECT l.quote FROM evidence_links l WHERE l.event_version_id=first_firm.event_version_id
                AND l.relation='SUPPORTS' AND l.published_at<=%(at)s),{future_event_parent_sql('latest')}
        FROM events e
        JOIN LATERAL (SELECT * FROM event_versions v WHERE v.event_id=e.event_id
             AND v.published_at<=%(at)s AND (NOT %(actual)s OR v.recorded_at<=%(at)s)
             ORDER BY v.published_at DESC NULLS LAST, v.version_no DESC LIMIT 1) latest ON true
        JOIN LATERAL (SELECT * FROM event_versions v WHERE v.event_id=e.event_id
             AND v.published_at<=%(at)s AND v.commercial_stage='BINDING_DEMAND'
             AND v.observation_status='OBSERVED' AND v.amount_basis IN ('FIRM','EXECUTABLE_RELEASE','GUARANTEED_MINIMUM')
             AND (NOT %(actual)s OR v.recorded_at<=%(at)s)
             ORDER BY v.published_at,v.version_no LIMIT 1) first_firm ON true
        JOIN LATERAL (SELECT cs.rules_version FROM evidence_links l
             JOIN text_artifacts t ON t.text_artifact_id=l.text_artifact_id
             JOIN text_artifacts reading ON reading.document_version_id=t.document_version_id
             JOIN commercial_scans cs ON cs.text_artifact_id=reading.text_artifact_id
             JOIN document_publications p ON p.publication_id=l.publication_id
             WHERE l.event_version_id=first_firm.event_version_id AND l.relation='SUPPORTS'
               AND cs.issuer_id=e.issuer_id
               AND {ready_sql('cs', "CASE WHEN %(actual)s THEN %(at)s ELSE 'infinity'::timestamptz END")}
               AND (reading.text_artifact_id=t.text_artifact_id OR reading.status='COMPLETE')
               AND (reading.created_at,reading.text_artifact_id)>=(t.created_at,t.text_artifact_id)
               AND (NOT %(actual)s OR (cs.scanned_at<=%(at)s AND p.ingested_at<=%(at)s AND reading.created_at<=%(at)s))
             ORDER BY (cs.rules_version=%(version)s) DESC,reading.created_at DESC,cs.scanned_at DESC LIMIT 1) effective ON true
        WHERE e.issuer_id=%(issuer)s AND e.event_type='ORDER' AND e.rules_version=effective.rules_version
          AND NOT EXISTS(SELECT 1 FROM evidence_links support WHERE support.event_version_id=latest.event_version_id
            AND support.relation='SUPPORTS' AND {withdrawn})
          AND first_firm.published_at>=%(since)s''',dict(issuer=issuer_id,at=cutoff,since=cutoff-timedelta(days=730),
             actual=actual,version=V.RULES_VERSION)).fetchall()
    current=previous=Decimal(0)
    for amount,currency,scale,stage,observation,basis,scope,details,first,quotes,history_conflict in rows:
        if history_conflict or (details or {}).get('ocr_verification_required'):return None,None
        details=details or {}
        if (amount is None or currency!='INR' or stage not in ('BINDING_DEMAND','COMMERCIAL_SHIPMENT','REPEAT_SHIPMENT')
            or observation!='OBSERVED' or basis not in ('FIRM','EXECUTABLE_RELEASE','GUARANTEED_MINIMUM')
            or scope=='JOINT_VENTURE' or details.get('relationship')=='CONFIRMED_RELATED'
            or details.get('tax_basis')=='INCLUSIVE'
            or any(details.get(k) for k in ('aggregate_order_total','mixed_commitment','relationship_conflict'))
            or (details.get('ambiguous_with') and not details.get('distinct_marker'))):continue
        from .units import Scale
        value=Decimal(amount)*Scale(scale).factor/Decimal(10**7)
        grounded=False
        for quote in quotes:
            if V.PERIOD_INFLOW.search(quote) or V.MULTI_AWARD.search(quote) or V.ORDER_BOOK.search(quote):continue
            for mention in extract_document([(1,quote)])[0]:
                if (mention.family=='ORDER' and mention.amount and mention.amount.currency=='INR'
                    and mention.amount.to_base()/Decimal(10**7)==value
                    and mention.amount_basis in ('FIRM','EXECUTABLE_RELEASE','GUARANTEED_MINIMUM')
                    and not mention.details.get('mixed_commitment')):grounded=True
        if not grounded:continue
        if first>=cutoff-timedelta(days=365):current+=value
        else:previous+=value
    return float(current),float(previous)
