import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

const ROUTING_RULES = [
  {
    id: 'R001',
    name: 'Default Mumbai Zone',
    condition: 'MICR prefix 4xxxxx',
    destination: 'CTS-MUMBAI Grid',
    grid: 'MUMBAI',
    priority: 10,
    type: 'ZONE',
    status: 'ACTIVE',
    filings_today: 1842,
  },
  {
    id: 'R002',
    name: 'Default Delhi Zone',
    condition: 'MICR prefix 1xxxxx',
    destination: 'CTS-DELHI Grid',
    grid: 'DELHI',
    priority: 10,
    type: 'ZONE',
    status: 'ACTIVE',
    filings_today: 934,
  },
  {
    id: 'R003',
    name: 'Default Chennai Zone',
    condition: 'MICR prefix 5xxxxx or 6xxxxx',
    destination: 'CTS-CHENNAI Grid',
    grid: 'CHENNAI',
    priority: 10,
    type: 'ZONE',
    status: 'ACTIVE',
    filings_today: 612,
  },
  {
    id: 'R004',
    name: 'High-Value Override',
    condition: 'Amount > ₹5,00,000 (any zone)',
    destination: 'CTS-MUMBAI Priority Lane',
    grid: 'MUMBAI',
    priority: 5,
    type: 'OVERRIDE',
    status: 'ACTIVE',
    filings_today: 23,
  },
  {
    id: 'R005',
    name: 'Government Cheque Route',
    condition: "Payee name contains 'GOVT OF' or 'INCOME TAX'",
    destination: 'CTS-MUMBAI Govt Lane',
    grid: 'MUMBAI',
    priority: 3,
    type: 'SPECIAL',
    status: 'ACTIVE',
    filings_today: 87,
  },
  {
    id: 'R006',
    name: 'Sub-Member Sponsor Route',
    condition: 'Drawee bank is sponsored sub-member',
    destination: 'Sponsor Bank Clearing Account',
    grid: 'SPONSOR',
    priority: 4,
    type: 'SUB_MEMBER',
    status: 'ACTIVE',
    filings_today: 312,
  },
  {
    id: 'R007',
    name: 'IET Emergency Fallback',
    condition: 'T-30s watchdog trigger (any zone)',
    destination: 'Emergency NGCH Queue (any available grid)',
    grid: 'ANY',
    priority: 1,
    type: 'EMERGENCY',
    status: 'ACTIVE',
    filings_today: 0,
  },
]

const NGCH_STATUS = {
  connectivity: 'CONNECTED',
  last_batch_filed: '2026-06-25 13:47:22',
  pending_queue: 3,
  total_filed_today: 3810,
  avg_ack_latency_ms: 340,
  sftp_host: 'ngch.npci.org.in',
  cert_expiry: '2027-01-14',
}

const TYPE_COLORS_D = {
  ZONE: 'bg-blue-900/40 text-blue-300 border-blue-700/50',
  OVERRIDE: 'bg-violet-900/40 text-violet-300 border-violet-700/50',
  SPECIAL: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  SUB_MEMBER: 'bg-cyan-900/40 text-cyan-300 border-cyan-700/50',
  EMERGENCY: 'bg-red-900/40 text-red-300 border-red-700/50',
}
const TYPE_COLORS_L = {
  ZONE: 'bg-blue-100 text-blue-700 border-blue-300',
  OVERRIDE: 'bg-violet-100 text-violet-700 border-violet-300',
  SPECIAL: 'bg-amber-100 text-amber-700 border-amber-300',
  SUB_MEMBER: 'bg-cyan-100 text-cyan-700 border-cyan-300',
  EMERGENCY: 'bg-red-100 text-red-700 border-red-300',
}

export default function CTSNGCHRouting() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3 cursor-pointer' : 'border-slate-100 hover:bg-slate-50 cursor-pointer',
  }
  const TYPE = isDark ? TYPE_COLORS_D : TYPE_COLORS_L

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>NGCH Routing</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Routing rules that determine how filed decisions are dispatched to NPCI's clearing grids</p>
          </div>
        </div>

        {/* NGCH Connection Status */}
        <div className={`rounded-xl border p-4 mb-5 ${th.card}`}>
          <div className="flex items-center justify-between mb-3">
            <span className={`text-xs font-semibold ${th.muted}`}>NGCH CONNECTIVITY</span>
            <span className={`flex items-center gap-1.5 text-xs font-medium ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {NGCH_STATUS.connectivity}
            </span>
          </div>
          <div className="grid grid-cols-5 gap-4 text-xs">
            {[
              ['SFTP Host', NGCH_STATUS.sftp_host],
              ['Filed Today', NGCH_STATUS.total_filed_today.toLocaleString()],
              ['Pending Queue', NGCH_STATUS.pending_queue],
              ['Avg ACK Latency', `${NGCH_STATUS.avg_ack_latency_ms} ms`],
              ['Cert Expiry', NGCH_STATUS.cert_expiry],
            ].map(([label, val]) => (
              <div key={label}>
                <div className={th.muted}>{label}</div>
                <div className={`font-medium mt-0.5 ${th.heading}`}>{val}</div>
              </div>
            ))}
          </div>
          <div className={`mt-3 pt-3 border-t text-xs ${th.divider} ${th.muted}`}>
            Last batch filed: <span className={`font-mono ${th.body}`}>{NGCH_STATUS.last_batch_filed}</span>
          </div>
        </div>

        {/* Routing rules */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <div className={`px-4 py-3 border-b flex items-center justify-between ${th.divider}`}>
            <span className={`text-xs font-semibold ${th.muted}`}>ROUTING RULES — evaluated in priority order (lower = higher priority)</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Priority', 'Rule Name', 'Condition', 'Destination Grid', 'Type', 'Filed Today', 'Status', ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROUTING_RULES.sort((a, b) => a.priority - b.priority).map(r => (
                <tr key={r.id} className={`border-b transition-colors ${th.row}`} onClick={() => setSelected(r)}>
                  <td className={`px-4 py-3 font-mono font-bold ${r.priority <= 3 ? (isDark ? 'text-red-300' : 'text-red-600') : th.heading}`}>
                    P{r.priority}
                  </td>
                  <td className={`px-4 py-3 font-medium ${th.heading}`}>{r.name}</td>
                  <td className={`px-4 py-3 font-mono text-[11px] max-w-[200px] truncate ${th.muted}`} title={r.condition}>{r.condition}</td>
                  <td className={`px-4 py-3 ${th.body}`}>{r.destination.split('(')[0].trim()}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${TYPE[r.type]}`}>{r.type}</span>
                  </td>
                  <td className={`px-4 py-3 font-mono ${th.body}`}>{r.filings_today.toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${r.status === 'ACTIVE' ? (isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-100 text-emerald-700') : (isDark ? 'bg-slate-700 text-slate-400' : 'bg-slate-100 text-slate-500')}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button className={`text-[11px] ${isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700'}`}>Detail →</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Detail panel */}
        {selected && (
          <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <h2 className={`font-semibold ${th.heading}`}>{selected.name}</h2>
                <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${TYPE[selected.type]}`}>{selected.type}</span>
              </div>
              <button onClick={() => setSelected(null)} className={th.muted}>✕ Close</button>
            </div>
            <div className="grid grid-cols-2 gap-4 text-xs mb-4">
              <div>
                <div className={th.muted}>Condition</div>
                <div className={`font-mono mt-0.5 ${th.body}`}>{selected.condition}</div>
              </div>
              <div>
                <div className={th.muted}>Destination</div>
                <div className={`font-medium mt-0.5 ${th.heading}`}>{selected.destination}</div>
              </div>
              <div>
                <div className={th.muted}>Priority</div>
                <div className={`font-bold text-lg mt-0.5 ${th.heading}`}>P{selected.priority}</div>
              </div>
              <div>
                <div className={th.muted}>Filings Today</div>
                <div className={`font-bold text-lg mt-0.5 ${th.heading}`}>{selected.filings_today.toLocaleString()}</div>
              </div>
            </div>
            {selected.type === 'EMERGENCY' && (
              <div className={`p-3 rounded-lg text-xs ${isDark ? 'bg-red-900/20 border border-red-700/40 text-red-300' : 'bg-red-50 border border-red-200 text-red-700'}`}>
                🔒 Emergency routing rule — cannot be edited. Managed by IETWatchdogWorkflow. Fires automatically at T-30s before IET deadline.
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  )
}
