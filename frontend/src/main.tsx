import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

import * as Sentry from '@sentry/react'
import { PostHogProvider } from '@posthog/react'
import { Analytics } from '@vercel/analytics/react'
import { SpeedInsights } from '@vercel/speed-insights/react'

Sentry.init({
  dsn: import.meta.env.VITE_SENTRY_DSN || "https://2bd0f370583a6d64b0920920e804fc45@o4512010180066048.ingest.de.sentry.io/4512010184929360",
  environment: import.meta.env.MODE || "production",
})

const options = {
  api_host: import.meta.env.VITE_POSTHOG_HOST || "https://eu.i.posthog.com",
  disable_session_recording: true,
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PostHogProvider 
      apiKey={import.meta.env.VITE_POSTHOG_PROJECT_TOKEN || "phc_vEgQtXumCU6NkHgdDiGm5J8MnDg4wEXTMuUjXRAYorDP"}
      options={options}
    >
      <App />
      <Analytics />
      <SpeedInsights />
    </PostHogProvider>
  </React.StrictMode>,
)

