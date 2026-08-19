import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

import { PostHogProvider } from '@posthog/react'

const options = {
  api_host: import.meta.env.VITE_POSTHOG_HOST || "https://eu.i.posthog.com",
  disable_session_recording: true,
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PostHogProvider 
      apiKey={import.meta.env.VITE_POSTHOG_PROJECT_TOKEN || "phc_vEgQtXumCU6NkhgdDiGm5J8MndG4wEXTMuUjXRNYorDP"}
      options={options}
    >
      <App />
    </PostHogProvider>
  </React.StrictMode>,
)
