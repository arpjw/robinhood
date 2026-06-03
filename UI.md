# Robinhood Velocity Signal Engine — UI Build Plan

One prompt. Build the full landing page as a Next.js app deployable to Vercel at robinhood.aryasomu.com.

---

## Prompt 1 — Full Landing Page

```
Build a production-grade Next.js 14 landing page (App Router) for the Robinhood Velocity Signal Engine project. Deploy target is Vercel at robinhood.aryasomu.com. The page should feel like it belongs in Robinhood's 2024-2026 visual identity — but adapted for a quant research project landing page, not a brokerage product.

---

DESIGN SYSTEM

Typography:
- Display/headlines: "Robinhood Phonic" is not publicly available, so substitute with DM Serif Display (Google Fonts) for large display text — it has similar ink-trap character and precision.
- Body and UI text: "DM Mono" (Google Fonts) for all data, numbers, tickers, and code. "DM Sans" for prose body copy.
- Import both from Google Fonts in the layout.

Color palette (match Robinhood's 2024 identity exactly):
- Background: #0a0a0a (near-black, not pure black)
- Surface: #111111
- Surface elevated: #1a1a1a
- Border: #222222
- Text primary: #f5f5f5
- Text secondary: #888888
- Text tertiary: #555555
- Robin Neon (primary accent): #b3ff00 — Robinhood's exact signature yellow-green. Use for: positive values, active states, signal indicators, hover accents, key numbers.
- Red (negative): #ff4d4d
- Neutral up: #22c55e (subtle green for smaller positive values)
- Neutral down: #ef4444 (subtle red for smaller negative values)

CSS variables for everything. No hardcoded color values anywhere in components.

Spacing system: 4px base unit. Use multiples: 4, 8, 12, 16, 24, 32, 48, 64, 96, 128.

Border radius: 2px for data elements (terminal feel), 8px for cards, 0px for dividers.

---

PAGE STRUCTURE

The page has 6 sections. No page navigation needed — it is a single long-scroll page with a fixed minimal header.

HEADER (fixed, full width):
- Left: "RH // VELOCITY" in DM Mono, 13px, letter-spacing 0.15em, color text-secondary. On hover, accent neon.
- Right: two links — "GitHub" and "arya somu" — in DM Mono, 12px, text-tertiary. On hover, text-primary.
- Background: rgba(10,10,10,0.85) with backdrop-filter blur(12px).
- Bottom border: 1px solid border color.
- Height: 52px.

---

SECTION 1 — HERO

Full viewport height minus header. Left-aligned, not centered.

Layout: Two-column grid (60/40 split) on desktop, stacked on mobile.

Left column:
- Eyebrow label: "SIGNAL ENGINE v2.0" in DM Mono, 11px, color Robin Neon, letter-spacing 0.2em. Small blinking cursor after it (CSS animation, 1s interval).
- Headline: "Prediction markets move faster than equities." in DM Serif Display, 64px on desktop / 40px mobile, color text-primary, line-height 1.1. No gradient. Pure white text with weight.
- Sub-headline: "We capture the gap." — same font, 64px, color Robin Neon. This line appears 200ms after the first with a fade-up animation.
- Body: 18px DM Sans, color text-secondary, max-width 480px, margin-top 32px. Text: "When a Kalshi or Polymarket contract reprices sharply, correlated equities take minutes to catch up. This engine detects velocity spikes — Δp/Δt exceeding threshold — and submits positions via Robinhood's agentic trading MCP before the gap closes."
- Two buttons below, margin-top 40px:
  - Primary: "View on GitHub" — background Robin Neon, color #000, DM Mono 13px, letter-spacing 0.1em, padding 12px 24px, border-radius 2px, no border. On hover: brightness 110%, slight scale 1.02, transition 150ms.
  - Secondary: "Read the thesis →" — background transparent, color text-secondary, DM Mono 13px, border: 1px solid border color. On hover: border-color Robin Neon, color Robin Neon, transition 150ms.

Right column:
- A live-data terminal widget (see LIVE TERMINAL WIDGET spec below).
- Positioned slightly overlapping the fold with a subtle top margin offset to break grid rigidity.

---

LIVE TERMINAL WIDGET (used in hero section right column)

This is the most important component. It fetches real Kalshi market data and displays it live.

Container: background #111111, border 1px solid #222222, border-radius 8px, padding 0. Width 100% of column. No box shadow.

Terminal title bar: height 36px, background #1a1a1a, border-bottom 1px solid #222222, padding 0 16px. Left side: three dots (12px circles, colors #ff5f57 / #febc2e / #28c840 — macOS style). Right side: "KALSHI // LIVE" in DM Mono 11px text-tertiary.

Content area: padding 20px.

Data fetch: On mount, fetch from the Kalshi public API (no auth required for market data):
GET https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXFED&limit=5

Poll every 30 seconds. Show a subtle "●" indicator in Robin Neon in the title bar that pulses (opacity 0.4 → 1.0, 2s ease-in-out infinite) when connected.

Display for each contract:
- Ticker in DM Mono 12px text-secondary, e.g. "KXFED-27APR-T4.25"
- Yes price as a percentage in DM Mono 16px — color Robin Neon if above 50%, text-primary if below. e.g. "28.0%"
- A mini sparkline (use a simple SVG path, 60px wide, 24px tall) showing the last 5 price points if available, otherwise a flat line. Color: Robin Neon stroke, no fill.
- A delta indicator showing price change since last poll: "▲ +0.5%" in Robin Neon or "▼ -0.2%" in red. Hidden if no change.

Each row separated by a 1px border in #1a1a1a.

Below the contracts, a section labeled "SIGNAL LOG" with a 1px top border. Show 3 simulated recent signal entries (hardcoded, realistic):
- Format: "[HH:MM:SS] KXFED-27APR-T4.25  vel=0.23  →  XLF +$4.20"
- DM Mono 11px, color text-secondary. The velocity value and dollar amount in Robin Neon.
- New entries animate in from the top with a 200ms fade-up.
- Simulate a new entry appearing every 45 seconds (random realistic data).

Footer of widget: "EXECUTION MODE: MOCK  //  98 TESTS PASSING" in DM Mono 10px text-tertiary, padding 12px 20px, border-top 1px solid #222222.

---

SECTION 2 — THE SIGNAL

Background: #0a0a0a. Padding: 128px 0.

Left-aligned section label: "01 // THE SIGNAL" in DM Mono 11px Robin Neon letter-spacing 0.2em, margin-bottom 48px.

Headline: "Velocity, not probability." in DM Serif Display 48px.

Three explanation cards in a grid (3-col desktop, 1-col mobile):
Each card: background #111111, border 1px solid #222222, border-radius 8px, padding 32px. On hover: border-color #333333, transition 200ms.

Card 1 — "The Problem":
- Icon: a simple SVG clock or latency diagram in Robin Neon (24px)
- Title: "Equity markets lag." DM Serif Display 22px.
- Body: "Prediction markets are purpose-built for rapid repricing. When new information arrives, contract probabilities update in seconds. Equity prices take minutes." DM Sans 15px text-secondary line-height 1.6.

Card 2 — "The Signal":
- Icon: SVG velocity/delta symbol in Robin Neon
- Title: "Δp/Δt > 0.15" in DM Mono 22px Robin Neon.
- Body: "A probability velocity exceeding 0.15 units per minute, confirmed by a volume spike, indicates genuine information arrival — not noise. Two conditions must hold simultaneously." DM Sans 15px text-secondary.

Card 3 — "The Edge":
- Icon: SVG timer in Robin Neon
- Title: "A 2-hour window." DM Serif Display 22px.
- Body: "Positions are held until the equity market reprices or 2 hours elapse — whichever comes first. The thesis is information diffusion speed, not prediction." DM Sans 15px text-secondary.

---

SECTION 3 — ARCHITECTURE

Background: #0d0d0d (very slightly lighter than hero). Padding 128px 0.

Section label: "02 // ARCHITECTURE"

Headline: "How it works." in DM Serif Display 48px.

A full-width architecture flow diagram built in pure SVG or HTML/CSS — no images. Show the signal pipeline as a horizontal flow:

[Kalshi WS] ──► [VelocityTracker] ──► [Deduplicator] ──► [Sizer] ──► [MCPClient] ──► [Robinhood]
                                                                           │
[Polymarket WS] ──────────────────────────────────────────────────────► [ExitManager]

Styling: nodes are rectangles with 1px border #333333, background #1a1a1a, DM Mono 12px text-primary, padding 10px 16px. Connecting lines are 1px #444444. Arrows are simple SVG arrowheads in #444444. The active path highlights in Robin Neon on hover over any node — the entire upstream path lights up (CSS + JS).

Below the diagram, four stat boxes in a row (2x2 on mobile):
- "98 → 149" / "tests passing" — show the v2 test count
- "< 1s" / "WebSocket latency"
- "0.15" / "default velocity threshold"
- "2h" / "max hold time"
Each box: DM Mono for the number in 32px Robin Neon, DM Sans 13px text-secondary for the label below. No borders, just spacing.

---

SECTION 4 — STACK

Background: #0a0a0a. Padding 96px 0.

Section label: "03 // STACK"

A simple two-column list layout:
Left column header: "Signal Layer" — Right column header: "Execution Layer"
Each item: tech name in DM Mono 14px text-primary, description in DM Sans 13px text-secondary below it. No icons needed.

Signal Layer items: Kalshi REST + WebSocket, Polymarket CLOB, VelocityTracker (custom), SignalDeduplicator (custom), ConfidenceDecay (custom)
Execution Layer items: Robinhood Agentic MCP, MockMCPClient (paper trading), ExposureManager (custom), ExitManager (custom), rich dashboard (terminal UI)

---

SECTION 5 — STATUS

Background: #111111. Padding 96px 0.

Section label: "04 // STATUS"

A single wide card (full width, max 800px centered): background #1a1a1a, border 1px solid #222222, border-radius 8px, padding 48px.

Three status rows, each with a label and a status badge:
- "Signal Engine (Phase 0-1)" → badge "COMPLETE" — green background #14532d, green text #86efac, DM Mono 11px
- "Mock Execution + Backtest (Phase 1)" → badge "COMPLETE"
- "Live MCP Execution (Phase 2)" → badge "AWAITING ACCESS" — amber background #451a03, amber text #fbbf24

Below the status rows, a callout box: background #0a0a0a, border-left 3px solid Robin Neon, padding 20px 24px, margin-top 32px. Text: "Live execution requires Robinhood agentic trading account access, currently in private beta. Set EXECUTION_MODE=live only after receiving access confirmation." DM Mono 13px text-secondary.

---

SECTION 6 — FOOTER

Background: #0a0a0a. Padding 64px 0. Border-top: 1px solid #1a1a1a.

Three columns:
- Left: "RH // VELOCITY" label + "Built by Arya Somu" in DM Sans 14px text-secondary.
- Center: links — GitHub, aryasomu.com — DM Mono 12px text-tertiary, hover Robin Neon.
- Right: "v2.0 // 149 TESTS // MOCK MODE" in DM Mono 11px text-tertiary.

---

ANIMATIONS AND INTERACTIONS

Page load sequence (staggered, CSS only):
- Header fades in: 0ms delay, 300ms duration
- Hero eyebrow: 100ms delay, 400ms
- Hero headline line 1: 200ms delay, 500ms
- Hero headline line 2 (neon): 400ms delay, 500ms
- Hero body: 600ms delay, 400ms
- Hero buttons: 700ms delay, 400ms
- Terminal widget slides in from right: 500ms delay, 600ms, slight translateX(20px) → 0

All animations: ease-out cubic-bezier(0.16, 1, 0.3, 1). Use CSS @keyframes with animation-fill-mode: both so elements stay in their end state.

Scroll behavior: smooth scroll. No scroll-triggered animations needed — keep it fast.

Hover states on all interactive elements: 150ms transition on color, border-color, transform. Never use box-shadow for hover — use border-color changes only.

---

TECHNICAL REQUIREMENTS

Framework: Next.js 14 with App Router. TypeScript.

File structure:
app/
  layout.tsx       — font imports, metadata, global CSS variables
  page.tsx         — main page assembling all sections
  globals.css      — CSS custom properties, reset, base styles
components/
  Header.tsx
  HeroSection.tsx
  TerminalWidget.tsx   — the live Kalshi data component (client component, "use client")
  SignalSection.tsx
  ArchitectureSection.tsx
  StackSection.tsx
  StatusSection.tsx
  Footer.tsx

The TerminalWidget is the only client component (needs useEffect for data fetching and polling). Everything else is server components.

Metadata in layout.tsx:
- title: "Robinhood Velocity Signal Engine"
- description: "Prediction market velocity signals mapped to equity positions via Robinhood's agentic trading MCP"
- og:image: generate a simple SVG og image or skip for now

Responsive breakpoints: mobile-first. Desktop breakpoint at 1024px. Single column on mobile, two-column grids on desktop.

No external UI libraries (no shadcn, no Radix, no Tailwind). Pure CSS modules or inline styles with CSS variables. The design is custom enough that component libraries would fight against it.

No placeholder lorem ipsum anywhere. All text should be final production copy matching the descriptions above.

package.json dependencies: next, react, react-dom, typescript only. No additional packages.

Output: complete runnable Next.js project. Include a README with: "npm install && npm run dev" to run locally, and deployment instructions for Vercel (connect repo, set custom domain robinhood.aryasomu.com in Vercel dashboard).
```

---

## Notes

- After building, run locally with `npm run dev` and check: terminal widget fetches real Kalshi data, Robin Neon renders correctly on both dark backgrounds, DM Serif Display loads from Google Fonts, animations play on first load
- Deploy to Vercel: push to GitHub, import repo in Vercel dashboard, add custom domain robinhood.aryasomu.com (requires CNAME record pointing to cname.vercel-dns.com in your DNS)
- The terminal widget polls Kalshi's public API — no API key required for market data reads, only for authenticated trading operations
