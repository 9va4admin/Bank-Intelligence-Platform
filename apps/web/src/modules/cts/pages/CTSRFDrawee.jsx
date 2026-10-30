import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { msg } from '../../../shared/messages'

export default function CTSRFDrawee() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()

  const th = {
    page:    isDark ? 'bg-navy-950'        : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'     : 'text-slate-400',
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-8`}>
        <div className="max-w-2xl mx-auto">
          <div className={`rounded-xl border p-8 text-center ${th.card}`}>
            <div className="text-4xl mb-4">📥</div>
            <h1 className={`text-xl font-semibold mb-2 ${th.heading}`}>{msg('UI_RFDRAWEE_RF_DRAWEE_BANK')}</h1>
            <p className={`text-sm mb-6 ${th.body}`}>
             {msg('UI_RFDRAWEE_REJECTION_FILE_RECEIVED_FROM_NGCH')}
            </p>
            <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium
              ${isDark ? 'border-amber-500/30 bg-amber-900/15 text-amber-400' : 'border-amber-300 bg-amber-50 text-amber-700'}`}>
              <span className="w-2 h-2 rounded-full bg-amber-400" />
             {msg('UI_RFDRAWEE_COMING_SOON_DRAWEE_PROCESS_TO')}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
