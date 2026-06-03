const statuses = [
  {
    label: 'Signal Engine (Phase 0-1)',
    badge: 'COMPLETE',
    color: { bg: '#14532d', text: '#86efac' },
  },
  {
    label: 'Mock Execution + Backtest (Phase 1)',
    badge: 'COMPLETE',
    color: { bg: '#14532d', text: '#86efac' },
  },
  {
    label: 'Live MCP Execution (Phase 2)',
    badge: 'AWAITING ACCESS',
    color: { bg: '#451a03', text: '#fbbf24' },
  },
]

export default function StatusSection() {
  return (
    <section style={{ background: 'var(--surface)', padding: '96px 0' }}>
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
          04 // STATUS
        </div>

        <div
          style={{
            maxWidth: '800px',
            margin: '0 auto',
            background: 'var(--surface-elevated)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '48px',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
            {statuses.map((s, i) => (
              <div
                key={s.label}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '24px',
                  padding: '20px 0',
                  borderBottom:
                    i < statuses.length - 1 ? '1px solid var(--border)' : 'none',
                  flexWrap: 'wrap',
                }}
              >
                <span
                  style={{
                    fontFamily: 'var(--font-sans)',
                    fontSize: '15px',
                    color: 'var(--text-primary)',
                  }}
                >
                  {s.label}
                </span>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '11px',
                    letterSpacing: '0.08em',
                    background: s.color.bg,
                    color: s.color.text,
                    padding: '4px 10px',
                    borderRadius: '2px',
                    flexShrink: 0,
                  }}
                >
                  {s.badge}
                </span>
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: '32px',
              background: 'var(--bg)',
              borderLeft: '3px solid var(--neon)',
              padding: '20px 24px',
            }}
          >
            <p
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                color: 'var(--text-secondary)',
                lineHeight: 1.6,
              }}
            >
              Live execution requires Robinhood agentic trading account access, currently in
              private beta. Set{' '}
              <span style={{ color: 'var(--neon)' }}>EXECUTION_MODE=live</span> only after
              receiving access confirmation.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
