import type { ReactNode } from 'react'

export const APP_VERSION = '1.2.0'
export const APP_GITHUB_URL = 'https://github.com/PiUnknown'

export function GnosisLogo({ size = 18 }: { size?: number }) {
  return (
    <img
      src="/logo_white.webp"
      alt=""
      width={size}
      height={size}
      style={{ width: size, height: size, objectFit: 'contain' }}
    />
  )
}

interface NavBarProps {
  onLogoClick?: () => void
  /** Right-hand side meta. Omit for a bare brand bar. */
  children?: ReactNode
  logoLabel?: string
}

export function NavBar({ onLogoClick, children, logoLabel = 'Project Gnosis home' }: NavBarProps) {
  const brand = (
    <>
      <GnosisLogo />
      <span>GNOSIS</span>
    </>
  )

  return (
    <nav className="topnav">
      {onLogoClick ? (
        <button type="button" className="brand" onClick={onLogoClick} aria-label={logoLabel}>
          {brand}
        </button>
      ) : (
        <div className="brand" aria-label="Project Gnosis">
          {brand}
        </div>
      )}
      {children ? <div className="nav-meta">{children}</div> : null}
    </nav>
  )
}

export function LandingNav() {
  return (
    <NavBar>
      <span className="ver">v{APP_VERSION}</span>
      <a className="ghost-link" href={APP_GITHUB_URL} target="_blank" rel="noreferrer">
        GITHUB ↗
      </a>
    </NavBar>
  )
}
