"""Job domain logic: canonical URLs, content hashes, posting dates and windows, normalization.

Pure functions with no I/O, so every rule (deduplication keys, the 24-hour window, unknown
dates) is unit-tested in isolation. Sources live in ``app.crawlers``; persistence in
``app.services.jobs``.
"""
