import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'
import { BANK_CONFIG } from './shared/config/bank.config'

// Browser tab title comes from bank.config — no hardcoding in HTML
document.title = `ASTRA CTS — ${BANK_CONFIG.bank_name}`

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>
)
