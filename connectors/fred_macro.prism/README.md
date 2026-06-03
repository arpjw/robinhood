# fred_macro — FRED Macro Indicators

Polls the [St. Louis Fed FRED API](https://fred.stlouisfed.org) for macroeconomic time series that are leading indicators for the events tracked by Kalshi and Polymarket contracts. This is an **alternative data connector** — FRED series are raw economic values, not probabilities. The connector normalizes each series to 0–1 using a rolling 52-week min-max window before feeding values into the velocity framework.

**Normalization approach:**

```
price_normalized = (value - rolling_min) / (rolling_max - rolling_min)
```

The rolling window holds the last 52 weekly observations. On the first observation, normalized value is 1.0. If the series is flat (max == min), normalized value is 1.0. This transforms the raw economic series into a pseudo-probability: a value near 1.0 means the indicator is near its recent historical high; a value near 0.0 means it is near its recent historical low.

A FRED velocity spike therefore represents an unusually rapid move in an economic indicator relative to its recent history — exactly the kind of signal that prediction markets will reprice on (often with a lag of hours to days).

**Default series and their meaning:**
- `FEDFUNDS`: Effective federal funds rate — maps to KXFED. Rising = more likely to hold/hike.
- `CPIAUCSL`: Consumer Price Index — maps to KXCPI. Rising = inflation pressure, bearish bonds.
- `UNRATE`: Unemployment rate — maps to KXJOBS. Rising = labor market weakening.

**Configuration:**
- `FRED_API_KEY`: free API key from [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html). **Required.**
- `FRED_SERIES`: comma-separated FRED series IDs (e.g. `"FEDFUNDS,CPIAUCSL,UNRATE"`).
- `FRED_SERIES_SLUG_MAP`: maps series IDs to contract slugs (e.g. `"FEDFUNDS:KXFED,CPIAUCSL:KXCPI,UNRATE:KXJOBS"`).
- `FRED_POLL_INTERVAL_SECONDS`: poll frequency in seconds (default 3600 — FRED updates at most daily).

**Auth:** `FRED_API_KEY` is required. Register for a free key at the FRED API documentation page — approval is instant.
