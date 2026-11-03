#!/usr/bin/env python3
"""Fetch public ICRA rationales; conservatively verify upgrades and backtest."""
import argparse
import csv
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
import pdfplumber
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = 'https://www.icra.in'
SCALE = ['D', 'C', 'B-', 'B', 'B+', 'BB-', 'BB', 'BB+', 'BBB-', 'BBB', 'BBB+', 'A-', 'A', 'A+', 'AA-', 'AA', 'AA+', 'AAA']
SHORT = ['A4', 'A4+', 'A3', 'A3+', 'A2', 'A2+', 'A1', 'A1+']
RATING = r'\[ICRA\]\s*(AAA|AA[ \t]*[+-]?|A[1-4][ \t]*\+?|A[ \t]*[+-]?|BBB[ \t]*[+-]?|BB[ \t]*[+-]?|B[ \t]*[+-]?|C|D)(?![A-Za-z0-9+-])'
SIGNALS = {'growth': r'growth|revenue|turnover', 'order_book': r'order[ -]book|backlog', 'margin': r'margin|profitability', 'capex': r'capex|capital expenditure|capacity expansion'}


def normalize(s):
    # No fuzzy or parent/subsidiary matching.
    return re.sub(r'[^a-z0-9]', '', s.lower())


def archive_rows(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    for tr in soup.select('table tbody tr'):
        cells = tr.find_all('td')
        link = tr.select_one('a[href*="ShowRationaleReport"]')
        if len(cells) < 3 or not link:
            continue
        report_date = datetime.strptime(cells[0].get_text(' ', strip=True), '%d %b %Y').date()
        url = urljoin(BASE, link['href'])
        title = link.get_text(' ', strip=True)
        result.append(dict(report_id=parse_qs(urlparse(url).query)['Id'][0], date=report_date.isoformat(), title=title, company=re.split(r'[:;]', title, maxsplit=1)[0].strip(), sector=cells[1].get_text(' ', strip=True), url=url))
    return result


def upgrade_evidence(text):
    """Explicit old/new pair in report body, corroborated by chronology section.

    Unparseable tables remain unverified; outlook revisions are never upgrades.
    """
    chronology = re.search(r'rating\s+history', text, re.I)
    if not chronology:
        return []
    history = text[chronology.start():]
    body = text[:chronology.start()]
    pairs = []
    token = re.compile(RATING, re.I)
    history_grades = {re.sub(r'\s+', '', m.group(1).upper()) for m in token.finditer(history)}
    def cluster(fragment, before=False):
        found = list(token.finditer(fragment))
        if not found:
            return []
        chosen = [found[-1] if before else found[0]]
        neighbour = found[-2] if before and len(found)>1 else (found[1] if not before and len(found)>1 else None)
        if neighbour:
            left, right = (neighbour, chosen[0]) if before else (chosen[0], neighbour)
            separator = fragment[left.end():right.start()]
            if re.fullmatch(r'\s*(?:\([^)]*\)\s*)?/\s*', separator):
                chosen.append(neighbour)
        return [re.sub(r'\s+', '', m.group(1).upper()) for m in chosen]
    for action in re.finditer(r'upgraded\s+from', body, re.I):
        left = body[max(0,action.start()-180):action.start()]
        right = body[action.end():action.end()+180]
        # Old grade must immediately follow the action, with optional PP-MLD prefix.
        if not re.match(r'\s*(?:PP-MLD\s*)?\[ICRA\]',right,re.I):
            continue
        for old in cluster(right):
            scale = SHORT if old in SHORT else SCALE
            new = next((g for g in cluster(left,True) if g in scale),None)
            if new and old in scale and scale.index(new)>scale.index(old) and {old,new} <= history_grades:
                excerpt = re.sub(r'\s+',' ',left[-120:]+action.group()+right[:100]).strip()
                pairs.append(dict(old_rating=old,new_rating=new,evidence=excerpt))
    return pairs


def pdf_upgrade_evidence(path, text):
    """Read the action column separately so instrument labels cannot split grades.

    Grade pairs are corroborated by chronology; snapshot review verifies instrument rows.
    """
    history = re.search(r'rating\s+history', text, re.I)
    if not history:
        return []
    if not re.search(r'upgraded', text[:history.start()], re.I):
        return []
    actions = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:2]:
            starts = page.search(r'Summary of rating action', case=False)
            if not starts:
                continue
            top = starts[0]['bottom']
            ends = [h['top'] for h in page.search(r'\bTotal\b|\bRationale\b', case=False) if h['top'] > top]
            bottom = min(ends) if ends else page.height - 40
            grades = [h for h in page.search(r'\[ICRA\]') if top < h['top'] < bottom]
            if grades:
                x = min(h['x0'] for h in grades)
                action = page.crop((max(0, x-1), top, page.width, bottom)).extract_text() or ''
                actions.append(action)
    pairs = upgrade_evidence('\n'.join(actions) + '\n' + text[history.start():]) if actions else []
    if not pairs:
        pairs = upgrade_evidence(text)
    # Deduplicate repeated facilities with the same grade transition.
    unique = {}
    for pair in pairs:
        unique.setdefault((pair['old_rating'],pair['new_rating']),pair)
    return list(unique.values())


class Client:
    def __init__(self, delay):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'ICRAResearchFetcher/1.0 (public rating research)'
        self.session.mount('https://', HTTPAdapter(max_retries=Retry(total=4, backoff_factor=1, status_forcelist=[404, 429, 500, 502, 503, 504], allowed_methods=['GET', 'POST'], respect_retry_after_header=True)))

    def request(self, method, url, **kwargs):
        time.sleep(self.delay)
        logging.info('%s %s', method, urljoin(BASE, url))
        r = self.session.request(method, urljoin(BASE, url), timeout=(15, 45), **kwargs)
        r.raise_for_status()
        return r

    def discover(self, start, end, cache):
        landing = self.request('GET', '/Rating/AllRatingRationales')
        token = BeautifulSoup(landing.text, 'html.parser').select_one('input[name="__RequestVerificationToken"]')
        if not token:
            raise RuntimeError('ICRA anti-forgery token missing; archive layout changed')
        cursor = start
        seen = set()
        while cursor <= end:
            stop = min(cursor + timedelta(days=6), end)
            page, fingerprints = 1, set()
            while True:
                path = cache / f'{cursor}_{stop}_{page}.html'
                if path.exists():
                    html = path.read_text()
                else:
                    html = self.request('POST', f'/Rating/GetAllRatingRational?page={page}&type=Search', data={'__RequestVerificationToken': token['value'], 'CompanyName': '', 'FromDate': cursor.strftime('%d %b %Y'), 'ToDate': stop.strftime('%d %b %Y'), 'RatingCategoryName': ''}).text
                    path.write_text(html)
                rows = archive_rows(html)
                if not rows:
                    if not re.search(r'no data|no records|no results', html, re.I):
                        raise RuntimeError(f'Unexpected empty archive response: {path}')
                    break
                fingerprint = tuple(r['report_id'] for r in rows)
                if fingerprint in fingerprints:
                    raise RuntimeError(f'Repeated archive page: {path}; refusing incomplete run')
                fingerprints.add(fingerprint)
                for row in rows:
                    if not cursor.isoformat() <= row['date'] <= stop.isoformat():
                        raise RuntimeError('ICRA returned dates outside requested range')
                    if row['report_id'] not in seen:
                        seen.add(row['report_id'])
                        yield row
                # Pagination links explicitly identify subsequent pages.
                pages = [int(a['data-page']) for a in BeautifulSoup(html, 'html.parser').select('.pagination .page-item:not(.disabled) a[data-page]')]
                if not pages or max(pages) <= page:
                    break
                page += 1
            cursor = stop + timedelta(days=1)

    def document(self, row, folder):
        path = folder / (row['report_id'] + '.pdf')
        if not path.exists():
            try:
                response = self.request('GET', f"/Rating/GetRationalReportFilePdf?Id={row['report_id']}")
            except requests.RequestException:
                html = self.request('GET', row['url']).text
                frame = BeautifulSoup(html, 'html.parser').select_one('iframe[data-pdf-url]')
                if not frame:
                    raise RuntimeError('Rationale PDF iframe missing')
                response = self.request('GET', frame['data-pdf-url'])
            if not response.content.startswith(b'%PDF'):
                raise RuntimeError('Document endpoint did not return a PDF')
            path.write_bytes(response.content)
        text_path = folder / (row['report_id'] + '.txt')
        if text_path.exists():
            text = text_path.read_text()
        else:
            with pdfplumber.open(path) as pdf:
                text = '\n'.join(page.extract_text(layout=False) or '' for page in pdf.pages)
            text_path.write_text(text)
        if len(text.strip()) < 100:
            raise RuntimeError('PDF has insufficient extractable text; OCR/manual review required')
        return path, text


def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def backtest(events, prices, as_of):
    by_symbol = {}
    for p in prices:
        day = date.fromisoformat(p['date'])
        close = float(p['adjusted_close'])
        if day <= as_of and close > 0:
            by_symbol.setdefault(p['symbol'], {})[day] = close
    result = []
    for event in events:
        series = sorted(by_symbol.get(event['symbol'], {}).items())
        # Entry next trading day avoids publication-time look-ahead.
        publication = date.fromisoformat(event['date'])
        entry = next(((d, p) for d, p in series if d > publication), None)
        for label, months in [('3M', 3), ('6M', 6), ('1Y', 12), ('2Y', 24), ('3Y', 36), ('maximum', None)]:
            row = {**event, 'horizon': label, 'status': 'missing_prices'}
            if entry:
                target = entry[0] + relativedelta(months=months) if months else as_of
                exit_point = next(((d, p) for d, p in series if d >= target), None) if months else (series[-1] if series else None)
                row.update(entry_date=entry[0].isoformat(), entry_price=entry[1], target_date=target.isoformat())
                row['status'] = 'not_matured' if target > as_of else 'missing_exit_price'
                if exit_point and exit_point[0] >= entry[0] and (not months or target <= as_of):
                    row.update(exit_date=exit_point[0].isoformat(), exit_price=exit_point[1], return_pct=round((exit_point[1] / entry[1] - 1) * 100, 4), status='ok')
            result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, default=date(2023, 1, 1))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    parser.add_argument('--output', type=Path, default=Path('output/icra'))
    parser.add_argument('--listed-map', type=Path, help='CSV: company,symbol,listed_from,listed_to (optional),alias (optional)')
    parser.add_argument('--prices', type=Path, help='CSV: symbol,date,adjusted_close; include delisted securities')
    parser.add_argument('--limit', type=int, help='Smoke run only; limits downloaded reports')
    parser.add_argument('--delay', type=float, default=1.0)
    args = parser.parse_args()
    if args.start > args.end or args.end > args.as_of or args.delay < 0 or (args.limit is not None and args.limit < 1):
        parser.error('Invalid date range, delay, or limit')
    for folder in [args.output, args.output / 'archive', args.output / 'documents']:
        folder.mkdir(parents=True, exist_ok=True)
    mappings = {}
    if args.listed_map:
        for row in load_csv(args.listed_map):
            for name in [row['company'], row.get('alias', '')]:
                if name:
                    key = normalize(name)
                    if key in mappings and mappings[key] != row:
                        raise ValueError(f'Ambiguous company mapping: {name}')
                    mappings[key] = row
    client = Client(args.delay)
    reports, upgrades, signals = [], [], []
    status, failure = 'running', ''
    def checkpoint():
        common = ['report_id', 'date', 'company', 'title', 'sector', 'url', 'pdf_path', 'sha256', 'upgrade_status', 'upgrade_evidence', 'error']
        write_csv(args.output / 'icra_all_rationales.csv', reports, common)
        write_csv(args.output / 'icra_listed_upgrades.csv', upgrades, common + ['symbol'])
        write_csv(args.output / 'icra_signals.csv', signals, ['report_id', 'date', 'company', 'url', 'signal', 'excerpt'])
        returns = backtest(upgrades, load_csv(args.prices) if args.prices else [], args.as_of)
        write_csv(args.output / 'icra_backtest.csv', returns, ['report_id', 'date', 'company', 'symbol', 'horizon', 'entry_date', 'entry_price', 'target_date', 'exit_date', 'exit_price', 'return_pct', 'status'])
        manifest = dict(status=status, failure=failure, start=str(args.start), end=str(args.end), as_of=str(args.as_of), reports=len(reports), errors=sum(r.get('upgrade_status') == 'error' for r in reports), listed_upgrades=len(upgrades), limited_run=bool(args.limit), listed_map_provided=bool(args.listed_map), prices_provided=bool(args.prices))
        (args.output / 'run_manifest.json').write_text(json.dumps(manifest, indent=2))
        return manifest

    checkpoint()
    try:
        for row in client.discover(args.start, args.end, args.output / 'archive'):
            try:
                path, text = client.document(row, args.output / 'documents')
                evidence = pdf_upgrade_evidence(path, text)
                row.update(pdf_path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), upgrade_status='verified' if evidence else 'unverified', upgrade_evidence=json.dumps(evidence), error='')
                listing = mappings.get(normalize(row['company']))
                if evidence and listing and listing['listed_from'] <= row['date'] and (not listing.get('listed_to') or row['date'] <= listing['listed_to']):
                    upgrades.append({**row, 'symbol': listing['symbol']})
                for sentence in re.split(r'(?<=[.!?])\s+|\n', text):
                    for kind, pattern in SIGNALS.items():
                        if re.search(pattern, sentence, re.I):
                            signals.append({**row, 'signal': kind, 'excerpt': sentence.strip()})
            except Exception as exc:
                logging.exception('Failed report %s', row['report_id'])
                row.update(upgrade_status='error', error=str(exc))
            reports.append(row)
            logging.info('%s %s', row['date'], row['title'])
            if args.limit and len(reports) >= args.limit:
                break
            if len(reports) % 25 == 0:
                checkpoint()
        status = 'limited' if args.limit else 'complete'
    except BaseException as exc:
        status, failure = 'failed', f'{type(exc).__name__}: {exc}'
        raise
    finally:
        manifest = checkpoint()
    print(json.dumps(manifest, indent=2))
    if manifest['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    main()
