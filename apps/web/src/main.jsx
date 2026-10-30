import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './shared/theme/ThemeContext'
import './index.css'
import { initMessages } from './shared/messages'

const queryClient = new QueryClient()

// Screens take their wording from the message bundle, and some read it when their module loads. So the bundle is loaded first and the
// app (and with it every screen) is imported only afterwards.
initMessages('en').finally(async () => {
  const { default: App } = await import('./App.jsx')
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
