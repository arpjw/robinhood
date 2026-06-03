# metaculus_macro — Metaculus Macro Questions

Polls [Metaculus](https://www.metaculus.com) for community probability on macro-relevant forecasting questions. Metaculus aggregates predictions from a large base of quantitatively-oriented forecasters, making it a high-quality signal for events like Fed rate decisions, recession probability, and CPI outcomes.

**Why velocity spikes here are rare but high-conviction:** Metaculus questions update slowly — the community median probability shifts only when many forecasters revise their estimates. Unlike active prediction markets, this happens in response to genuine new information (an economic data release, a Fed speech, a geopolitical event). A velocity spike in Metaculus almost always precedes a Kalshi or Polymarket reprice.

**Configuration:**
- `METACULUS_QUESTION_IDS`: comma-separated Metaculus question IDs to track (e.g. `"12345,67890"`). If not set, the connector starts but no-ops.
- `METACULUS_SLUG_MAP`: maps question IDs to contract slugs (e.g. `"12345:KXFED,67890:KXCPI"`). Questions without a mapping are skipped.
- `METACULUS_POLL_INTERVAL_SECONDS`: poll frequency in seconds (default 300).

**Auth:** No authentication required. Metaculus public API endpoints return question data including community probability without a key.

**Mapped equities:** KXFED → banks, bonds, utilities; KXCPI → TLT, GLD, inflation equities; KXJOBS → consumer discretionary.
