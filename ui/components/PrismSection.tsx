'use client'

import { useState } from 'react'

const CONNECTORS = [
  {
    slug: 'kalshi_fed',
    name: 'Kalshi Fed Markets',
    transport: 'WS',
    description:
      'Streams KXFED contract prices via WebSocket. Five contracts tracking Fed funds rate targets through April 2027.',
    meta: '5 contracts  ·  Auth required  ·  v1.0.0',
    builtIn: true,
    custom: false,
  },
  {
    slug: 'polymarket_macro',
    name: 'Polymarket Macro',
    transport: 'WS',
    description:
      "Streams macro prediction market prices from Polymarket's CLOB via WebSocket. Covers Fed, inflation, and economic event contracts.",
    meta: '3 contracts  ·  No auth  ·  v1.0.0',
    builtIn: true,
    custom: false,
  },
  {
    slug: 'metaculus_macro',
    name: 'Metaculus Macro Questions',
    transport: 'REST',
    description:
      'Polls Metaculus for expert-aggregated probability on macro questions. Low frequency, high conviction — velocity spikes here are rare but informative.',
    meta: '3 contracts  ·  No auth  ·  v1.0.0',
    builtIn: true,
    custom: false,
  },
  {
    slug: null,
    name: 'Your Connector',
    transport: null,
    description:
      'Any data source. One interface. Drop a .prism package into connectors/ and the engine loads it automatically.',
    meta: null,
    builtIn: false,
    custom: true,
  },
]

const CODE_LINES = [
  { text: 'class MyConnector(PrismConnector):', tokens: [{ type: 'kw', t: 'class' }, { type: 'plain', t: ' MyConnector(PrismConnector):' }] },
  { text: '    metadata = PrismMetadata(', tokens: [{ type: 'plain', t: '    metadata = PrismMetadata(' }] },
  { text: '        name="My Data Source",', tokens: [{ type: 'plain', t: '        name=' }, { type: 'str', t: '"My Data Source"' }, { type: 'plain', t: ',' }] },
  { text: '        slug="my_source",', tokens: [{ type: 'plain', t: '        slug=' }, { type: 'str', t: '"my_source"' }, { type: 'plain', t: ',' }] },
  { text: '        source_type="prediction_market",', tokens: [{ type: 'plain', t: '        source_type=' }, { type: 'str', t: '"prediction_market"' }, { type: 'plain', t: ',' }] },
  { text: '        transport="rest",', tokens: [{ type: 'plain', t: '        transport=' }, { type: 'str', t: '"rest"' }, { type: 'plain', t: ',' }] },
  { text: '        auth_fields=["MY_API_KEY"],', tokens: [{ type: 'plain', t: '        auth_fields=[' }, { type: 'str', t: '"MY_API_KEY"' }, { type: 'plain', t: '],' }] },
  { text: '        contract_slugs=["KXFED"],', tokens: [{ type: 'plain', t: '        contract_slugs=[' }, { type: 'str', t: '"KXFED"' }, { type: 'plain', t: '],' }] },
  { text: '    )', tokens: [{ type: 'plain', t: '    )' }] },
  { text: '', tokens: [] },
  { text: '    async def start(self, tracker, mapper, handle_signal):', tokens: [{ type: 'plain', t: '    ' }, { type: 'kw', t: 'async' }, { type: 'plain', t: ' ' }, { type: 'kw', t: 'def' }, { type: 'plain', t: ' start(self, tracker, mapper, handle_signal):' }] },
  { text: '        while True:', tokens: [{ type: 'plain', t: '        ' }, { type: 'kw', t: 'while' }, { type: 'plain', t: ' True:' }] },
  { text: '            price = await self.fetch_latest_price()', tokens: [{ type: 'plain', t: '            price = ' }, { type: 'kw', t: 'await' }, { type: 'plain', t: ' self.fetch_latest_price()' }] },
  { text: '            tracker.update(self.metadata.slug, PricePoint(', tokens: [{ type: 'plain', t: '            tracker.update(self.metadata.slug, PricePoint(' }] },
  { text: '                timestamp=datetime.now(UTC),', tokens: [{ type: 'plain', t: '                timestamp=datetime.now(UTC),' }] },
  { text: '                price=price,   # must be 0.0 – 1.0', tokens: [{ type: 'plain', t: '                price=price,   ' }, { type: 'comment', t: '# must be 0.0 – 1.0' }] },
  { text: '                volume=1,', tokens: [{ type: 'plain', t: '                volume=1,' }] },
  { text: '            ))', tokens: [{ type: 'plain', t: '            ))' }] },
  { text: '            await asyncio.sleep(self.metadata.poll_interval_seconds)', tokens: [{ type: 'plain', t: '            ' }, { type: 'kw', t: 'await' }, { type: 'plain', t: ' asyncio.sleep(self.metadata.poll_interval_seconds)' }] },
]

const TOKEN_COLORS: Record<string, string> = {
  kw: 'var(--neon)',
  str: '#888888',
  comment: '#555555',
  plain: 'var(--text-primary)',
}

export default function PrismSection() {
  return (
    <section style={{ background: 'var(--bg)', padding: '128px 0' }}>
      <div className="container">
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--neon)',
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            marginBottom: '48px',
          }}
        >
          05 // PRISM
        </div>

        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 'clamp(32px, 4vw, 48px)',
            color: 'var(--text-primary)',
            fontWeight: 400,
            marginBottom: '16px',
          }}
        >
          Bring your own signal.
        </h2>

        <div
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '20px',
            color: 'var(--text-secondary)',
            marginBottom: '16px',
          }}
        >
          Any data source. One interface.
        </div>

        <p
          style={{
            fontFamily: 'var(--font-sans)',
            fontSize: '16px',
            color: 'var(--text-secondary)',
            maxWidth: '600px',
            lineHeight: 1.7,
            marginTop: '16px',
          }}
        >
          .prism is the connector format for the Velocity Signal Engine. Drop a .prism package
          into the connectors/ directory and the engine loads it automatically. Prediction
          markets, alternative data, news sentiment, order flow — if it produces a time series,
          it can drive a signal.
        </p>

        <div
          className="prism-cards-grid"
          style={{ marginTop: '64px' }}
        >
          {CONNECTORS.map((c) => (
            <ConnectorCard key={c.name} connector={c} />
          ))}
        </div>

        <div
          style={{
            marginTop: '64px',
            background: '#0d0d0d',
            border: '1px solid #222222',
            borderRadius: '8px',
            padding: '24px 28px',
            overflowX: 'auto',
          }}
        >
          <pre
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '13px',
              lineHeight: 1.7,
              margin: 0,
            }}
          >
            {CODE_LINES.map((line, i) => (
              <div key={i}>
                {line.tokens.length === 0 ? (
                  ' '
                ) : (
                  line.tokens.map((tok, j) => (
                    <span key={j} style={{ color: TOKEN_COLORS[tok.type] }}>
                      {tok.t}
                    </span>
                  ))
                )}
              </div>
            ))}
          </pre>
        </div>
      </div>

      <style>{`
        .prism-cards-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }
        @media (max-width: 768px) {
          .prism-cards-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  )
}

function ConnectorCard({ connector }: { connector: (typeof CONNECTORS)[0] }) {
  const [hovered, setHovered] = useState(false)

  const cardStyle: React.CSSProperties = {
    background: '#111111',
    border: connector.custom
      ? '1px dashed #333333'
      : `1px solid ${hovered ? 'var(--neon)' : '#222222'}`,
    borderRadius: '8px',
    padding: '28px 32px',
    transition: 'border-color 200ms',
    cursor: 'default',
  }

  return (
    <div
      style={cardStyle}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '12px',
        }}
      >
        {connector.slug && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-tertiary)',
            }}
          >
            {connector.slug}
          </span>
        )}
        {connector.custom && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--neon)',
            }}
          >
            .prism
          </span>
        )}
        {connector.builtIn && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              background: '#1a2e1a',
              color: '#86efac',
              borderRadius: '2px',
              padding: '2px 6px',
            }}
          >
            BUILT-IN
          </span>
        )}
        {connector.transport && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '10px',
              background: 'var(--neon)',
              color: '#000000',
              borderRadius: '2px',
              padding: '2px 6px',
            }}
          >
            {connector.transport}
          </span>
        )}
      </div>

      <div
        style={{
          fontFamily: 'var(--font-serif)',
          fontSize: '20px',
          color: connector.custom ? 'var(--text-secondary)' : 'var(--text-primary)',
          fontWeight: 400,
          marginBottom: '12px',
        }}
      >
        {connector.name}
      </div>

      <div
        style={{
          fontFamily: 'var(--font-sans)',
          fontSize: '14px',
          color: connector.custom ? 'var(--text-tertiary)' : 'var(--text-secondary)',
          lineHeight: 1.6,
          marginBottom: '20px',
        }}
      >
        {connector.description}
      </div>

      {connector.meta && (
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--text-tertiary)',
          }}
        >
          {connector.meta}
        </div>
      )}

      {connector.custom && (
        <a
          href="https://github.com/aryasomu/robinhood/blob/main/CONTRIBUTING_CONNECTORS.md"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-block',
            fontFamily: 'var(--font-mono)',
            fontSize: '12px',
            color: 'var(--text-secondary)',
            border: '1px solid var(--border)',
            borderRadius: '4px',
            padding: '8px 16px',
            textDecoration: 'none',
            transition: 'border-color 150ms, color 150ms',
          }}
          onMouseEnter={(e) => {
            ;(e.currentTarget as HTMLElement).style.borderColor = 'var(--neon)'
            ;(e.currentTarget as HTMLElement).style.color = 'var(--neon)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'
            ;(e.currentTarget as HTMLElement).style.color = 'var(--text-secondary)'
          }}
        >
          Read the spec →
        </a>
      )}
    </div>
  )
}
