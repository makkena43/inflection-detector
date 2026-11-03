from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from inflection.parse_cache import ParsedDocumentCache
from inflection.commercial.extract import extract_document
from inflection import audit
from inflection.packets import contents as C
from test_commercial import PO
from test_packet_process_audit import setup


def test_exact_text_reuses_parse_but_changed_pages_rules_and_parser_invalidate():
    cache=ParsedDocumentCache();calls=[]
    def parse(pages):calls.append(1);return deepcopy(pages)
    source=[(1,'a'),(2,'bc')]
    assert cache.extract(source,'r1',parse)==source
    assert cache.extract(source,'r1',parse)==source and len(calls)==1
    for pages,version in [([(1,'ab'),(2,'c')],'r1'),([(2,'a'),(3,'bc')],'r1'),(list(reversed(source)),'r1'),(source,'r2')]:
        assert cache.extract(pages,version,parse)==pages
    assert len(calls)==5
    assert cache.extract(source,'r1',lambda pages:['new interpretation'])==['new interpretation']


def test_mutable_mentions_are_isolated_between_four_threads():
    cache=ParsedDocumentCache();pages=[(1,PO)]
    first=cache.extract(pages,'v1',extract_document);expected=deepcopy(first)
    first[0][0].details['accidental_change']=True
    def get(_):
        value=cache.extract(pages,'v1',extract_document)
        assert value==expected
        value[0][0].details['thread_change']=True
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(get,range(12)))
    assert cache.extract(pages,'v1',extract_document)==expected
    assert cache.stats()['hits']==13


def test_entry_and_memory_bounds_and_oversized_result_bypass():
    cache=ParsedDocumentCache(max_bytes=200,max_entries=1);calls=[]
    def parse(pages):calls.append(1);return pages
    for text in ['one','two','one']:cache.extract([(1,text)],'r',parse)
    assert len(calls)==3 and cache.stats()['entries']==1 and cache.stats()['bytes']<=200
    cache=ParsedDocumentCache(max_bytes=10,max_entries=1)
    cache.extract([(1,'large'*1000)],'r',parse)
    assert cache.stats()['entries']==0 and cache.stats()['bytes']==0


def test_uncacheable_parser_output_remains_usable():
    class LocalResult:pass
    cache=ParsedDocumentCache();calls=[]
    def parse(pages):calls.append(1);return LocalResult()
    assert isinstance(cache.extract([(1,'text')],'v1',parse),LocalResult)
    assert isinstance(cache.extract([(1,'text')],'v1',parse),LocalResult)
    assert calls==[1,1] and cache.stats()['entries']==0


def test_cold_warm_and_uncached_rechecks_produce_identical_packet_hash(db,monkeypatch):
    _,body,_,_=setup(db)
    monkeypatch.setattr(audit,'PARSED_DOCUMENTS',ParsedDocumentCache(max_bytes=0))
    baseline=audit.recheck_packet(db,body)
    cache=ParsedDocumentCache();monkeypatch.setattr(audit,'PARSED_DOCUMENTS',cache)
    cold=audit.recheck_packet(db,body);warm=audit.recheck_packet(db,body)
    assert C.content_hash(baseline)==C.content_hash(cold)==C.content_hash(warm)
    # documents already scanned under the current rules come from their stored reading, not the cache
    assert cache.stats()['hits']>0 or cache.stats()['misses']==0
