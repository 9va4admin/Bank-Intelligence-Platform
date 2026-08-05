import { useEffect } from 'react'
import { useBankContext } from '../context/BankContext'

/**
 * setInterval that only fires in DEMO deployment mode. No-op in POC/PROD.
 * isDemo is static (build-time), so the effect mounts once and never re-runs on isDemo change.
 *
 * Usage:
 *   useDemoInterval(() => { ...tick... }, 1000)
 *   useDemoInterval(() => { ...tick using bankIfsc... }, 800, [bankIfsc])
 */
export default function useDemoInterval(fn, delay, deps = []) {
  const { isDemo } = useBankContext()
  useEffect(() => {
    if (!isDemo) return
    const timer = setInterval(fn, delay)
    return () => clearInterval(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDemo, ...deps])
}
