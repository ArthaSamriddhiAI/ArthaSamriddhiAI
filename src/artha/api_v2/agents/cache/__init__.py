"""E1 verdict cache + manual-flag service — cluster 7 chunk 7.2.

Per FR Entry 20.3 §5.2 + cluster 7 chunk 7.2 spec, E1 is the only
agent in cluster 7 with caching enabled. Cache key shape:

    e1:{ticker}:{latest_earnings_id}:{manual_flag_id}

Three invalidation triggers per chunk 7.2 §3.2:

1. **earnings auto** — when an earnings event for ``ticker`` lands in
   the data layer, the cache row's ``earnings_id`` no longer matches
   the current latest, so the next lookup with the new key naturally
   misses (and the previous row is GC'd lazily on read or via
   :func:`repository.evict_expired`).
2. **manual flag** — analyst flips a manual flag (e.g. promoter
   pledge change, audit qualification surfaced). The shim's cache key
   carries the active manual_flag_id; flagging or clearing rotates
   the key.
3. **TTL** — any cache row older than 90 days is considered stale and
   gets evicted lazily on read.

Submodules:

- :mod:`.models` — :class:`E1VerdictCache` + :class:`E1ManualFlag` ORM
- :mod:`.repository` — async CRUD + the three invalidators
- :mod:`.manual_flag` — async manual-flag service (create / clear / lookup)
- :mod:`.backend` — :class:`CacheBackend` Protocol + DB-backed +
  null implementations
"""

from __future__ import annotations
