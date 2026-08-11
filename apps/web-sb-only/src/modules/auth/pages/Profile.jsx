/**
 * Profile — the signed-in user's identity + session details.
 * Reached from the top-right user menu ("My Profile").
 */
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { useAuth } from '../../../shared/context/AuthContext'

export default function Profile() {
  const { isDark } = useTheme()
  const { bankName, bankIfsc, bankType, userRole, userName } = useBankContext()
  const { user } = useAuth()

  const th = {
    page:    isDark ? 'bg-[#020817]'      : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'        : 'text-slate-900',
    label:   isDark ? 'text-slate-400'    : 'text-slate-500',
    value:   isDark ? 'text-slate-200'    : 'text-slate-800',
    row:     isDark ? 'border-white/8'    : 'border-slate-100',
  }

  const rows = [
    ['Username', userName || user?.username || '—'],
    ['Role', userRole || '—'],
    ['Bank', bankName ? `${bankName}${bankIfsc ? ` · ${bankIfsc}` : ''}` : '—'],
    ['Bank type', bankType || '—'],
    ['Two-factor (TOTP)', user?.mfa_authenticated ? 'Enabled' : 'Not enabled'],
  ]

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-6`}>
        <h1 className={`text-lg font-semibold mb-4 ${th.heading}`}>My Profile</h1>
        <div className={`max-w-lg rounded-xl border ${th.card}`}>
          {rows.map(([k, v], i) => (
            <div
              key={k}
              className={`flex items-center justify-between px-4 py-3 ${i < rows.length - 1 ? `border-b ${th.row}` : ''}`}
            >
              <span className={`text-xs ${th.label}`}>{k}</span>
              <span className={`text-sm font-medium ${th.value}`}>{v}</span>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  )
}
