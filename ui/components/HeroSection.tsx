import TerminalWidget from './TerminalWidget'

export default function HeroSection() {
  return (
    <section
      style={{
        minHeight: 'calc(100vh - 52px)',
        display: 'flex',
        alignItems: 'center',
        background: 'var(--bg)',
        padding: '80px 0',
      }}
    >
      <div className="container" style={{ width: '100%' }}>
        <div className="hero-grid">
          <div>
            <div className="anim-eyebrow" style={{ marginBottom: '24px' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  letterSpacing: '0.2em',
                  color: 'var(--neon)',
                  textTransform: 'uppercase',
                }}
              >
                SIGNAL ENGINE v2.0
              </span>
              <span className="cursor-blink" />
            </div>

            <div className="anim-headline1">
              <h1
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 'clamp(40px, 5vw, 64px)',
                  color: 'var(--text-primary)',
                  lineHeight: 1.1,
                  fontWeight: 400,
                }}
              >
                Prediction markets move faster than equities.
              </h1>
            </div>

            <div className="anim-headline2">
              <h2
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 'clamp(40px, 5vw, 64px)',
                  color: 'var(--neon)',
                  lineHeight: 1.1,
                  fontWeight: 400,
                  marginTop: '4px',
                }}
              >
                We capture the gap.
              </h2>
            </div>

            <div className="anim-body">
              <p
                style={{
                  fontFamily: 'var(--font-sans)',
                  fontSize: '18px',
                  color: 'var(--text-secondary)',
                  lineHeight: 1.6,
                  maxWidth: '480px',
                  marginTop: '32px',
                }}
              >
                When a Kalshi or Polymarket contract reprices sharply, correlated equities take
                minutes to catch up. This engine detects velocity spikes — Δp/Δt exceeding
                threshold — and submits positions via Robinhood&apos;s agentic trading MCP before
                the gap closes.
              </p>
            </div>

            <div
              className="anim-buttons"
              style={{ display: 'flex', gap: '12px', marginTop: '40px', flexWrap: 'wrap' }}
            >
              <a
                href="https://github.com/aryasomu"
                target="_blank"
                rel="noopener noreferrer"
                className="btn-primary"
              >
                View on GitHub
              </a>
              <a href="#signal" className="btn-secondary">
                Read the thesis →
              </a>
            </div>
          </div>

          <div className="anim-terminal hero-terminal">
            <TerminalWidget />
          </div>
        </div>
      </div>

      <style>{`
        .hero-grid {
          display: grid;
          grid-template-columns: 60fr 40fr;
          gap: 64px;
          align-items: center;
        }
        .hero-terminal {
          margin-top: -24px;
        }
        @media (max-width: 1024px) {
          .hero-grid {
            grid-template-columns: 1fr;
          }
          .hero-terminal {
            margin-top: 0;
          }
        }
      `}</style>
    </section>
  )
}
