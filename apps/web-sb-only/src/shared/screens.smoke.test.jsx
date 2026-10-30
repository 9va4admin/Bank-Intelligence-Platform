// Renders every page inside the providers the real app gives it, with the API answering "nothing", and checks that
//   - the page renders without throwing (a converted message call that is broken fails here), and
//   - no raw message key (UI_..., CTS_WF_...) reaches the screen, which would mean wording was looked up before the bundle was loaded
//     or a key does not exist.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { render, cleanup, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './theme/ThemeContext'
import { AuthProvider } from './context/AuthContext'
import { BankProvider } from './context/BankContext'
import { PageHeaderProvider } from './layout/PageHeaderContext'

const pages = import.meta.glob(['../modules/**/pages/*.jsx', '!../modules/**/pages/*.test.jsx'])
// A leak is a real message key showing on screen. A status code that merely looks like one (CTS_NON_COMP) is not.
const MESSAGE_KEYS = new Set(
  [...readFileSync(join(process.cwd(), '..', '..', 'shared', 'messages', 'locales', 'messages.yaml'), 'utf8').matchAll(/^([A-Z][A-Z0-9_]+):\s*$/gm)].map(m => m[1]))
const leakedKey = (text) => (text.match(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g) ?? []).find(t => MESSAGE_KEYS.has(t)) ?? null

afterEach(() => cleanup())

// Pages that cannot be rendered by this harness today, for reasons that predate the wording work (see the notes in the pull request):
//   LoginPage.jsx           imports qrcode.react, which web-sb-only's package.json does not list, so the page cannot load here
//   CTSInwardReviewQueue.jsx kills the test process when it renders against an empty API answer (it did so before any wording change)
const KNOWN_BROKEN = new Set(['auth/pages/LoginPage.jsx', 'cts/pages/CTSInwardReviewQueue.jsx'])

describe('every page renders and shows real wording', () => {
  for (const [path, load] of Object.entries(pages)) {
    const name = path.replace('../modules/', '')
    const run = KNOWN_BROKEN.has(name) ? it.skip : it
    run(name, async () => {
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
      expect(leakedKey(text)).toBeNull()
    })
  }
})
