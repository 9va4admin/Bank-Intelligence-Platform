import { createContext, useContext, useState, useEffect } from 'react'

export const PageHeaderCtx = createContext({
  subtitle: null,
  actions: null,
  setSubtitle: () => {},
  setActions: () => {},
})

export function PageHeaderProvider({ children }) {
  const [subtitle, setSubtitle] = useState(null)
  const [actions, setActions] = useState(null)
  return (
    <PageHeaderCtx.Provider value={{ subtitle, actions, setSubtitle, setActions }}>
      {children}
    </PageHeaderCtx.Provider>
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
  const { setSubtitle, setActions } = useContext(PageHeaderCtx)
  useEffect(() => {
    setSubtitle(subtitle ?? null)
    setActions(actions ?? null)
    return () => {
      setSubtitle(null)
      setActions(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
