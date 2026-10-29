import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './shared/theme/ThemeContext'
import './index.css'
import App from './App.jsx'
import { initMessages } from './shared/messages'

const queryClient = new QueryClient()

// Load the message bundle first: screens take their wording from it, and show the key until it is loaded.
initMessages('en').finally(() => {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <App />
        </ThemeProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
})
