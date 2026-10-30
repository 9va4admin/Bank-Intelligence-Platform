import AppShell from '../../shared/layout/AppShell'
import { useTheme } from '../../shared/theme/ThemeContext'
import { msg } from '../../shared/messages'

export default function IETMonitorPage() {
  const { isDark } = useTheme()
  const th = {
    page:    isDark ? 'bg-shell-800'               : 'bg-slate-50',
    card:    isDark ? 'bg-shell-950 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                 : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'             : 'text-slate-500',
  }

  return (
    <AppShell title={msg('UI_IETMONITORPAGE_IET_MONITOR_WATCHDOG_STATUS')}>
      <div className={`${th.page} px-6 py-5 min-h-full`}>

        {/* IET health banner */}
        <div className="mb-5 flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/8 px-5 py-4">
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-sm font-medium text-emerald-300">
           {msg('UI_IETMONITORPAGE_IET_BREACH_RATE_0_000')}
          </span>
        </div>

        {/* Placeholder — will wire to Temporal workflow query */}
        <div className={`rounded-xl border p-8 text-center ${th.card}`}>
          <div className={`text-sm ${th.muted}`}>
           {msg('UI_IETMONITORPAGE_IETWATCHDOGWORKFLOW_STATUS_PER_CHEQU')}
            <br />
           {msg('UI_IETMONITORPAGE_EACH_ROW_SHOWS_INSTRUMENT_ID')}
          </div>
        </div>

      </div>
    </AppShell>
  )
}
