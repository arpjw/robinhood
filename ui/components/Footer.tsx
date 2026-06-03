export default function Footer() {
  return (
    <footer
      style={{
        background: 'var(--bg)',
        borderTop: '1px solid var(--surface-elevated)',
        padding: '64px 0',
      }}
    >
      <div className="container">
        <div className="footer-grid">
          <div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                color: 'var(--text-secondary)',
                letterSpacing: '0.1em',
                marginBottom: '8px',
              }}
            >
              RH // VELOCITY
            </div>
            <div
              style={{
                fontFamily: 'var(--font-sans)',
                fontSize: '14px',
                color: 'var(--text-secondary)',
              }}
            >
              Built by Arya Somu
            </div>
          </div>

          <div style={{ display: 'flex', gap: '24px', justifyContent: 'center' }}>
            {[
              { label: 'GitHub', href: 'https://github.com/aryasomu' },
              { label: 'aryasomu.com', href: 'https://aryasomu.com' },
            ].map(({ label, href }) => (
              <a
                key={label}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className="footer-link"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                  color: 'var(--text-tertiary)',
                  transition: 'color 150ms',
                }}
              >
                {label}
              </a>
            ))}
          </div>

          <div
            style={{
              textAlign: 'right',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-tertiary)',
              letterSpacing: '0.05em',
            }}
          >
            v3.0 // 4 PRISM CONNECTORS // MOCK MODE
          </div>
        </div>
      </div>

      <style>{`
        .footer-grid {
          display: grid;
          grid-template-columns: 1fr 1fr 1fr;
          gap: 32px;
          align-items: start;
        }
        @media (max-width: 1024px) {
          .footer-grid {
            grid-template-columns: 1fr;
            text-align: center;
          }
          .footer-grid > div:last-child {
            text-align: center;
          }
          .footer-grid > div:nth-child(2) {
            justify-content: center;
          }
        }
      `}</style>
    </footer>
  )
}
