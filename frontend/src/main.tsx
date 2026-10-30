import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import DeferredTelemetry from './components/DeferredTelemetry'
import { initializeAnalyticsWhenIdle } from './lib/analytics'

import * as Sentry from '@sentry/react'

Sentry.init({
  dsn: import.meta.env.VITE_SENTRY_DSN || "https://2bd0f370583a6d64b0920920e804fc45@o4512010180066048.ingest.de.sentry.io/4512010184929360",
  environment: import.meta.env.MODE || "production",
})
initializeAnalyticsWhenIdle()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Sentry.ErrorBoundary fallback={<div style={{ padding: 24, color: '#fff', background: '#1400FF', fontFamily: 'monospace' }}>An error occurred while loading the application. Please refresh.</div>}>
      <App />
      <DeferredTelemetry />
    </Sentry.ErrorBoundary>
  </React.StrictMode>,
)

