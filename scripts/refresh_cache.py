#!/usr/bin/env python3
"""Refresh latest price cache tables after daily pipeline run."""

import sqlite3
import sys
import time

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "artha.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

caches = [
    ("latest_stock_prices", """
        SELECT s.symbol, s.date, s.adj_close, s.volume
        FROM stock_prices s
        INNER JOIN (SELECT symbol, MAX(date) as md FROM stock_prices GROUP BY symbol) m
        ON s.symbol = m.symbol AND s.date = m.md
    """, "symbol"),
    ("latest_mf_navs", """
        SELECT n.scheme_code, n.date, n.nav
        FROM mf_navs n
        INNER JOIN (SELECT scheme_code, MAX(date) as md FROM mf_navs GROUP BY scheme_code) m
        ON n.scheme_code = m.scheme_code AND n.date = m.md
    """, "scheme_code"),
    ("latest_commodity_prices", """
        SELECT c.commodity, c.date, c.price_usd
        FROM commodity_prices c
        INNER JOIN (SELECT commodity, MAX(date) as md FROM commodity_prices GROUP BY commodity) m
        ON c.commodity = m.commodity AND c.date = m.md
    """, "commodity"),
    ("latest_crypto_prices", """
        SELECT c.coin_id, c.date, c.price_usd
        FROM crypto_prices c
        INNER JOIN (SELECT coin_id, MAX(date) as md FROM crypto_prices GROUP BY coin_id) m
        ON c.coin_id = m.coin_id AND c.date = m.md
    """, "coin_id"),
]

for name, query, idx_col in caches:
    t0 = time.time()
    c.execute(f"DROP TABLE IF EXISTS {name}")
    c.execute(f"CREATE TABLE {name} AS {query}")
    c.execute(f"CREATE INDEX idx_{name} ON {name}({idx_col})")
    conn.commit()
    c.execute(f"SELECT COUNT(*) FROM {name}")
    cnt = c.fetchone()[0]
    print(f"  {name}: {cnt} rows ({time.time()-t0:.1f}s)")

conn.close()
print("Cache refresh complete.")
