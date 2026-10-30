type AnalyticsProperties = Record<string, unknown>
type IdleCapableWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number
}

let posthogPromise: Promise<typeof import('posthog-js').default> | undefined

function loadPostHog() {
  if (!posthogPromise) {
    posthogPromise = import('posthog-js').then(({ default: posthog }) => {
      posthog.init(
        import.meta.env.VITE_POSTHOG_PROJECT_TOKEN || 'phc_vEgQtXumCU6NkHgdDiGm5J8MnDg4wEXTMuUjXRAYorDP',
        {
          api_host: import.meta.env.VITE_POSTHOG_HOST || (import.meta.env.PROD ? '/ingest' : 'https://eu.i.posthog.com'),
          ui_host: 'https://eu.posthog.com',
          disable_session_recording: true,
        },
      )
      return posthog
    }).catch((error) => {
      posthogPromise = undefined
      throw error
    })
  }
  return posthogPromise
}

export function track(event: string, properties?: AnalyticsProperties) {
  void loadPostHog()
    .then((posthog) => posthog.capture(event, properties))
    .catch(() => {
      // Analytics must never block the app flow.
    })
}

export function initializeAnalyticsWhenIdle() {
  const initialize = () => {
    void loadPostHog().catch(() => {
      // Analytics will retry on the next captured event.
    })
  }

  const idleWindow = window as IdleCapableWindow
  if (idleWindow.requestIdleCallback) {
    idleWindow.requestIdleCallback(initialize, { timeout: 5000 })
  } else {
    window.setTimeout(initialize, 2500)
  }
}
