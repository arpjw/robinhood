'use client'

import { useState, useEffect, useRef } from 'react'

interface KalshiMarket {
  ticker: string
  last_price: number
  yes_bid: number
  yes_ask: number
  volume?: number
}

interface MarketRow {
  ticker: string
  price: number
  prevPrice: number | null
  history: number[]
}

interface SignalEntry {
  id: string
  time: string
  ticker: string
  vel: string
  equity: string
  amount: string
  isNew?: boolean
}

const INITIAL_SIGNALS: SignalEntry[] = [
  {
    id: '1',
    time: '14:23:47',
    ticker: 'KXFED-27APR-T4.25',
    vel: '0.23',
    equity: 'XLF',
    amount: '+$4.20',
  },
  {
    id: '2',
    time: '14:18:31',
    ticker: 'KXFED-27JUN-T4.50',
    vel: '0.31',
    equity: 'TLT',
    amount: '+$2.85',
  },
  {
    id: '3',
    time: '14:09:12',
    ticker: 'KXFED-27APR-T4.00',
    vel: '0.19',
    equity: 'GLD',
    amount: '+$3.60',
  },
]

const FAKE_TICKERS = [
  'KXFED-27APR-T4.25',
  'KXFED-27JUN-T4.50',
  'KXFED-27APR-T4.00',
  'KXFED-27SEP-T5.00',
  'KXFED-27DEC-T4.75',
]
const FAKE_EQUITIES = ['XLF', 'TLT', 'GLD', 'SPY', 'BND', 'KRE', 'IYF']

function randomSignal(): SignalEntry {
  const now = new Date()
  const time = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':')
  const ticker = FAKE_TICKERS[Math.floor(Math.random() * FAKE_TICKERS.length)]
  const vel = (0.15 + Math.random() * 0.25).toFixed(2)
  const equity = FAKE_EQUITIES[Math.floor(Math.random() * FAKE_EQUITIES.length)]
  const amount = `+$${(1.2 + Math.random() * 6).toFixed(2)}`
  return { id: String(Date.now()), time, ticker, vel, equity, amount, isNew: true }
}

function sparklinePath(prices: number[]): string {
  if (prices.length < 2) return 'M 0,11 L 60,11'
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const range = max - min || 1
  const w = 60
  const h = 22
  const points = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * w
    const y = h - ((p - min) / range) * (h - 4) - 2
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return `M ${points.join(' L ')}`
}

export default function TerminalWidget() {
  const [markets, setMarkets] = useState<MarketRow[]>([])
  const [connected, setConnected] = useState(false)
  const [signals, setSignals] = useState<SignalEntry[]>(INITIAL_SIGNALS)
  const prevPricesRef = useRef<Record<string, number>>({})

  useEffect(() => {
    async function fetchMarkets() {
      try {
        const res = await fetch(
          'https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXFED&limit=5',
          { cache: 'no-store' }
        )
        if (!res.ok) throw new Error('fetch failed')
        const data = await res.json()
        const raw: KalshiMarket[] = data.markets ?? []

        setMarkets((prev) => {
          const prevMap = Object.fromEntries(prev.map((m) => [m.ticker, m]))
          return raw.map((m) => {
            const price = m.last_price ?? m.yes_bid ?? 0
            const existing = prevMap[m.ticker]
            const history = existing
              ? [...existing.history.slice(-9), price]
              : [price]
            const prevPrice = existing ? existing.price : null
            prevPricesRef.current[m.ticker] = price
            return { ticker: m.ticker, price, prevPrice, history }
          })
        })
        setConnected(true)
      } catch {
        setConnected(false)
      }
    }

    fetchMarkets()
    const iv = setInterval(fetchMarkets, 30000)
    return () => clearInterval(iv)
  }, [])

  useEffect(() => {
    const iv = setInterval(() => {
      setSignals((prev) => {
        const entry = randomSignal()
        return [entry, ...prev.slice(0, 4)]
      })
    }, 45000)
    return () => clearInterval(iv)
  }, [])

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        overflow: 'hidden',
        width: '100%',
      }}
    >
      <div
        style={{
          height: '36px',
          background: 'var(--surface-elevated)',
          borderBottom: '1px solid var(--border)',
          padding: '0 16px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <span
            style={{
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              background: '#ff5f57',
              display: 'inline-block',
            }}
          />
          <span
            style={{
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              background: '#febc2e',
              display: 'inline-block',
            }}
          />
          <span
            style={{
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              background: '#28c840',
              display: 'inline-block',
            }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {connected && (
            <span
              className="pulse-dot"
              style={{ color: 'var(--neon)', fontSize: '10px', lineHeight: 1 }}
            >
              ●
            </span>
          )}
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-tertiary)',
            }}
          >
            KALSHI // LIVE
          </span>
        </div>
      </div>

      <div style={{ padding: '20px' }}>
        {markets.length === 0 ? (
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-tertiary)',
              padding: '16px 0',
            }}
          >
            {connected === false ? 'CONNECTING TO KALSHI API...' : 'LOADING MARKETS...'}
          </div>
        ) : (
          <div>
            {markets.map((m, i) => {
              const delta = m.prevPrice !== null ? m.price - m.prevPrice : null
              const pricePct = m.price.toFixed(1)
              const isAbove50 = m.price > 50
              return (
                <div
                  key={m.ticker}
                  style={{
                    paddingTop: i === 0 ? 0 : '12px',
                    paddingBottom: '12px',
                    borderBottom: i < markets.length - 1 ? '1px solid var(--surface-elevated)' : 'none',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '12px',
                        color: 'var(--text-secondary)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {m.ticker}
                    </div>
                    {delta !== null && delta !== 0 && (
                      <div
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '11px',
                          color: delta > 0 ? 'var(--neon)' : 'var(--red)',
                          marginTop: '2px',
                        }}
                      >
                        {delta > 0 ? '▲' : '▼'} {delta > 0 ? '+' : ''}{delta.toFixed(1)}%
                      </div>
                    )}
                  </div>
                  <div style={{ flexShrink: 0 }}>
                    <svg width="60" height="24" viewBox="0 0 60 24" fill="none">
                      <path
                        d={sparklinePath(m.history)}
                        stroke="var(--neon)"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                      />
                    </svg>
                  </div>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '16px',
                      color: isAbove50 ? 'var(--neon)' : 'var(--text-primary)',
                      flexShrink: 0,
                      minWidth: '52px',
                      textAlign: 'right',
                    }}
                  >
                    {pricePct}%
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div
          style={{
            marginTop: '16px',
            paddingTop: '16px',
            borderTop: '1px solid var(--border)',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              color: 'var(--text-tertiary)',
              letterSpacing: '0.1em',
              marginBottom: '10px',
            }}
          >
            SIGNAL LOG
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {signals.map((s, i) => (
              <div
                key={s.id}
                className={i === 0 && s.isNew ? 'log-entry-new' : undefined}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-secondary)',
                  lineHeight: '1.4',
                }}
              >
                [{s.time}] {s.ticker}&nbsp;&nbsp;vel=
                <span style={{ color: 'var(--neon)' }}>{s.vel}</span>
                &nbsp;&nbsp;→&nbsp;&nbsp;{s.equity}&nbsp;
                <span style={{ color: 'var(--neon)' }}>{s.amount}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div
        style={{
          padding: '10px 20px',
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-mono)',
          fontSize: '10px',
          color: 'var(--text-tertiary)',
        }}
      >
        EXECUTION MODE: MOCK&nbsp;&nbsp;//&nbsp;&nbsp;149 TESTS PASSING
      </div>
    </div>
  )
}
