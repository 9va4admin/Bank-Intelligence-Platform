import { createContext, useContext, useState, useLayoutEffect, useMemo } from 'react'

export const PageHeaderCtx = createContext({
  subtitle: null,
  actions: null,
  setSubtitle: () => {},
  setActions: () => {},
})

// The setters live in their own context with a stable value. A page that calls usePageHeader reads only that one, so it is not re-rendered
// every time it changes the header (which would loop); only the shell, which reads PageHeaderCtx, follows the header.
const PageHeaderSetCtx = createContext({ setSubtitle: () => {}, setActions: () => {} })

export function PageHeaderProvider({ children }) {
  const [subtitle, setSubtitle] = useState(null)
  const [actions, setActions] = useState(null)
  const setters = useMemo(() => ({ setSubtitle, setActions }), [])
  return (
    <PageHeaderSetCtx.Provider value={setters}>
      <PageHeaderCtx.Provider value={{ subtitle, actions, setSubtitle, setActions }}>
        {children}
      </PageHeaderCtx.Provider>
    </PageHeaderSetCtx.Provider>
  )
}

/**
 * Call inside any page component to push subtitle text and action buttons
 * up into AppShell's unified breadcrumb/header bar.
 *
 * @param {object} opts
 * @param {string}  [opts.subtitle]  - e.g. "Saraswat Co-op Bank · Session SES-001 · 2026-06-19"
 * @param {JSX}     [opts.actions]   - e.g. <button>Download CSV</button>
 */
export function usePageHeader({ subtitle, actions } = {}) {
  const { setSubtitle, setActions } = useContext(PageHeaderSetCtx)
  // Runs after every render of the page: the buttons are closures over the page's state (a Start/Stop button, a session picker), so a copy taken
  // once on mount would go stale and the header would show the page as it was at first paint.
  useLayoutEffect(() => {
    setSubtitle(subtitle ?? null)
    setActions(actions ?? null)
  })
  useLayoutEffect(() => () => {
    setSubtitle(null)
    setActions(null)
  }, [setSubtitle, setActions])
}
