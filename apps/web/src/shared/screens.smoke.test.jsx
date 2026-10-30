// Renders every page inside the providers the real app gives it, with the API answering "nothing", and checks that
//   - the page renders without throwing (a converted message call that is broken fails here), and
//   - no raw message key (UI_..., CTS_WF_...) reaches the screen, which would mean wording was looked up before the bundle was loaded
//     or a key does not exist.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './theme/ThemeContext'
import { AuthProvider } from './context/AuthContext'
import { BankProvider } from './context/BankContext'
import { PageHeaderProvider } from './layout/PageHeaderContext'

const pages = import.meta.glob(['../modules/**/pages/*.jsx', '!../modules/**/pages/*.test.jsx'])
const RAW_KEY = /\b(?:UI|CTS|AUTH|PLATFORM|API|VAULT|CBS|MSV)_[A-Z0-9]+(?:_[A-Z0-9]+){1,}\b/

afterEach(() => cleanup())

describe('every page renders and shows real wording', () => {
  for (const [path, load] of Object.entries(pages)) {
    it(path.replace('../modules/', ''), async () => {
      globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => '', blob: async () => new Blob() }))
      const Page = (await load()).default
      if (!Page) return
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      await act(async () => {
        render(
          <MemoryRouter>
            <QueryClientProvider client={client}>
              <ThemeProvider><AuthProvider><BankProvider><PageHeaderProvider><Page /></PageHeaderProvider></BankProvider></AuthProvider></ThemeProvider>
            </QueryClientProvider>
          </MemoryRouter>,
        )
        await new Promise(r => setTimeout(r, 30))
      })
      const text = document.body.textContent
      expect(text.match(RAW_KEY)?.[0] ?? null).toBeNull()
    })
  }
})
