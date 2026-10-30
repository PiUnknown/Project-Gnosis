import { lazy, Suspense, useEffect, useState } from 'react'

type IdleCapableWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number
  cancelIdleCallback?: (handle: number) => void
}

const VercelAnalytics = lazy(() =>
  import('@vercel/analytics/react').then(({ Analytics }) => ({ default: Analytics })),
)
const VercelSpeedInsights = lazy(() =>
  import('@vercel/speed-insights/react').then(({ SpeedInsights }) => ({ default: SpeedInsights })),
)

export default function DeferredTelemetry() {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const enable = () => setReady(true)
    const idleWindow = window as IdleCapableWindow
    if (idleWindow.requestIdleCallback) {
      const idleId = idleWindow.requestIdleCallback(enable, { timeout: 5000 })
      return () => idleWindow.cancelIdleCallback?.(idleId)
    }
    const timeoutId = window.setTimeout(enable, 2500)
    return () => window.clearTimeout(timeoutId)
  }, [])

  if (!ready) return null
  return (
    <Suspense fallback={null}>
      <VercelAnalytics />
      <VercelSpeedInsights />
    </Suspense>
  )
}
