import AppShell from '../../shared/layout/AppShell'
import { useTheme } from '../../shared/theme/ThemeContext'

export default function InwardQueuePage() {
  const { isDark } = useTheme()
  const th = {
    page:    isDark ? 'bg-shell-800'              : 'bg-slate-50',
    card:    isDark ? 'bg-shell-950 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                : 'text-slate-900',
    body:    isDark ? 'text-slate-300'            : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'            : 'text-slate-500',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
  }

  return (
    <AppShell title="Inward Queue — Live">
      <div className={`${th.page} px-6 py-5 min-h-full`}>

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: 'In Queue',       value: '—', color: 'text-amber-400' },
            { label: 'STP Confirm',    value: '—', color: 'text-emerald-400' },
            { label: 'Human Review',   value: '—', color: 'text-violet-400' },
            { label: 'IET Breaches',   value: '0', color: 'text-slate-400' },
          ].map(k => (
            <div key={k.label} className={`rounded-xl border p-4 ${th.card}`}>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
              <div className={`text-xs mt-1 ${th.muted}`}>{k.label}</div>
            </div>
          ))}
        </div>

        {/* Queue table placeholder */}
        <div className={`rounded-xl border ${th.card}`}>
          <div className={`px-5 py-3 border-b text-xs font-semibold uppercase tracking-wider ${th.muted} ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            Pending Instruments
          </div>
          <div className={`px-5 py-12 text-center text-sm ${th.muted}`}>
            Connect backend to populate live queue
          </div>
        </div>

      </div>
    </AppShell>
  )
}
