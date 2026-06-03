# polymarket_macro — Polymarket Macro Markets

Streams macro prediction market prices from Polymarket's Central Limit Order Book (CLOB) via WebSocket. Covers Fed rate decisions, CPI prints, and jobs report contracts — the same event categories tracked by Kalshi, providing a cross-market velocity confirmation signal.

**Mapped equities:** KXFED → rate-sensitive banks and bonds; KXCPI → TLT, GLD, inflation-linked equities; KXJOBS → consumer discretionary, broad market.

**Auth:** No authentication required for read-only CLOB access. Set `POLYMARKET_CONDITION_IDS` to a comma-separated list of Polymarket condition IDs to track. Without this env var the connector starts but no-ops.

**Transport:** WebSocket primary with REST polling fallback. Polymarket CLOB WebSocket provides real-time price change events; REST polling fetches token prices and volume on a configurable interval.
