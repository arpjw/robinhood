# kalshi_fed — Kalshi Fed Rate Markets

Streams live contract prices for Federal Reserve rate target markets from Kalshi via WebSocket. Covers KXFED series contracts that track the probability of the Fed funds rate landing at each basis-point target through April 2027.

**Mapped equities:** Fed rate decisions drive bank stocks (JPM, BAC, GS, WFC), utilities (XLU), and rate-sensitive ETFs (TLT, IEF). A probability spike toward a rate hike signals bearish pressure on long-duration bonds and utility equities; a spike toward a cut is bullish for both.

**Auth:** Requires `KALSHI_API_KEY` (RSA key ID from the Kalshi dashboard) and `KALSHI_PRIVATE_KEY_PATH` (path to your RSA private key PEM file). Kalshi v2 uses RSA-PSS request signing on every API and WebSocket call.

**Transport:** WebSocket primary, with automatic REST polling fallback after 5 consecutive WebSocket failures.
