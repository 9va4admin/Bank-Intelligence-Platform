import { useBankContext } from '../context/BankContext'

/**
 * Returns mockValue in DEMO deployment mode, emptyValue in POC/PROD.
 * isDemo is derived from VITE_DEPLOYMENT_MODE (build-time env var — never changes at runtime).
 *
 * Usage:
 *   const items    = useDemoData(MOCK_ITEMS)                  // emptyValue defaults to []
 *   const stats    = useDemoData(MOCK_STATS, ZERO_STATS)      // custom empty object
 *   const count    = useDemoData(42, 0)                       // numeric
 *   const sessions = useDemoData(isSMB ? SMB_DATA : SB_DATA) // conditional mock
 */
export default function useDemoData(mockValue, emptyValue = []) {
  const { isDemo } = useBankContext()
  return isDemo ? mockValue : emptyValue
}
