# manifold_macro — Manifold Markets Macro

Polls [Manifold Markets](https://manifold.markets) for binary market probabilities on US macro questions. Manifold uses play money (mana) but has surprisingly accurate calibration on economic forecasting questions — its markets often move faster than Kalshi because participation barriers are lower.

**Why Manifold velocity can lead Kalshi:** Because Manifold has no real-money barrier to entry, retail forecasters reprice quickly on news. A velocity spike on a Manifold market frequently precedes the same move on Kalshi by 15–60 minutes. Use this connector as an early-warning layer alongside Kalshi.

**Configuration:**
- `MANIFOLD_MARKET_IDS`: comma-separated Manifold market slugs to track (e.g. `"will-the-fed-cut-rates-in-2026,will-us-cpi-exceed-3-in-2026"`). If not set, the connector starts but no-ops.
- `MANIFOLD_SLUG_MAP`: maps Manifold market slugs to contract slugs (e.g. `"will-the-fed-cut-rates-in-2026:KXFED"`). Markets without a mapping are skipped.
- `MANIFOLD_POLL_INTERVAL_SECONDS`: poll frequency in seconds (default 120).

**Auth:** No authentication required. Manifold API is fully public for read access.

**Mapped equities:** KXFED → rate-sensitive banks and bonds; KXCPI → inflation-linked ETFs; KXJOBS → broad market, consumer discretionary; KXBTC → crypto-adjacent equities.
