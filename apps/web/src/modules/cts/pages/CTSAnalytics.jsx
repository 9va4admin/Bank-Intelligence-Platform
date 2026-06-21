import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

const DAILY = [
  { date: 'Jun 13', total: 487, stp_confirm: 401, stp_return: 62, human: 24, avg_ms: 389 },
  { date: 'Jun 14', total: 512, stp_confirm: 423, stp_return: 71, human: 18, avg_ms: 372 },
  { date: 'Jun 15', total: 498, stp_confirm: 411, stp_return: 68, human: 19, avg_ms: 401 },
  { date: 'Jun 16', total: 531, stp_confirm: 444, stp_return: 74, human: 13, avg_ms: 358 },
  { date: 'Jun 17', total: 474, stp_confirm: 388, stp_return: 63, human: 23, avg_ms: 413 },
  { date: 'Jun 18', total: 543, stp_confirm: 456, stp_return: 71, human: 16, avg_ms: 344 },
  { date: 'Jun 19', total: 127, stp_confirm: 104, stp_return: 17, human:  6, avg_ms: 361 },
]

const FRAUD_DIST = [
  { range: '0–10%',   count: 312 },
  { range: '10–30%',  count: 89  },
  { range: '30–50%',  count: 41  },
  { range: '50–70%',  count: 28  },
  { range: '70–90%',  count: 31  },
  { range: '90–100%', count: 44  },
]

const RETURN_REASONS = [
  { reason: 'FRAUD_RISK',   count: 44 },
  { reason: 'SIG_MISMATCH', count: 31 },
  { reason: 'ALTERATION',   count: 18 },
  { reason: 'FUNDS_SHORT',  count: 9  },
  { reason: 'OTHER',        count: 4  },
]

const maxFraud  = Math.max(...FRAUD_DIST.map(d => d.count))
const maxReturn = Math.max(...RETURN_REASONS.map(d => d.count))
const maxTotal  = Math.max(...DAILY.map(d => d.total))

export default function CTSAnalytics() {
  const today  = DAILY[DAILY.length - 1]
  const stpRate = ((today.stp_confirm / today.total) * 100).toFixed(1)

  const th = {
    page:     'bg-slate-50 dark:bg-transparent',
    card:     'bg-white border-slate-200 dark:bg-white/4 dark:border-white/8',
    heading:  'text-slate-900 dark:text-white',
    faint:    'text-slate-400 dark:text-slate-600',
    muted:    'text-slate-500 dark:text-slate-400',
    bar:      'bg-slate-100 dark:bg-white/5',
    dateLbl:  'text-slate-400 dark:text-slate-600',
    legend:   'text-slate-500 dark:text-slate-500',
  }

  usePageHeader({ subtitle: 'Decision analytics · 7-day rolling view' })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Today Total',    value: today.total,         color: th.heading },
            { label: 'STP Rate',       value: `${stpRate}%`,       color: 'text-emerald-500' },
            { label: 'Avg Agent Time', value: `${today.avg_ms}ms`, color: 'text-amber-500' },
            { label: 'Human Reviews',  value: today.human,         color: 'text-amber-500' },
            { label: 'IET Breaches',   value: '0',                 color: 'text-emerald-500' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          {/* Daily volume bar chart */}
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-sm font-medium ${th.heading} mb-4`}>Daily Volume (7 days)</div>
            <div className="flex items-end gap-2 h-32">
              {DAILY.map(d => (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                  <div className="w-full flex flex-col justify-end" style={{ height: '100px' }}>
                    <div className="w-full bg-emerald-500/70 rounded-t" style={{ height: `${(d.stp_confirm / maxTotal) * 100}px` }} />
                    <div className="w-full bg-red-500/50"              style={{ height: `${(d.stp_return  / maxTotal) * 100}px` }} />
                    <div className="w-full bg-amber-500/50 rounded-b"  style={{ height: `${(d.human       / maxTotal) * 100}px` }} />
                  </div>
                  <span className={`text-[9px] ${th.dateLbl}`}>{d.date.replace('Jun ', '')}</span>
                </div>
              ))}
            </div>
            <div className="flex gap-4 mt-3">
              {[['Confirmed','bg-emerald-500/70'],['Returned','bg-red-500/50'],['Human','bg-amber-500/50']].map(([l,c]) => (
                <div key={l} className="flex items-center gap-1.5">
                  <div className={`w-2.5 h-2.5 rounded-sm ${c}`} />
                  <span className={`text-[10px] ${th.legend}`}>{l}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Fraud score distribution */}
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-sm font-medium ${th.heading} mb-4`}>Fraud Score Distribution (today)</div>
            <div className="space-y-2">
              {FRAUD_DIST.map(d => (
                <div key={d.range} className="flex items-center gap-3">
                  <span className={`text-[10px] ${th.muted} w-16 shrink-0`}>{d.range}</span>
                  <div className={`flex-1 ${th.bar} rounded-full h-2`}>
                    <div
                      className={`h-2 rounded-full ${d.range.startsWith('70') || d.range.startsWith('90') ? 'bg-red-500' : 'bg-amber-400/70'}`}
                      style={{ width: `${(d.count / maxFraud) * 100}%` }}
                    />
                  </div>
                  <span className={`text-[10px] ${th.muted} w-6 text-right`}>{d.count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Return reasons */}
        <div className={`border rounded-xl p-4 ${th.card}`}>
          <div className={`text-sm font-medium ${th.heading} mb-4`}>STP Return Reasons (7-day)</div>
          <div className="space-y-2">
            {RETURN_REASONS.map(d => (
              <div key={d.reason} className="flex items-center gap-3">
                <span className={`text-[10px] ${th.muted} w-32 shrink-0`}>{d.reason.replace(/_/g, ' ')}</span>
                <div className={`flex-1 ${th.bar} rounded-full h-2`}>
                  <div className="h-2 rounded-full bg-red-500/60" style={{ width: `${(d.count / maxReturn) * 100}%` }} />
                </div>
                <span className={`text-[10px] ${th.muted} w-6 text-right`}>{d.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  )
}
