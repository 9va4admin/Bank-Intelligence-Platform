import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

const SB_DAILY = [
  { date: 'Jun 13', total: 4820, stp_confirm: 3921, stp_return: 641, human: 258, avg_ms: 389 },
  { date: 'Jun 14', total: 5210, stp_confirm: 4281, stp_return: 721, human: 208, avg_ms: 372 },
  { date: 'Jun 15', total: 4980, stp_confirm: 4101, stp_return: 681, human: 198, avg_ms: 401 },
  { date: 'Jun 16', total: 5310, stp_confirm: 4441, stp_return: 741, human: 128, avg_ms: 358 },
  { date: 'Jun 17', total: 4740, stp_confirm: 3881, stp_return: 631, human: 228, avg_ms: 413 },
  { date: 'Jun 18', total: 5430, stp_confirm: 4561, stp_return: 711, human: 158, avg_ms: 344 },
  { date: 'Jun 19', total: 1230, stp_confirm: 1041, stp_return: 171, human:  18, avg_ms: 361 },
]

const SMB_DAILY = [
  { date: 'Jun 13', total: 295, stp_confirm: 243, stp_return: 38, human: 14, avg_ms: 391 },
  { date: 'Jun 14', total: 312, stp_confirm: 258, stp_return: 41, human: 13, avg_ms: 374 },
  { date: 'Jun 15', total: 298, stp_confirm: 247, stp_return: 38, human: 13, avg_ms: 403 },
  { date: 'Jun 16', total: 321, stp_confirm: 268, stp_return: 42, human: 11, avg_ms: 360 },
  { date: 'Jun 17', total: 287, stp_confirm: 235, stp_return: 38, human: 14, avg_ms: 415 },
  { date: 'Jun 18', total: 331, stp_confirm: 275, stp_return: 43, human: 13, avg_ms: 346 },
  { date: 'Jun 19', total:  79, stp_confirm:  65, stp_return: 10, human:  4, avg_ms: 363 },
]

const SB_FRAUD_DIST = [
  { range: '0–10%',   count: 3120 },
  { range: '10–30%',  count: 890  },
  { range: '30–50%',  count: 410  },
  { range: '50–70%',  count: 280  },
  { range: '70–90%',  count: 310  },
  { range: '90–100%', count: 440  },
]

const SMB_FRAUD_DIST = [
  { range: '0–10%',   count: 189 },
  { range: '10–30%',  count: 54  },
  { range: '30–50%',  count: 25  },
  { range: '50–70%',  count: 17  },
  { range: '70–90%',  count: 18  },
  { range: '90–100%', count: 27  },
]

const SB_RETURN_REASONS = [
  { reason: 'FRAUD_RISK',   count: 440 },
  { reason: 'SIG_MISMATCH', count: 310 },
  { reason: 'ALTERATION',   count: 180 },
  { reason: 'FUNDS_SHORT',  count: 90  },
  { reason: 'OTHER',        count: 40  },
]

const SMB_RETURN_REASONS = [
  { reason: 'FRAUD_RISK',   count: 27 },
  { reason: 'SIG_MISMATCH', count: 18 },
  { reason: 'ALTERATION',   count: 11 },
  { reason: 'FUNDS_SHORT',  count: 5  },
  { reason: 'OTHER',        count: 2  },
]

const MODEL_PERF = [
  { model: 'GOT-OCR2',       metric: 'Accuracy',        value: 99.3,  threshold: 99.0, status: 'OK'  },
  { model: 'Siamese-SigNet', metric: 'Precision',        value: 97.8,  threshold: 97.0, status: 'OK'  },
  { model: 'XGBoost-Fraud',  metric: 'F1 Score',         value: 0.934, threshold: 0.920, status: 'OK' },
  { model: 'Qwen2-VL',       metric: 'Confidence Mean',  value: 0.912, threshold: 0.900, status: 'OK' },
]

const IET_TREND = [
  { date: 'Jun 13', nearBreach: 2 },
  { date: 'Jun 14', nearBreach: 0 },
  { date: 'Jun 15', nearBreach: 1 },
  { date: 'Jun 16', nearBreach: 0 },
  { date: 'Jun 17', nearBreach: 3 },
  { date: 'Jun 18', nearBreach: 0 },
  { date: 'Jun 19', nearBreach: 0 },
]

// derived below inside component (bank-scoped)
const maxNearBreach = Math.max(...IET_TREND.map(d => d.nearBreach), 1)

const MODEL_STATUS_COLOR = {
  OK:   { badge: 'text-emerald-500', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  WARN: { badge: 'text-amber-500',   bg: 'bg-amber-500/10 border-amber-500/20'     },
  CRIT: { badge: 'text-red-500',     bg: 'bg-red-500/10 border-red-500/20'         },
}
const MODEL_STATUS_COLOR_L = {
  OK:   { badge: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  WARN: { badge: 'text-amber-700',   bg: 'bg-amber-50 border-amber-200'     },
  CRIT: { badge: 'text-red-700',     bg: 'bg-red-50 border-red-200'         },
}

export default function CTSAnalytics() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()

  const DAILY          = isSMB ? SMB_DAILY          : SB_DAILY
  const FRAUD_DIST     = isSMB ? SMB_FRAUD_DIST     : SB_FRAUD_DIST
  const RETURN_REASONS = isSMB ? SMB_RETURN_REASONS : SB_RETURN_REASONS

  const maxFraud  = Math.max(...FRAUD_DIST.map(d => d.count))
  const maxReturn = Math.max(...RETURN_REASONS.map(d => d.count))
  const maxTotal  = Math.max(...DAILY.map(d => d.total))

  const weekTotal   = DAILY.reduce((s, d) => s + d.total, 0)
  const weekConfirm = DAILY.reduce((s, d) => s + d.stp_confirm, 0)
  const weekHuman   = DAILY.reduce((s, d) => s + d.human, 0)
  const stpRate     = ((weekConfirm / weekTotal) * 100).toFixed(1)
  const humanRate   = ((weekHuman / weekTotal) * 100).toFixed(1)
  const avgMs       = Math.round(DAILY.reduce((s, d) => s + d.avg_ms, 0) / DAILY.length)

  const th = {
    page:     isDark ? 'bg-navy-950'                              : 'bg-slate-50',
    card:     isDark ? 'bg-navy-900 border-white/8'               : 'bg-white border-slate-200',
    heading:  isDark ? 'text-white'                               : 'text-slate-900',
    body:     isDark ? 'text-slate-300'                           : 'text-slate-700',
    muted:    isDark ? 'text-slate-400'                           : 'text-slate-500',
    faint:    isDark ? 'text-slate-600'                           : 'text-slate-400',
    divider:  isDark ? 'border-white/8'                           : 'border-slate-200',
    dividerSm:isDark ? 'border-white/5'                           : 'border-slate-100',
    row:      isDark ? 'border-white/4 hover:bg-white/2'          : 'border-slate-100 hover:bg-slate-50',
    thCell:   isDark ? 'text-slate-500'                           : 'text-slate-400',
    bar:      isDark ? 'bg-white/5'                               : 'bg-slate-100',
    dateLbl:  isDark ? 'text-slate-500'                           : 'text-slate-400',
    legend:   isDark ? 'text-slate-500'                           : 'text-slate-500',
    totals:   isDark ? 'bg-white/5 text-slate-200 font-semibold'  : 'bg-slate-50 text-slate-800 font-semibold',
  }

  const MSC = isDark ? MODEL_STATUS_COLOR : MODEL_STATUS_COLOR_L

  usePageHeader({ subtitle: 'Decision analytics · AI model performance · IET safety · 7-day rolling view' })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* KPI strip — 5 cards */}
        <div className="grid grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Total Processed (7d)', value: weekTotal.toLocaleString(), color: th.heading },
            { label: 'STP Rate',             value: `${stpRate}%`,              color: 'text-emerald-500' },
            { label: 'Avg Decision Time',    value: `${avgMs}ms`,               color: 'text-amber-500' },
            { label: 'IET Breaches',         value: '0',                        color: 'text-emerald-500' },
            { label: 'Human Review Rate',    value: `${humanRate}%`,            color: 'text-amber-500' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Daily throughput table */}
        <div className={`border rounded-xl mb-4 ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider}`}>
            <span className={`text-sm font-medium ${th.heading}`}>Daily Throughput — 7 Days</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thCell} border-b ${th.dividerSm}`}>
                <th className="text-left px-4 py-2 font-normal">Date</th>
                <th className="text-right px-4 py-2 font-normal">Total</th>
                <th className="text-right px-4 py-2 font-normal">STP Confirm</th>
                <th className="text-right px-4 py-2 font-normal">STP Return</th>
                <th className="text-right px-4 py-2 font-normal">Human Review</th>
                <th className="text-right px-4 py-2 font-normal">Avg Time</th>
                <th className="text-right px-4 py-2 font-normal">STP Rate</th>
              </tr>
            </thead>
            <tbody>
              {DAILY.map((d, i) => (
                <tr key={i} className={`border-b ${th.row} transition-colors`}>
                  <td className={`px-4 py-2.5 ${th.body}`}>{d.date}</td>
                  <td className={`px-4 py-2.5 ${th.heading} text-right font-medium`}>{d.total}</td>
                  <td className="px-4 py-2.5 text-emerald-500 text-right">{d.stp_confirm}</td>
                  <td className="px-4 py-2.5 text-red-400 text-right">{d.stp_return}</td>
                  <td className="px-4 py-2.5 text-amber-500 text-right">{d.human}</td>
                  <td className={`px-4 py-2.5 ${th.muted} text-right font-mono`}>{d.avg_ms}ms</td>
                  <td className="px-4 py-2.5 text-emerald-500 text-right">
                    {((d.stp_confirm / d.total) * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
              {/* Totals row */}
              <tr className={th.totals}>
                <td className="px-4 py-2.5">Total / Avg</td>
                <td className="px-4 py-2.5 text-right">{weekTotal.toLocaleString()}</td>
                <td className="px-4 py-2.5 text-right text-emerald-500">{weekConfirm.toLocaleString()}</td>
                <td className="px-4 py-2.5 text-right text-red-400">{DAILY.reduce((s,d)=>s+d.stp_return,0)}</td>
                <td className="px-4 py-2.5 text-right text-amber-500">{weekHuman}</td>
                <td className="px-4 py-2.5 text-right font-mono">{avgMs}ms</td>
                <td className="px-4 py-2.5 text-right text-emerald-500">{stpRate}%</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          {/* Fraud score distribution */}
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-sm font-medium ${th.heading} mb-4`}>Fraud Score Distribution (today)</div>
            <div className="space-y-2.5">
              {FRAUD_DIST.map(d => (
                <div key={d.range} className="flex items-center gap-3">
                  <span className={`text-[10px] ${th.muted} w-16 shrink-0`}>{d.range}</span>
                  <div className={`flex-1 ${th.bar} rounded-full h-3`}>
                    <div
                      className={`h-3 rounded-full ${d.range.startsWith('70') || d.range.startsWith('90') ? 'bg-red-500' : 'bg-amber-400/70'}`}
                      style={{ width: `${(d.count / maxFraud) * 100}%` }}
                    />
                  </div>
                  <span className={`text-[10px] ${th.muted} w-8 text-right`}>{d.count}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Return reasons */}
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-sm font-medium ${th.heading} mb-4`}>STP Return Reasons (7-day)</div>
            <div className="space-y-2.5">
              {RETURN_REASONS.map(d => (
                <div key={d.reason} className="flex items-center gap-3">
                  <span className={`text-[10px] ${th.muted} w-28 shrink-0`}>{d.reason.replace(/_/g, ' ')}</span>
                  <div className={`flex-1 ${th.bar} rounded-full h-3`}>
                    <div className="h-3 rounded-full bg-red-500/60" style={{ width: `${(d.count / maxReturn) * 100}%` }} />
                  </div>
                  <span className={`text-[10px] ${th.muted} w-6 text-right`}>{d.count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* AI model performance */}
        <div className={`border rounded-xl mb-4 ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider}`}>
            <span className={`text-sm font-medium ${th.heading}`}>AI Model Performance</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thCell} border-b ${th.dividerSm}`}>
                <th className="text-left px-4 py-2 font-normal">Model</th>
                <th className="text-left px-4 py-2 font-normal">Metric</th>
                <th className="text-right px-4 py-2 font-normal">Value</th>
                <th className="text-right px-4 py-2 font-normal">Threshold</th>
                <th className="text-right px-4 py-2 font-normal">Margin</th>
                <th className="text-right px-4 py-2 font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {MODEL_PERF.map((m, i) => {
                const margin = (m.value - m.threshold)
                const marginStr = margin >= 0 ? `+${margin.toFixed(3)}` : margin.toFixed(3)
                const sc = MSC[m.status]
                return (
                  <tr key={i} className={`border-b ${th.row} transition-colors`}>
                    <td className={`px-4 py-3 ${th.heading} font-medium`}>{m.model}</td>
                    <td className={`px-4 py-3 ${th.body}`}>{m.metric}</td>
                    <td className={`px-4 py-3 text-right font-mono font-semibold ${sc.badge}`}>{m.value}</td>
                    <td className={`px-4 py-3 text-right font-mono ${th.muted}`}>{m.threshold}</td>
                    <td className={`px-4 py-3 text-right font-mono ${margin >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>{marginStr}</td>
                    <td className="px-4 py-3 text-right">
                      <span className={`inline-block text-[10px] font-semibold border rounded px-1.5 py-0.5 ${sc.badge} ${sc.bg}`}>
                        {m.status}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* IET Safety panel */}
        <div className={`border rounded-xl p-4 ${th.card}`}>
          <div className="flex items-center justify-between mb-4">
            <span className={`text-sm font-medium ${th.heading}`}>IET Safety — 7-Day Near-Breach Trend</span>
            <span className={`text-xs font-bold px-3 py-1 rounded-full border ${isDark ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-emerald-50 text-emerald-700 border-emerald-200'}`}>
              IET Breach Rate: 0.000% &nbsp;·&nbsp; Target: 0.000% ✓
            </span>
          </div>
          <div className="space-y-2">
            {IET_TREND.map(d => (
              <div key={d.date} className="flex items-center gap-3">
                <span className={`text-[10px] ${th.muted} w-12 shrink-0`}>{d.date}</span>
                <div className={`flex-1 ${th.bar} rounded h-4 relative`}>
                  {d.nearBreach > 0 ? (
                    <div
                      className="h-4 rounded bg-amber-500/70"
                      style={{ width: `${(d.nearBreach / maxNearBreach) * 100}%` }}
                    />
                  ) : (
                    <div className="h-4 rounded bg-emerald-500/20" style={{ width: '100%' }} />
                  )}
                </div>
                <span className={`text-[10px] w-24 text-right ${d.nearBreach === 0 ? 'text-emerald-500' : 'text-amber-500'}`}>
                  {d.nearBreach === 0 ? '0 near-breaches ✓' : `${d.nearBreach} near-breach${d.nearBreach > 1 ? 'es' : ''}`}
                </span>
              </div>
            ))}
          </div>
          <div className={`mt-3 text-[10px] ${th.faint}`}>
            Near-breach = cheque processed within 30s of IET deadline. Zero actual breaches in all 7 days.
          </div>
        </div>

      </div>
    </AppShell>
  )
}
