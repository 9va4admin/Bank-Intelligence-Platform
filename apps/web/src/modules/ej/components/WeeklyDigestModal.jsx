import { X } from 'lucide-react'

const DIGEST_DATA = {
  period: 'June 11 – June 18, 2026',
  bank: 'Astra National Bank',
  generated: '18 Jun 2026, 09:00 IST',
  kpis: [
    { label: 'Total ATMs Monitored', value: '247', delta: '+3', up: true },
    { label: 'Avg Uptime', value: '98.7%', delta: '+0.4%', up: true },
    { label: 'Total Transactions', value: '1,84,209', delta: '+12%', up: true },
    { label: 'Incidents Raised', value: '23', delta: '-6', up: false },
    { label: 'SLA Breached', value: '2', delta: '-1', up: false },
    { label: 'Auto-Resolved', value: '18', delta: '+4', up: true },
  ],
  topIssues: [
    { type: 'Cash Near Empty', count: 9, atms: 'ATM-MUM-012, ATM-DEL-003, +7' },
    { type: 'Card Retention', count: 5, atms: 'ATM-MUM-004, ATM-BLR-002, +3' },
    { type: 'Cash Not Dispensed', count: 4, atms: 'ATM-CHN-001, ATM-PNQ-005, +2' },
    { type: 'Comm Failure >15m', count: 3, atms: 'ATM-DEL-007, +2' },
    { type: 'High Txn Velocity', count: 2, atms: 'ATM-MUM-001, ATM-BLR-001' },
  ],
  cityHealth: [
    { city: 'Mumbai', atms: 68, healthy: 64, degraded: 3, offline: 1, uptime: '99.1%' },
    { city: 'Delhi', atms: 52, healthy: 49, degraded: 2, offline: 1, uptime: '98.6%' },
    { city: 'Bangalore', atms: 45, healthy: 43, degraded: 2, offline: 0, uptime: '99.3%' },
    { city: 'Pune', atms: 38, healthy: 36, degraded: 1, offline: 1, uptime: '97.9%' },
    { city: 'Chennai', atms: 44, healthy: 41, degraded: 3, offline: 0, uptime: '98.0%' },
  ],
  recommendations: [
    'Schedule cash replenishment for 9 ATMs in Mumbai & Delhi before weekend',
    'Inspect card reader on ATM-MUM-004 — 3 card retention events this week',
    'ATM-PNQ-011 offline >24h — dispatch field engineer',
    'Consider increasing cash float at ATM-BLR-001 (peak volume, 2× avg txn)',
  ],
  nextDigest: 'June 25, 2026 · 09:00 IST',
}

export default function WeeklyDigestModal({ open, onClose, role }) {
  if (!open) return null
  const d = DIGEST_DATA

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-xl border border-white/10 shadow-2xl bg-[#0d1117]">
        {/* Email-style header */}
        <div className="bg-gradient-to-r from-violet-900/60 to-cyan-900/40 px-6 py-4 flex items-start justify-between border-b border-white/10">
          <div>
            <div className="text-xs text-slate-400 mb-1">AUTO-GENERATED · WEEKLY DIGEST</div>
            <h2 className="text-lg font-bold text-white">ATM Fleet Health Report</h2>
            <div className="text-sm text-slate-300 mt-0.5">{d.bank} · {d.period}</div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white mt-1">
            <X size={20} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-6">
          {/* Meta */}
          <div className="flex gap-6 text-xs text-slate-400">
            <span>Generated: <span className="text-slate-200">{d.generated}</span></span>
            <span>Recipient role: <span className="text-cyan-400 font-medium">{role || 'National Head'}</span></span>
            <span>Delivered via: <span className="text-slate-200">Email (Postal SMTP)</span></span>
          </div>

          {/* KPI grid */}
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Weekly Snapshot</h3>
            <div className="grid grid-cols-3 gap-3">
              {d.kpis.map(k => (
                <div key={k.label} className="bg-white/5 rounded-lg px-4 py-3">
                  <div className="text-xs text-slate-400 mb-1">{k.label}</div>
                  <div className="text-xl font-bold text-white">{k.value}</div>
                  <div className={`text-xs mt-0.5 ${k.up ? 'text-emerald-400' : 'text-red-400'}`}>
                    {k.delta} vs last week
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* City health */}
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">City-wise ATM Health</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-white/5">
                  <th className="pb-2">City</th>
                  <th className="pb-2 text-right">ATMs</th>
                  <th className="pb-2 text-right text-emerald-400">Healthy</th>
                  <th className="pb-2 text-right text-amber-400">Degraded</th>
                  <th className="pb-2 text-right text-slate-500">Offline</th>
                  <th className="pb-2 text-right">Uptime</th>
                </tr>
              </thead>
              <tbody>
                {d.cityHealth.map(c => (
                  <tr key={c.city} className="border-b border-white/5 text-slate-300">
                    <td className="py-2 font-medium">{c.city}</td>
                    <td className="py-2 text-right">{c.atms}</td>
                    <td className="py-2 text-right text-emerald-400">{c.healthy}</td>
                    <td className="py-2 text-right text-amber-400">{c.degraded}</td>
                    <td className="py-2 text-right text-slate-500">{c.offline}</td>
                    <td className="py-2 text-right text-white font-mono">{c.uptime}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Top issues */}
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Top Issues This Week</h3>
            <div className="space-y-2">
              {d.topIssues.map((issue, i) => (
                <div key={i} className="flex items-center gap-3 bg-white/5 rounded-lg px-4 py-2.5">
                  <span className="text-lg font-bold text-slate-500 w-5 text-right">{i + 1}</span>
                  <div className="flex-1">
                    <span className="text-sm font-medium text-white">{issue.type}</span>
                    <span className="text-xs text-slate-500 ml-2">{issue.atms}</span>
                  </div>
                  <span className="text-sm font-bold text-amber-400">{issue.count} incidents</span>
                </div>
              ))}
            </div>
          </section>

          {/* Recommendations */}
          <section>
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Recommended Actions</h3>
            <ul className="space-y-2">
              {d.recommendations.map((r, i) => (
                <li key={i} className="flex gap-2 text-sm text-slate-300">
                  <span className="text-cyan-400 mt-0.5">→</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </section>

          {/* Footer */}
          <div className="border-t border-white/10 pt-4 flex items-center justify-between text-xs text-slate-500">
            <span>Next digest scheduled: <span className="text-slate-300">{d.nextDigest}</span></span>
            <span className="text-violet-400">ASTRA EJ Intelligence Platform</span>
          </div>
        </div>
      </div>
    </div>
  )
}
