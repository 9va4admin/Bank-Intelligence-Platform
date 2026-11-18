// Test helper for the alerting screens: renders a page inside the providers the real app gives it, with a scripted API.
import { render } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '../../shared/theme/ThemeContext'
import { AuthProvider } from '../../shared/context/AuthContext'
import { BankProvider } from '../../shared/context/BankContext'
import { PageHeaderProvider } from '../../shared/layout/PageHeaderContext'

// routes: { 'GET /v1/x': body | () => body | { status, body } } ; the first key contained in "METHOD url" wins; anything unscripted is an empty 200.
export function mockApi(routes) {
  const calls = []
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const method = opts.method ?? 'GET'
    const line = `${method} ${url}`
    calls.push({ url: String(url), method, body: opts.body ? JSON.parse(opts.body) : undefined, headers: opts.headers })
    const key = Object.keys(routes).find(k => line.includes(k))
    let out = key === undefined ? {} : routes[key]
    if (typeof out === 'function') out = out()
    if (out && out.__status) return { ok: out.__status < 400, status: out.__status, json: async () => out.body ?? {} }
    return { ok: true, status: 200, json: async () => out }
  })
  return calls
}

export const failing = (status, body) => ({ __status: status, body })

export function renderPage(element, { route = '/', path = '*', isDark = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  try { localStorage.setItem('astra-theme', isDark ? 'dark' : 'light') } catch { /* the theme falls back to its default */ }
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <ThemeProvider><AuthProvider><BankProvider><PageHeaderProvider>
          <Routes><Route path={path} element={element} /></Routes>
        </PageHeaderProvider></BankProvider></AuthProvider></ThemeProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}
