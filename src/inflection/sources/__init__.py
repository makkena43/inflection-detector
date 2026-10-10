"""Exchange source adapters (NSE, BSE) and attachment download.

Ported from MakroGraph at b31bdd0: ``fetcher/nse_fetcher.py``, ``fetcher/bse_fetcher.py`` and
``IntelligencePipeline.run_pdf_fetch_india`` (see docs/reuse_inventory.md).  Plain HTTP only:
the curl_cffi impersonation and Playwright/Selenium cookie harvesting are not ported, and a
blocked or empty response is reported as such rather than read as "no filings".
"""
