/**
 * CTS Settlement View — clearing session lifecycle + net settlement position.
 *
 * Shows:
 *   - Each clearing session: OPEN → PROCESSING → FILED → NGCH_ACK → SETTLED
 *   - Net payable / receivable per counterparty bank
 *   - NGCH acknowledgement status
 *   - Settlement finality tracker
 *   - Download: settlement position statement
 */
import { useState, useMemo } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Mock data ────────────────────────────────────────────────────────────────

const SB_SESSIONS = [
  {
    id: 'SES-20260625-001', slot: '10:00–12:00', status: 'SETTLED',
    inward: 1840, inward_val_cr: 42.3, outward: 1210, outward_val_cr: 28.1,
    ngch_ack: '12:03:14', settled_at: '14:22:07',
    net_cr: 14.2, net_dir: 'RECEIVE',
  },
  {
    id: 'SES-20260625-002', slot: '12:00–14:00', status: 'FILED',
    inward: 2105, inward_val_cr: 53.7, outward: 1380, outward_val_cr: 31.4,
    ngch_ack: '14:11:33', settled_at: null,
    net_cr: 22.3, net_dir: 'RECEIVE',
  },
  {
    id: 'SES-20260625-003', slot: '14:00–16:00', status: 'OPEN',
    inward: 1230, inward_val_cr: 29.8, outward: 890, outward_val_cr: 19.2,
    ngch_ack: null, settled_at: null,
    net_cr: 10.6, net_dir: 'RECEIVE',
  },
  {
    id: 'SES-20260625-004', slot: '16:00–18:00', status: 'UPCOMING',
    inward: 0, inward_val_cr: 0, outward: 0, outward_val_cr: 0,
    ngch_ack: null, settled_at: null,
    net_cr: 0, net_dir: 'TBD',
  },
]

function makeSmbSessions(bankIfsc) {
  const p = `SES-${bankIfsc}-20260625`
  return [
    {
      id: `${p}-001`, slot: '10:00–12:00', status: 'SETTLED',
      inward: 143, inward_val_cr: 3.8, outward: 92, outward_val_cr: 2.1,
      ngch_ack: '12:05:41', settled_at: '14:24:17',
      net_cr: 1.7, net_dir: 'RECEIVE',
    },
    {
      id: `${p}-002`, slot: '12:00–14:00', status: 'OPEN',
      inward: 175, inward_val_cr: 4.65, outward: 115, outward_val_cr: 2.9,
      ngch_ack: null, settled_at: null,
      net_cr: 1.75, net_dir: 'RECEIVE',
    },
  ]
}

const SB_COUNTERPARTIES = [
  { ifsc: 'SBIN0000001', name: 'State Bank of India',   ours_cr: 12.3, theirs_cr: 4.1,  net_cr: 8.2,  dir: 'RECEIVE' },
  { ifsc: 'ICIC0000001', name: 'ICICI Bank',            ours_cr: 7.1,  theirs_cr: 9.8,  net_cr: 2.7,  dir: 'PAY' },
  { ifsc: 'UTIB0000001', name: 'Axis Bank',             ours_cr: 5.4,  theirs_cr: 2.1,  net_cr: 3.3,  dir: 'RECEIVE' },
  { ifsc: 'KKBK0000001', name: 'Kotak Mahindra Bank',  ours_cr: 9.8,  theirs_cr: 3.2,  net_cr: 6.6,  dir: 'RECEIVE' },
  { ifsc: 'YESB0000001', name: 'Yes Bank',              ours_cr: 3.9,  theirs_cr: 5.6,  net_cr: 1.7,  dir: 'PAY' },
  { ifsc: 'INDB0000001', name: 'IndusInd Bank',         ours_cr: 6.2,  theirs_cr: 2.8,  net_cr: 3.4,  dir: 'RECEIVE' },
  { ifsc: 'PUNB0000001', name: 'Punjab National Bank',  ours_cr: 4.1,  theirs_cr: 1.9,  net_cr: 2.2,  dir: 'RECEIVE' },
]

// SMB settles through its Sponsor Bank only — single counterparty
const SMB_COUNTERPARTIES = [
  { ifsc: 'SRCB0000001', name: 'Saraswat Co-op Bank (Sponsor)', ours_cr: 8.45, theirs_cr: 5.80, net_cr: 2.65, dir: 'RECEIVE' },
]

const PIPELINE_STEPS = ['OPEN', 'PROCESSING', 'FILED', 'NGCH_ACK', 'SETTLED']
const STEP_IDX = { OPEN: 0, PROCESSING: 1, FILED: 2, NGCH_ACK: 3, SETTLED: 4, UPCOMING: -1 }

// ─── Sub-components ───────────────────────────────────────────────────────────

function Pipeline({ status, isDark }) {
  const current = STEP_IDX[status] ?? -1
  const dot = (i) => {
    if (i < current)  return isDark ? 'bg-emerald-500 border-emerald-500' : 'bg-emerald-600 border-emerald-600'
    if (i === current) return isDark ? 'bg-gold-400 border-gold-400 ring-2 ring-gold-400/30' : 'bg-amber-500 border-amber-500 ring-2 ring-amber-400/30'
    return isDark ? 'bg-transparent border-white/20' : 'bg-transparent border-slate-300'
  }
  const line = (i) => i < current
    ? (isDark ? 'bg-emerald-500' : 'bg-emerald-600')
    : (isDark ? 'bg-white/10' : 'bg-slate-200')
  const label = (i) => {
    if (i < current)  return isDark ? 'text-emerald-400' : 'text-emerald-600'
    if (i === current) return isDark ? 'text-gold-400' : 'text-amber-600'
    return isDark ? 'text-slate-600' : 'text-slate-400'
  }
  if (status === 'UPCOMING') return <div className={`text-[11px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Not yet opened</div>
  return (
    <div className="w-full overflow-hidden">
      <div className="grid grid-cols-5 w-full relative">
        {PIPELINE_STEPS.map((step, i) => (
          <div key={step} className="flex flex-col items-center relative">
            {i > 0 && (
              <div className={`absolute top-1.5 right-1/2 left-0 h-0.5 transition-all ${line(i - 1)}`} />
            )}
            {i < PIPELINE_STEPS.length - 1 && (
              <div className={`absolute top-1.5 left-1/2 right-0 h-0.5 transition-all ${line(i)}`} />
            )}
            <div className={`w-3 h-3 rounded-full border-2 transition-all relative z-10 ${dot(i)}`} />
            <span className={`text-[9px] mt-1 text-center leading-tight w-full ${label(i)}`}>{step.replace('_', ' ')}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSSettlement() {
  const { isDark } = useTheme()
  const { bankName, bankIfsc, isSMB } = useBankContext()

  const SESSIONS      = useMemo(() => isSMB ? makeSmbSessions(bankIfsc) : SB_SESSIONS, [bankIfsc, isSMB])
  const COUNTERPARTIES = isSMB ? SMB_COUNTERPARTIES : SB_COUNTERPARTIES

  const [selectedSession, setSelectedSession] = useState(null)
  const activeSessionId = selectedSession ?? SESSIONS[1]?.id ?? SESSIONS[0]?.id

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    tab:     (a) => a
      ? (isDark ? 'bg-white/10 text-white border-white/20' : 'bg-slate-900 text-white border-slate-900')
      : (isDark ? 'text-slate-400 border-white/8 hover:text-white' : 'text-slate-500 border-slate-200 hover:text-slate-800'),
  }

  const sel = SESSIONS.find(s => s.id === activeSessionId) || SESSIONS[0]
  const totalReceive = COUNTERPARTIES.filter(c => c.dir === 'RECEIVE').reduce((s, c) => s + c.net_cr, 0)
  const totalPay     = COUNTERPARTIES.filter(c => c.dir === 'PAY').reduce((s, c) => s + c.net_cr, 0)

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>
        {/* Header */}
        <div className={`sticky top-0 z-10 ${isDark ? 'bg-navy-950/95' : 'bg-slate-50/95'} backdrop-blur border-b ${th.divider} px-6 py-3`}>
          <div className="flex items-center justify-between">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>Settlement Position</h1>
              <p className={`text-[11px] ${th.muted}`}>
                {bankName} · Clearing session lifecycle &amp; net payable/receivable
                {isSMB && <span className="ml-2 text-amber-400">· settled via Sponsor Bank</span>}
              </p>
            </div>
            <button className={`text-[11px] px-3 py-1.5 rounded-lg border transition-colors
              ${isDark ? 'border-white/15 text-slate-300 hover:text-white hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-100'}`}>
              ↓ Settlement Statement
            </button>
          </div>
        </div>

        <div className="px-6 py-5 max-w-7xl space-y-5">

          {/* Session cards with pipeline */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            {SESSIONS.map(s => (
              <div
                key={s.id}
                onClick={() => setSelectedSession(s.id)}
                className={`border rounded-xl p-4 cursor-pointer transition-all ${
                  activeSessionId === s.id
                    ? (isDark ? 'border-gold-400/40 bg-gold-400/5' : 'border-amber-400 bg-amber-50')
                    : th.card
                }`}
              >
                <div className="flex justify-between items-start mb-3">
                  <div className={`text-sm font-semibold ${th.heading}`}>{s.slot}</div>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full border ${
                    s.status === 'SETTLED'  ? 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20' :
                    s.status === 'FILED'    ? 'bg-blue-400/10 text-blue-400 border-blue-400/20' :
                    s.status === 'OPEN'     ? 'bg-amber-400/10 text-amber-400 border-amber-400/20' :
                    'bg-slate-400/10 text-slate-400 border-slate-400/20'
                  }`}>{s.status}</span>
                </div>
                <Pipeline status={s.status} isDark={isDark} />
                {s.inward > 0 && (
                  <div className={`mt-3 pt-2 border-t ${th.divider} grid grid-cols-2 gap-2`}>
                    <div>
                      <div className={`text-[9px] ${th.muted}`}>Inward</div>
                      <div className={`text-sm font-mono font-bold ${th.heading}`}>₹{s.inward_val_cr}Cr</div>
                    </div>
                    <div>
                      <div className={`text-[9px] ${th.muted}`}>Net</div>
                      <div className={`text-sm font-mono font-bold ${s.net_dir === 'RECEIVE' ? 'text-emerald-400' : 'text-red-400'}`}>
                        {s.net_dir === 'RECEIVE' ? '+' : '-'}₹{s.net_cr}Cr
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Settlement detail for selected session */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* Net summary */}
            <div className={`border rounded-xl p-5 ${th.card}`}>
              <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-4`}>
                Session {sel.slot} — Net Position
              </div>
              <div className="space-y-4">
                <div>
                  <div className={`text-[10px] ${th.muted}`}>Inward (we pay)</div>
                  <div className={`text-2xl font-bold font-mono ${th.heading}`}>₹{sel.inward_val_cr}Cr</div>
                  <div className={`text-[10px] ${th.muted}`}>{sel.inward.toLocaleString()} cheques</div>
                </div>
                <div>
                  <div className={`text-[10px] ${th.muted}`}>Outward (we collect)</div>
                  <div className={`text-2xl font-bold font-mono ${th.heading}`}>₹{sel.outward_val_cr}Cr</div>
                  <div className={`text-[10px] ${th.muted}`}>{sel.outward.toLocaleString()} cheques</div>
                </div>
                <div className={`pt-3 border-t ${th.divider}`}>
                  <div className={`text-[10px] ${th.muted}`}>Net Settlement</div>
                  <div className={`text-3xl font-bold font-mono ${sel.net_dir === 'RECEIVE' ? 'text-emerald-400' : 'text-red-400'}`}>
                    {sel.net_dir === 'RECEIVE' ? '+' : '-'}₹{sel.net_cr}Cr
                  </div>
                  <div className={`text-[11px] font-semibold mt-1 ${sel.net_dir === 'RECEIVE' ? 'text-emerald-400' : 'text-red-400'}`}>
                    {sel.net_dir === 'RECEIVE' ? 'WE RECEIVE' : 'WE PAY'} from NGCH
                  </div>
                </div>
                {sel.ngch_ack && (
                  <div className={`text-[10px] ${th.muted}`}>NGCH Ack: {sel.ngch_ack}</div>
                )}
                {sel.settled_at && (
                  <div className={`text-[10px] text-emerald-400`}>Settled: {sel.settled_at}</div>
                )}
              </div>
            </div>

            {/* Counterparty table */}
            <div className={`lg:col-span-2 border rounded-xl ${th.card}`}>
              <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
                <span className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted}`}>Per-Bank Settlement</span>
                <div className="flex gap-4">
                  <span className="text-[11px] text-emerald-400">Receive: ₹{totalReceive.toFixed(1)}Cr</span>
                  <span className="text-[11px] text-red-400">Pay: ₹{totalPay.toFixed(1)}Cr</span>
                </div>
              </div>
              <table className="w-full text-[12px]">
                <thead>
                  <tr className={`border-b ${th.divider}`}>
                    {['Bank', 'IFSC', 'We Receive (Cr)', 'We Pay (Cr)', 'Net', 'Direction'].map(h => (
                      <th key={h} className={`px-4 py-2 text-left text-[10px] uppercase tracking-wide ${th.muted}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {COUNTERPARTIES.map(c => (
                    <tr key={c.ifsc} className={`border-b ${th.row} transition-colors`}>
                      <td className={`px-4 py-2.5 font-medium ${th.body}`}>{c.name}</td>
                      <td className={`px-4 py-2.5 font-mono text-[10px] ${th.muted}`}>{c.ifsc}</td>
                      <td className={`px-4 py-2.5 font-mono text-emerald-400`}>₹{c.ours_cr}</td>
                      <td className={`px-4 py-2.5 font-mono text-red-400`}>₹{c.theirs_cr}</td>
                      <td className={`px-4 py-2.5 font-mono font-semibold ${c.dir === 'RECEIVE' ? 'text-emerald-400' : 'text-red-400'}`}>
                        {c.dir === 'RECEIVE' ? '+' : '-'}₹{c.net_cr}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${
                          c.dir === 'RECEIVE'
                            ? 'bg-emerald-400/10 text-emerald-400 border-emerald-400/20'
                            : 'bg-red-400/10 text-red-400 border-red-400/20'
                        }`}>{c.dir}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className={`border-t ${th.divider} font-semibold`}>
                    <td colSpan={4} className={`px-4 py-2.5 ${th.muted}`}>Net Position (Day)</td>
                    <td className="px-4 py-2.5 font-mono font-bold text-emerald-400">
                      +₹{(totalReceive - totalPay).toFixed(1)}Cr
                    </td>
                    <td className="px-4 py-2.5 text-[10px] text-emerald-400 font-bold">RECEIVE</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
