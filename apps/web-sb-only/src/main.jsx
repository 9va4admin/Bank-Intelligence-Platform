import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { BANK_CONFIG } from './shared/config/bank.config'
import { initMessages } from './shared/messages'

// Browser tab title comes from bank.config — no hardcoding in HTML
document.title = `ASTRA CTS — ${BANK_CONFIG.bank_name}`

// Screens take their wording from the message bundle, and some read it when their module loads. So the bundle is loaded first and the
// app (and with it every screen) is imported only afterwards.
initMessages().finally(async () => {
  const { default: App } = await import('./App')
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
