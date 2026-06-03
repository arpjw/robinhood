const signalLayer = [
  { name: 'Kalshi REST + WebSocket', desc: 'Primary signal source. RSA-PSS authenticated polling with WebSocket fallback and exponential backoff.' },
  { name: 'Polymarket CLOB', desc: 'Secondary signal feed via py-clob-client. Contributes to shared VelocityTracker.' },
  { name: 'VelocityTracker', desc: 'Custom Δp/Δt engine with configurable rolling windows (default: 5m, 15m). Threshold-filtered.' },
  { name: 'SignalDeduplicator', desc: 'Per-slug and per-sector deduplication. Sector cap enforcement prevents correlated flood.' },
  { name: 'ConfidenceDecay', desc: 'Price centrality adjustment. Discounts signals near historical extremes where edge is thinner.' },
]

const executionLayer = [
  { name: 'Robinhood Agentic MCP', desc: 'Live execution endpoint at agent.robinhood.com. Requires EXECUTION_MODE=live and private beta access.' },
  { name: 'MockMCPClient', desc: 'Paper trading mode. Orders logged to logs/mock_orders.jsonl with full metadata. Default mode.' },
  { name: 'ExposureManager', desc: 'Macro factor cap enforcement. 15% per-factor, 40% gross total. Checked before every order.' },
  { name: 'ExitManager', desc: 'Time-decay primary exits (2h default). Reverse velocity and adverse move (3%) secondary exits.' },
  { name: 'rich dashboard', desc: 'Terminal UI refreshing every 5s. Reads orders.jsonl, tracks open positions, shows unrealized P&L.' },
]

export default function StackSection() {
  return (
    <section style={{ background: 'var(--bg)', padding: '96px 0' }}>
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
          04 // STACK
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '64px',
          }}
          className="stack-grid"
        >
          <StackColumn title="Signal Layer" items={signalLayer} />
          <StackColumn title="Execution Layer" items={executionLayer} />
        </div>
      </div>

      <style>{`
        @media (max-width: 1024px) {
          .stack-grid {
            grid-template-columns: 1fr !important;
            gap: 48px !important;
          }
        }
      `}</style>
    </section>
  )
}

function StackColumn({
  title,
  items,
}: {
  title: string
  items: { name: string; desc: string }[]
}) {
  return (
    <div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '12px',
          color: 'var(--text-tertiary)',
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          marginBottom: '32px',
          paddingBottom: '12px',
          borderBottom: '1px solid var(--border)',
        }}
      >
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
        {items.map((item) => (
          <div key={item.name}>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '14px',
                color: 'var(--text-primary)',
                marginBottom: '4px',
              }}
            >
              {item.name}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: '13px',
                color: 'var(--text-secondary)',
                lineHeight: 1.5,
              }}
            >
              {item.desc}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
