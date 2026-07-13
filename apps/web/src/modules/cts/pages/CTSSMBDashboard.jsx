/**
 * CTSSMBDashboard — standalone route wrapper for /cts/smb/dashboard.
 *
 * Content lives in SMBDashboardContent (shared with CTSOpsDashboard, which
 * embeds the same content directly when an SMB user opens "Dashboard" — see
 * the SB/SMB dashboard restructure). This wrapper just supplies AppShell +
 * the page header for anyone hitting this route directly.
 */
import { useEffect } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import AppShell from '../../../shared/layout/AppShell'
import SMBDashboardContent from '../components/SMBDashboardContent'

export default function CTSSMBDashboard() {
  const { bankName } = useBankContext()
  const { isDark } = useTheme()
  const { setHeader } = usePageHeader()

  useEffect(() => {
    setHeader({ title: 'SMB Dashboard', subtitle: bankName })
  }, [setHeader, bankName])

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${isDark ? 'bg-navy-950' : 'bg-slate-50'} px-6 py-5`}>
        <SMBDashboardContent />
      </div>
    </AppShell>
  )
}
