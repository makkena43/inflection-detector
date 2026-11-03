"""Bounded reuse of pure extraction from exact current page contents.

Availability, identity, cutoff and source-revision checks are never cached.
"""
from collections import OrderedDict
from hashlib import sha256
import pickle
from threading import Lock


class ParsedDocumentCache:
    def __init__(self,max_bytes=64*1024**2,max_entries=8192):
        if max_bytes<0 or max_entries<0:raise ValueError('Cache bounds cannot be negative')
        self.max_bytes=max_bytes;self.max_entries=max_entries;self._lock=Lock();self.clear()

    def clear(self):
        with self._lock:
            self._values=OrderedDict();self._bytes=0;self._hits=0;self._misses=0

    def stats(self):
        with self._lock:
            return dict(hits=self._hits,misses=self._misses,entries=len(self._values),bytes=self._bytes,max_bytes=self.max_bytes)

    def extract(self,pages,rules_version,extractor):
        if not self.max_bytes or not self.max_entries:return extractor(pages)
        digest=sha256()
        for number,text in pages:
            if type(number) is not int or number<1 or not isinstance(text,str):raise ValueError('Invalid extraction page')
            page=str(number).encode();body=text.encode('utf-8')
            digest.update(len(page).to_bytes(4,'big'));digest.update(page)
            digest.update(len(body).to_bytes(8,'big'));digest.update(body)
        key=(rules_version,extractor,digest.digest())
        with self._lock:
            blob=self._values.get(key)
            if blob is not None:self._values.move_to_end(key);self._hits+=1
            else:self._misses+=1
        if blob is not None:
            # Only trusted extractor results serialized inside this process are
            # loaded. Fresh objects isolate edits made by different packets.
            return pickle.loads(blob)
        result=extractor(pages)
        try:blob=pickle.dumps(result,protocol=5)
        except (pickle.PickleError,TypeError,AttributeError):return result
        if len(blob)<=self.max_bytes:
            with self._lock:
                previous=self._values.pop(key,None)
                if previous is not None:self._bytes-=len(previous)
                while self._values and (self._bytes+len(blob)>self.max_bytes or len(self._values)>=self.max_entries):
                    _,expired=self._values.popitem(last=False);self._bytes-=len(expired)
                self._values[key]=blob;self._bytes+=len(blob)
        return result
