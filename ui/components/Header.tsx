export default function Header() {
  return (
    <header
      className="anim-header"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: '52px',
        background: 'rgba(10,10,10,0.85)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 48px',
        zIndex: 1000,
      }}
    >
      <a
        href="/"
        className="logo-link"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '13px',
          letterSpacing: '0.15em',
          color: 'var(--text-secondary)',
          transition: 'color 150ms',
        }}
      >
        RH // VELOCITY
      </a>
      <nav style={{ display: 'flex', gap: '24px' }}>
        {[
          { label: 'GitHub', href: 'https://github.com/aryasomu' },
          { label: 'arya somu', href: 'https://aryasomu.com' },
        ].map(({ label, href }) => (
          <a
            key={label}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="nav-link"
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
      </nav>
    </header>
  )
}
