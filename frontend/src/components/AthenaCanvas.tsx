import { useEffect, useRef } from 'react'
import { useReducedMotion } from 'motion/react'
import { DOTS } from '../lib/athenaDots'

interface AthenaCanvasProps {
  className?: string
  /** Multiplies every dot's alpha. Used to keep small screens quiet. */
  alpha?: number
  /** Decorative: the portrait never carries information. */
  label?: string
}

interface Spark {
  x: number
  y: number
  r: number
  phase: number
}

/**
 * Dot-matrix Athena portrait rendered from precomputed points.
 *
 * The reference design bakes the static field once into an offscreen canvas and
 * only animates a handful of sparks, which keeps the cost near zero at 60fps.
 */
export function AthenaCanvas({ className, alpha = 1, label = 'Athena' }: AthenaCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return

    const buffer = document.createElement('canvas')
    const bufferContext = buffer.getContext('2d')
    if (!bufferContext) return

    let sparks: Spark[] = []
    let scale = 1
    let frame = 0
    let running = true
    let startedAt = performance.now()
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const size = () => {
      const height = canvas.clientHeight || window.innerHeight
      const nextScale = height / 200
      canvas.width = 128 * nextScale * dpr
      canvas.height = height * dpr
      canvas.style.width = `${128 * nextScale}px`
      canvas.style.height = `${height}px`
      context.setTransform(dpr, 0, 0, dpr, 0, 0)
      scale = nextScale
    }

    const bake = () => {
      buffer.width = canvas.width
      buffer.height = canvas.height
      bufferContext.setTransform(dpr, 0, 0, dpr, 0, 0)
      bufferContext.clearRect(0, 0, buffer.width, buffer.height)
      const nextSparks: Spark[] = []

      for (let i = 0; i < DOTS.length; i += 1) {
        const dot = DOTS[i]
        const x = dot[0] * scale + scale / 2
        const y = dot[1] * scale + scale / 2
        const radius = dot[2] * scale
        const brightness = dot[3]
        if ((dot[0] * 31 + dot[1] * 17) % 211 === 0) {
          nextSparks.push({
            x,
            y,
            r: Math.max(radius, 0.8),
            phase: (dot[0] * 7 + dot[1] * 13) % 6.283,
          })
          continue
        }
        const opacity = (0.3 + 0.7 * brightness) * alpha
        if (opacity <= 0.01) continue
        const value = Math.round(70 + brightness * 185)
        bufferContext.fillStyle = `rgba(${value},${value},${Math.min(255, Math.round(value * 1.02))},${opacity.toFixed(3)})`
        bufferContext.beginPath()
        bufferContext.arc(x, y, Math.max(radius, 0.4), 0, 6.283)
        bufferContext.fill()
      }
      sparks = nextSparks
    }

    const draw = (time: number) => {
      const elapsed = (time - startedAt) / 1000
      context.clearRect(0, 0, canvas.width, canvas.height)
      context.drawImage(buffer, 0, 0, buffer.width / dpr, buffer.height / dpr)
      for (const spark of sparks) {
        const pulse = reducedMotion ? 0.7 : 0.5 + 0.5 * Math.sin(elapsed * 2.2 + spark.phase * 3)
        const glow = reducedMotion ? 1 : 1 + 0.4 * Math.sin(elapsed * 2.2 + spark.phase)
        context.fillStyle = `rgba(98,84,255,${(pulse * 0.9 * alpha).toFixed(3)})`
        context.beginPath()
        context.arc(spark.x, spark.y, spark.r * glow, 0, 6.283)
        context.fill()
      }
    }

    const loop = (time: number) => {
      if (!running) return
      draw(time)
      frame = requestAnimationFrame(loop)
    }

    const restart = () => {
      cancelAnimationFrame(frame)
      size()
      bake()
      startedAt = performance.now()
      if (reducedMotion) {
        draw(startedAt)
        return
      }
      running = true
      frame = requestAnimationFrame(loop)
    }

    restart()

    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') {
        cancelAnimationFrame(frame)
      } else if (!reducedMotion) {
        startedAt = performance.now()
        frame = requestAnimationFrame(loop)
      }
    }

    const observer = new ResizeObserver(() => restart())
    observer.observe(canvas)
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      running = false
      cancelAnimationFrame(frame)
      observer.disconnect()
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [alpha, reducedMotion])

  return <canvas ref={canvasRef} className={className} aria-hidden="true" role="presentation" data-label={label} />
}
