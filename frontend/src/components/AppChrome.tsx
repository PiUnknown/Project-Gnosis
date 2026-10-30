import { useEffect, useState } from 'react'
import { motion } from 'motion/react'

function useWindowWidth() {
  const [width, setWidth] = useState(
    typeof window !== 'undefined' ? window.innerWidth : 1440
  )
  useEffect(() => {
    const fn = () => setWidth(window.innerWidth)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [])
  return width
}


function GnosisLogo({ size = 24 }: { size?: number }) {
  return (
    <img
      src="/logo_white.webp"
      alt="Project Gnosis Symbol"
      width={size}
      height={size}
      style={{
        display: 'block',
        flexShrink: 0,
        width: size,
        height: size,
        objectFit: 'contain',
      }}
    />
  )
}

// ─── NavBar ───────────────────────────────────────────────────────────────────
export function NavBar({ onLogoClick }: { onLogoClick: () => void }) {
  const isMobile = useWindowWidth() < 768
  return (
    <nav
      style={{
        height: isMobile ? 56 : 72,
        background: '#1400FF',
        borderBottom: '1px solid rgba(255,255,255,0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: isMobile ? '0 20px' : '0 96px',
        flexShrink: 0,
      }}
    >
      <motion.button
        onClick={onLogoClick}
        whileTap={{ scale: 0.97 }}
        transition={{ type: 'spring', bounce: 0, duration: 0.2 }}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: 0,
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: 14,
          fontWeight: 500,
          letterSpacing: '0.12em',
          color: '#FFFFFF',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <GnosisLogo />
        GNOSIS
      </motion.button>
      {!isMobile && (
        <span
          style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 11,
            fontWeight: 400,
            letterSpacing: '0.14em',
            color: 'rgba(255,255,255,0.50)',
          }}
        >
          CODE ARCHAEOLOGY AGENT
        </span>
      )}
    </nav>
  )
}

// ─── Athena Figure ────────────────────────────────────────────────────────────
export function AthenaFigure({ brightness = 0.88 }: { brightness?: number }) {
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}>
      <img
        src="https://images.unsplash.com/photo-1670813885725-e3c5391dcd31?w=900&h=1400&fit=crop&auto=format"
        srcSet="https://images.unsplash.com/photo-1670813885725-e3c5391dcd31?w=600&h=1000&fit=crop&auto=format 600w, https://images.unsplash.com/photo-1670813885725-e3c5391dcd31?w=900&h=1400&fit=crop&auto=format 900w"
        sizes="(max-width: 768px) 600px, 900px"
        alt="Athena — goddess of wisdom"
        fetchPriority="high"
        loading="eager"
        decoding="async"
        style={{
          position: 'absolute',
          top: 0,
          left: '50%',
          transform: 'translateX(-40%)',
          height: '100%',
          width: 'auto',
          filter: `grayscale(1) contrast(1.55) brightness(${brightness})`,
          mixBlendMode: 'screen',
          opacity: 0.9,
          WebkitMaskImage: 'linear-gradient(to right, transparent 0%, black 18%, black 80%, transparent 100%)',
          maskImage: 'linear-gradient(to right, transparent 0%, black 18%, black 80%, transparent 100%)',
        }}
      />
    </div>
  )
}

// ─── RiskBadge ────────────────────────────────────────────────────────────────

