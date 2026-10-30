import '@testing-library/jest-dom'
import { vi } from 'vitest'
import { initMessages } from './shared/messages'

// The real app wraps every screen in the same providers (data fetching, bank identity, page header; authentication is optional for them). Screens read them
// through hooks that throw when a provider is missing, so a test that rendered a bare screen failed before reaching any assertion.
// Every render() now gets those providers by default; a test's own providers sit inside them and win. A router is not added here
// because tests that need one supply theirs (two routers cannot be nested).
vi.mock('@testing-library/react', async (importOriginal) => {
  const rtl = await importOriginal()
  const React = await import('react')
  const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
  const h = React.createElement
  // A test that mocks one of these modules (for example only useBankContext) has no provider to wrap with, and needs none.
  const pick = async (load, name) => { try { const m = await load(); return m[name] ?? null } catch { return null } }
  // BankProvider reads the auth context, so it is only added when that module has not been replaced by a test.
  const authIntact = await pick(() => import('./shared/context/AuthContext'), 'useAuthOptional')
  const BankProvider = authIntact ? await pick(() => import('./shared/context/BankContext'), 'BankProvider') : null
  const PageHeaderProvider = await pick(() => import('./shared/layout/PageHeaderContext'), 'PageHeaderProvider')
  const nest = (Provider, children) => (Provider ? h(Provider, null, children) : children)
  function AppProviders({ children }) {
    const client = React.useMemo(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }), [])
    return h(QueryClientProvider, { client }, nest(BankProvider, nest(PageHeaderProvider, children)))
  }
  const compose = (Inner) => function Wrapped({ children }) { return h(AppProviders, null, h(Inner, null, children)) }
  return {
    ...rtl,
    render: (ui, options = {}) => rtl.render(ui, { ...options, wrapper: options.wrapper ? compose(options.wrapper) : AppProviders }),
  }
})

// This Node/jsdom combination can leave localStorage / sessionStorage undefined; screens read them, so give tests an in-memory one.
function memoryStorage() {
  const store = new Map()
  return {
    getItem: k => (store.has(String(k)) ? store.get(String(k)) : null),
    setItem: (k, v) => { store.set(String(k), String(v)) },
    removeItem: k => { store.delete(String(k)) },
    clear: () => store.clear(),
    key: i => [...store.keys()][i] ?? null,
    get length() { return store.size },
  }
}
for (const name of ['localStorage', 'sessionStorage']) {
  let ok = false
  try { ok = typeof globalThis[name]?.getItem === 'function' } catch { ok = false }
  if (!ok) {
    const s = memoryStorage()
    Object.defineProperty(globalThis, name, { value: s, configurable: true, writable: true })
    if (typeof window !== 'undefined') Object.defineProperty(window, name, { value: s, configurable: true, writable: true })
  }
}

// Charts measure themselves with ResizeObserver, which jsdom does not have.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
}

// Screens take their wording from the message bundle, and some read it when their module loads, so it is loaded before any test file.
await initMessages('en')
