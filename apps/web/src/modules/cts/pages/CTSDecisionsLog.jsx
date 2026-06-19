import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'

const DECISIONS = [
  { id: 'CHQ-2026-001901', account: '****4521', amount: '₹[1L-5L]', payee: 'R***', reason: 'FRAUD_RISK',      outcome: 'STP_RETURN',   agent_ms: 412, fraud: 0.91, ngch: 'ACK-7821', filed: '11:02:14', reviewer: null },
  { id: 'CHQ-2026-001900', account: '****7103', amount: '₹[<1L]',   payee: 'S***', reason: 'CLEAR',           outcome: 'STP_CONFIRM',  agent_ms: 388, fraud: 0.08, ngch: 'ACK-7820', filed: '11:01:52', reviewer: null },
  { id: 'CHQ-2026-001899', account: '****2290', amount: '₹[5L-10L]',payee: 'M***', reason: 'VAULT_MISS',      outcome: 'HUMAN_REVIEW', agent_ms: 201, fraud: null, ngch: 'ACK-7819', filed: '10:58:31', reviewer: 'Rahul S.' },
  { id: 'CHQ-2026-001898', account: '****8812', amount: '₹[<1L]',   payee: 'A***', reason: 'ALTERATION',      outcome: 'STP_RETURN',   agent_ms: 544, fraud: 0.87, ngch: 'ACK-7818', filed: '10:55:09', reviewer: null },
  { id: 'CHQ-2026-001897', account: '****3301', amount: '₹[1L-5L]', payee: 'P***', reason: 'CLEAR',           outcome: 'STP_CONFIRM',  agent_ms: 361, fraud: 0.12, ngch: 'ACK-7817', filed: '10:52:43', reviewer: null },
  { id: 'CHQ-2026-001896', account: '****5509', amount: '₹[>1Cr]',  payee: 'N***', reason: 'HIGH_VALUE',      outcome: 'HUMAN_REVIEW', agent_ms: 298, fraud: 0.44, ngch: 'ACK-7816', filed: '10:49:17', reviewer: 'Priya K.' },
  { id: 'CHQ-2026-001895', account: '****1122', amount: '₹[<1L]',   payee: 'V***', reason: 'CLEAR',           outcome: 'STP_CONFIRM',  agent_ms: 402, fraud: 0.05, ngch: 'ACK-7815', filed: '10:47:01', reviewer: null },
  { id: 'CHQ-2026-001894', account: '****6634', amount: '₹[1L-5L]', payee: 'D***', reason: 'SIG_MISMATCH',   outcome: 'STP_RETURN',   agent_ms: 478, fraud: 0.79, ngch: 'ACK-7814', filed: '10:44:22', reviewer: null },
]

const OUTCOME_STYLE = {
  STP_CONFIRM:  'text-emerald-400 bg-emerald-400/10',
  STP_RETURN:   'text-red-400 bg-red-400/10',
  HUMAN_REVIEW: 'text-amber-400 bg-amber-400/10',
}

const FILTERS = ['All', 'STP_CONFIRM', 'STP_RETURN', 'HUMAN_REVIEW']

export default function CTSDecisionsLog() {
  const [filter, setFilter] = useState('All')

  const rows = filter === 'All' ? DECISIONS : DECISIONS.filter(d => d.outcome === filter)

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-navy-950 px-6 py-5">
        <div className="flex items-center justify-between mb-5">
          <h1 className="text-lg font-semibold text-white">Decisions Log</h1>
          <div className="flex gap-1">
            {FILTERS.map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                  filter === f ? 'bg-gold-400/15 text-gold-400' : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {f.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>

        {/* Summary strip */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Total Filed',     value: DECISIONS.length,                                   color: 'text-white' },
            { label: 'STP Confirmed',   value: DECISIONS.filter(d => d.outcome === 'STP_CONFIRM').length,  color: 'text-emerald-400' },
            { label: 'STP Returned',    value: DECISIONS.filter(d => d.outcome === 'STP_RETURN').length,   color: 'text-red-400' },
            { label: 'Human Review',    value: DECISIONS.filter(d => d.outcome === 'HUMAN_REVIEW').length, color: 'text-amber-400' },
          ].map(s => (
            <div key={s.label} className="bg-navy-900 border border-white/8 rounded-xl px-4 py-3">
              <div className="text-[10px] text-slate-600 mb-1">{s.label}</div>
              <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className="bg-navy-900 border border-white/8 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-600 border-b border-white/8 bg-white/2">
                <th className="text-left px-4 py-3 font-normal">Instrument</th>
                <th className="text-left px-4 py-3 font-normal">Account</th>
                <th className="text-left px-4 py-3 font-normal">Amount</th>
                <th className="text-left px-4 py-3 font-normal">Reason</th>
                <th className="text-left px-4 py-3 font-normal">Outcome</th>
                <th className="text-right px-4 py-3 font-normal">Agent ms</th>
                <th className="text-right px-4 py-3 font-normal">Fraud</th>
                <th className="text-left px-4 py-3 font-normal">NGCH Ref</th>
                <th className="text-left px-4 py-3 font-normal">Filed</th>
                <th className="text-left px-4 py-3 font-normal">Reviewer</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d, i) => (
                <tr key={i} className="border-b border-white/4 hover:bg-white/2 transition-colors">
                  <td className="px-4 py-2.5 text-slate-300 font-mono text-[11px]">{d.id}</td>
                  <td className="px-4 py-2.5 text-slate-400 font-mono">{d.account}</td>
                  <td className="px-4 py-2.5 text-slate-400">{d.amount}</td>
                  <td className="px-4 py-2.5 text-slate-400">{d.reason.replace(/_/g, ' ')}</td>
                  <td className="px-4 py-2.5">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${OUTCOME_STYLE[d.outcome]}`}>
                      {d.outcome.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-300 font-mono">{d.agent_ms}</td>
                  <td className="px-4 py-2.5 text-right">
                    {d.fraud !== null
                      ? <span className={d.fraud > 0.7 ? 'text-red-400' : 'text-emerald-400'}>{(d.fraud * 100).toFixed(0)}%</span>
                      : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono text-[10px]">{d.ngch}</td>
                  <td className="px-4 py-2.5 text-slate-500 font-mono">{d.filed}</td>
                  <td className="px-4 py-2.5 text-slate-500">{d.reviewer ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </AppShell>
  )
}
