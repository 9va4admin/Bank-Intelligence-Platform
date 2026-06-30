import { useState, useMemo } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Mock Data ────────────────────────────────────────────────────────────────

const DISC_TYPES_D = {
  AMOUNT_MISMATCH:   { label: 'Amount Mismatch',        color: 'text-red-400',    bg: 'bg-red-900/30 border-red-700/40',       icon: '₹' },
  MICR_ERROR:        { label: 'MICR Read Error',         color: 'text-orange-400', bg: 'bg-orange-900/30 border-orange-700/40', icon: '⊟' },
  LOT_COUNT_DIFF:    { label: 'Lot Count Mismatch',      color: 'text-amber-400',  bg: 'bg-amber-900/30 border-amber-700/40',   icon: '≠' },
  STALE_DATE:        { label: 'Stale Dated',             color: 'text-violet-400', bg: 'bg-violet-900/30 border-violet-700/40', icon: '📅' },
  POST_DATE:         { label: 'Post Dated',              color: 'text-blue-400',   bg: 'bg-blue-900/30 border-blue-700/40',     icon: '📅' },
  WORDS_FIGURES:     { label: 'Words/Figures Diff',      color: 'text-rose-400',   bg: 'bg-rose-900/30 border-rose-700/40',     icon: 'Ξ' },
  DUPLICATE:         { label: 'Duplicate Instrument',    color: 'text-red-400',    bg: 'bg-red-900/30 border-red-700/40',       icon: '⊕' },
  UNPROCESSED:       { label: 'Unprocessed Item',        color: 'text-slate-400',  bg: 'bg-slate-800/60 border-slate-600/40',   icon: '⌛' },
  EXTENSION_FILE:    { label: 'Extension File Item',     color: 'text-cyan-400',   bg: 'bg-cyan-900/30 border-cyan-700/40',     icon: '↗' },
}
const DISC_TYPES_L = {
  AMOUNT_MISMATCH:   { label: 'Amount Mismatch',        color: 'text-red-700',    bg: 'bg-red-50 border-red-200',              icon: '₹' },
  MICR_ERROR:        { label: 'MICR Read Error',         color: 'text-orange-700', bg: 'bg-orange-50 border-orange-200',        icon: '⊟' },
  LOT_COUNT_DIFF:    { label: 'Lot Count Mismatch',      color: 'text-amber-700',  bg: 'bg-amber-50 border-amber-200',          icon: '≠' },
  STALE_DATE:        { label: 'Stale Dated',             color: 'text-violet-700', bg: 'bg-violet-50 border-violet-200',        icon: '📅' },
  POST_DATE:         { label: 'Post Dated',              color: 'text-blue-700',   bg: 'bg-blue-50 border-blue-200',            icon: '📅' },
  WORDS_FIGURES:     { label: 'Words/Figures Diff',      color: 'text-rose-700',   bg: 'bg-rose-50 border-rose-200',            icon: 'Ξ' },
  DUPLICATE:         { label: 'Duplicate Instrument',    color: 'text-red-700',    bg: 'bg-red-50 border-red-200',              icon: '⊕' },
  UNPROCESSED:       { label: 'Unprocessed Item',        color: 'text-slate-600',  bg: 'bg-slate-100 border-slate-300',         icon: '⌛' },
  EXTENSION_FILE:    { label: 'Extension File Item',     color: 'text-cyan-700',   bg: 'bg-cyan-50 border-cyan-200',            icon: '↗' },
}

const STATUS_D = {
  OPEN:       { label: 'Open',       cls: 'text-amber-300   bg-amber-900/40   border-amber-700/40'   },
  ESCALATED:  { label: 'Escalated',  cls: 'text-red-300     bg-red-900/40     border-red-700/40'     },
  RESOLVED:   { label: 'Resolved',   cls: 'text-emerald-300 bg-emerald-900/40 border-emerald-700/40' },
  RETURNED:   { label: 'Returned',   cls: 'text-slate-300   bg-slate-800/60   border-slate-600/40'   },
}
const STATUS_L = {
  OPEN:       { label: 'Open',       cls: 'text-amber-700   bg-amber-50   border-amber-200'   },
  ESCALATED:  { label: 'Escalated',  cls: 'text-red-700     bg-red-50     border-red-200'     },
  RESOLVED:   { label: 'Resolved',   cls: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  RETURNED:   { label: 'Returned',   cls: 'text-slate-600   bg-slate-100  border-slate-300'   },
}

const BRANCHES = ['Andheri (W)', 'Bandra (E)', 'Churchgate', 'Dadar', 'Goregaon', 'Kurla', 'Malad', 'Vashi']
const SESSIONS = ['SES-0619-001 (10:00–12:00)', 'SES-0619-002 (12:00–14:00)']

function seed(n) {
  const types   = Object.keys(DISC_TYPES_D)
  const statuses= Object.keys(STATUS_D)
  const now     = Date.now()
  return Array.from({ length: n }, (_, i) => {
    const type   = types[(i * 7 + 3) % types.length]
    const status = i % 9 === 0 ? 'ESCALATED' : i % 5 === 0 ? 'RESOLVED' : i % 11 === 0 ? 'RETURNED' : 'OPEN'
    const branch = BRANCHES[i % BRANCHES.length]
    const session= SESSIONS[i % SESSIONS.length]
    const lot    = `LOT_SVCB${String(Math.floor(i / 3) + 1).padStart(7, '0')}_20260619`
    const amt1   = 10000 + (i * 13751) % 990000
    const amt2   = type === 'AMOUNT_MISMATCH' ? amt1 + (1 + (i * 37) % 999) : amt1
    const words_amt = type === 'WORDS_FIGURES' ? amt1 + (500 + (i * 23) % 5000) : amt1
    return {
      id:          `DISC-${String(i + 1).padStart(4, '0')}`,
      instrument:  `CHQ-${String(10000 + i).padStart(6, '0')}`,
      lot,
      branch,
      session,
      type,
      status,
      micr_amount: `₹${amt1.toLocaleString('en-IN')}`,
      actual_amount: `₹${amt2.toLocaleString('en-IN')}`,
      words_amount:  `₹${words_amt.toLocaleString('en-IN')}`,
      physical_count: type === 'LOT_COUNT_DIFF' ? 15 + (i % 3) : null,
      electronic_count: type === 'LOT_COUNT_DIFF' ? 15 : null,
      detail: type === 'AMOUNT_MISMATCH'  ? `MICR reads ₹${amt1.toLocaleString('en-IN')}, OCR reads ₹${amt2.toLocaleString('en-IN')}` :
              type === 'MICR_ERROR'       ? `MICR band unreadable at position ${3 + i % 5}` :
              type === 'LOT_COUNT_DIFF'   ? `Physical: ${15 + i % 3}, Electronic: 15` :
              type === 'STALE_DATE'       ? `Cheque dated ${4 + i % 180} months ago` :
              type === 'POST_DATE'        ? `Cheque dated ${1 + i % 30} days in future` :
              type === 'WORDS_FIGURES'    ? `Figures: ₹${amt1.toLocaleString('en-IN')}, Words differ by ₹${Math.abs(words_amt - amt1).toLocaleString('en-IN')}` :
              type === 'DUPLICATE'        ? `Instrument already presented on ${new Date(now - 86400000 * (1 + i % 5)).toLocaleDateString('en-IN')}` :
              type === 'UNPROCESSED'      ? `Received at ${new Date(now - 3600000 * (1 + i % 4)).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}, awaiting assignment` :
              `Filed for manual processing — extension item ref ${i + 1}`,
      raised_at: new Date(now - 3600000 * (0.5 + i * 0.3)).toISOString(),
      assigned_to: status === 'OPEN' ? null : ['Priya Sharma', 'Amit Verma', 'Sunita Rao'][i % 3],
    }
  })
}

const ALL_DISCS = seed(48)

const SUMMARY = {
  total:       ALL_DISCS.length,
  open:        ALL_DISCS.filter(d => d.status === 'OPEN').length,
  escalated:   ALL_DISCS.filter(d => d.status === 'ESCALATED').length,
  resolved:    ALL_DISCS.filter(d => d.status === 'RESOLVED').length,
  returned:    ALL_DISCS.filter(d => d.status === 'RETURNED').length,
}

const TYPE_COUNTS = Object.keys(DISC_TYPES_D).map(k => ({
  key: k,
  count: ALL_DISCS.filter(d => d.type === k).length,
})).sort((a, b) => b.count - a.count)

// ─── Component ────────────────────────────────────────────────────────────────

export default function CTSDiscrepancy() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [typeFilter,   setTypeFilter]   = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [branchFilter, setBranchFilter] = useState('ALL')
  const [selected,     setSelected]     = useState(null)
  const [search,       setSearch]       = useState('')

  const DISC_TYPES = isDark ? DISC_TYPES_D : DISC_TYPES_L
  const STATUS_META = isDark ? STATUS_D : STATUS_L

  const th = {
    page:    isDark ? 'bg-[#020817] text-white'          : 'bg-slate-50 text-slate-900',
    card:    isDark ? 'bg-white/4 border-white/8'         : 'bg-white border-slate-200',
    h1:      isDark ? 'text-white'                        : 'text-slate-900',
    sub:     isDark ? 'text-slate-400'                    : 'text-slate-500',
    label:   isDark ? 'text-slate-400'                    : 'text-slate-500',
    val:     isDark ? 'text-white'                        : 'text-slate-900',
    row:     isDark ? 'border-white/5 hover:bg-white/3'   : 'border-slate-100 hover:bg-slate-50',
    rowSel:  isDark ? 'bg-cyan-900/20 border-cyan-700/30' : 'bg-cyan-50 border-cyan-200',
    inp:     isDark ? 'bg-white/5 border-white/10 text-slate-200 placeholder-slate-600' : 'bg-white border-slate-300 text-slate-700 placeholder-slate-400',
    sel:     isDark ? 'bg-white/5 border-white/10 text-slate-200' : 'bg-white border-slate-300 text-slate-700',
    divider: isDark ? 'bg-white/8'                        : 'bg-slate-200',
    detail:  isDark ? 'bg-white/3 border-white/8'         : 'bg-slate-50 border-slate-200',
    badge:   isDark ? 'bg-white/8 text-slate-300'         : 'bg-slate-100 text-slate-600',
  }

  const filtered = useMemo(() => ALL_DISCS.filter(d => {
    if (typeFilter !== 'ALL'   && d.type   !== typeFilter)   return false
    if (statusFilter !== 'ALL' && d.status !== statusFilter) return false
    if (branchFilter !== 'ALL' && d.branch !== branchFilter) return false
    if (search && !d.instrument.toLowerCase().includes(search.toLowerCase()) &&
        !d.lot.toLowerCase().includes(search.toLowerCase()) &&
        !d.detail.toLowerCase().includes(search.toLowerCase())) return false
    return true
  }), [typeFilter, statusFilter, branchFilter, search])

  const sel = selected ? ALL_DISCS.find(d => d.id === selected) : null

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col min-h-0 ${th.page}`}>
        {/* ── Header ── */}
        <div className={`shrink-0 border-b px-6 py-4 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
          <div className="flex items-start justify-between">
            <div>
              <h1 className={`text-lg font-semibold ${th.h1}`}>Discrepancy Register</h1>
              <p className={`text-xs mt-0.5 ${th.sub}`}>Unprocessed items · Amount mismatches · Lot count differences · Extension file items</p>
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-xs px-2 py-1 rounded border ${isDark ? 'border-white/10 text-slate-400' : 'border-slate-200 text-slate-500'}`}>
                Session: 19-Jun-2026
              </span>
              <button className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${isDark ? 'bg-cyan-600/20 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/30' : 'bg-cyan-50 text-cyan-700 border-cyan-200 hover:bg-cyan-100'}`}>
                Export Register
              </button>
            </div>
          </div>

          {/* KPI Strip */}
          <div className="grid grid-cols-5 gap-3 mt-4">
            {[
              { label: 'Total Items',  val: SUMMARY.total,     color: th.val },
              { label: 'Open',         val: SUMMARY.open,      color: isDark ? 'text-amber-400' : 'text-amber-600' },
              { label: 'Escalated',    val: SUMMARY.escalated, color: isDark ? 'text-red-400' : 'text-red-600' },
              { label: 'Resolved',     val: SUMMARY.resolved,  color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
              { label: 'Returned',     val: SUMMARY.returned,  color: isDark ? 'text-slate-400' : 'text-slate-500' },
            ].map(k => (
              <div key={k.label} className={`rounded-lg border px-4 py-3 ${th.card}`}>
                <div className={`text-2xl font-bold font-mono ${k.color}`}>{k.val}</div>
                <div className={`text-[11px] mt-0.5 ${th.label}`}>{k.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Body ── */}
        <div className="flex-1 min-h-0 flex overflow-hidden">

          {/* Left: type breakdown sidebar */}
          <div className={`w-52 shrink-0 border-r p-3 overflow-y-auto ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
            <p className={`text-[10px] uppercase tracking-widest font-semibold mb-2 ${th.label}`}>By Type</p>
            <button
              onClick={() => setTypeFilter('ALL')}
              className={`w-full text-left px-2 py-1.5 rounded text-xs mb-1 flex justify-between items-center ${typeFilter === 'ALL' ? (isDark ? 'bg-cyan-600/20 text-cyan-300' : 'bg-cyan-50 text-cyan-700') : `${th.sub} ${isDark ? 'hover:bg-white/5' : 'hover:bg-slate-100'}`}`}
            >
              <span>All Types</span>
              <span className={`font-mono text-[10px] ${th.badge} px-1.5 py-0.5 rounded`}>{ALL_DISCS.length}</span>
            </button>
            {TYPE_COUNTS.map(({ key, count }) => {
              const meta = DISC_TYPES[key]
              return (
                <button
                  key={key}
                  onClick={() => setTypeFilter(key)}
                  className={`w-full text-left px-2 py-1.5 rounded text-xs mb-0.5 flex justify-between items-center transition-colors ${typeFilter === key ? (isDark ? 'bg-cyan-600/20 text-cyan-300' : 'bg-cyan-50 text-cyan-700') : `${th.sub} ${isDark ? 'hover:bg-white/5' : 'hover:bg-slate-100'}`}`}
                >
                  <span className="flex items-center gap-1.5">
                    <span className={`${meta.color} text-[10px]`}>{meta.icon}</span>
                    <span className="leading-tight">{meta.label}</span>
                  </span>
                  <span className={`font-mono text-[10px] ${th.badge} px-1.5 py-0.5 rounded shrink-0`}>{count}</span>
                </button>
              )
            })}
          </div>

          {/* Center: item list */}
          <div className="flex-1 min-w-0 flex flex-col min-h-0">
            {/* Filters */}
            <div className={`shrink-0 px-4 py-2 border-b flex items-center gap-2 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
              <input
                className={`text-xs px-3 py-1.5 rounded-lg border flex-1 min-w-0 ${th.inp}`}
                placeholder="Search instrument, lot, detail…"
                value={search} onChange={e => setSearch(e.target.value)}
              />
              <select className={`text-xs px-2 py-1.5 rounded-lg border ${th.sel}`} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                <option value="ALL">All Status</option>
                {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
              <select className={`text-xs px-2 py-1.5 rounded-lg border ${th.sel}`} value={branchFilter} onChange={e => setBranchFilter(e.target.value)}>
                <option value="ALL">All Branches</option>
                {BRANCHES.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
              <span className={`text-xs shrink-0 ${th.sub}`}>{filtered.length} items</span>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className={`sticky top-0 ${isDark ? 'bg-[#020817]' : 'bg-slate-50'}`}>
                  <tr className={`border-b ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
                    {['ID', 'Instrument', 'Type', 'Branch', 'Detail', 'Raised', 'Status'].map(h => (
                      <th key={h} className={`text-left px-3 py-2 font-medium ${th.label}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(d => {
                    const meta   = DISC_TYPES[d.type]
                    const smeta  = STATUS_META[d.status]
                    const isSel  = selected === d.id
                    return (
                      <tr
                        key={d.id}
                        onClick={() => setSelected(isSel ? null : d.id)}
                        className={`border-b cursor-pointer transition-colors ${isSel ? th.rowSel : th.row}`}
                      >
                        <td className={`px-3 py-2 font-mono ${th.sub}`}>{d.id}</td>
                        <td className={`px-3 py-2 font-mono ${th.val}`}>{d.instrument}</td>
                        <td className="px-3 py-2">
                          <span className={`px-2 py-0.5 rounded border text-[10px] font-medium ${meta.color} ${meta.bg}`}>{meta.label}</span>
                        </td>
                        <td className={`px-3 py-2 ${th.sub}`}>{d.branch}</td>
                        <td className={`px-3 py-2 max-w-[240px] truncate ${th.sub}`}>{d.detail}</td>
                        <td className={`px-3 py-2 font-mono whitespace-nowrap ${th.sub}`}>
                          {new Date(d.raised_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                        </td>
                        <td className="px-3 py-2">
                          <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold ${smeta.cls}`}>{smeta.label}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right: detail panel */}
          {sel && (
            <div className={`w-72 shrink-0 border-l overflow-y-auto ${isDark ? 'border-white/8 bg-white/2' : 'border-slate-200 bg-slate-50'}`}>
              <div className="p-4 space-y-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className={`font-mono text-sm font-semibold ${th.val}`}>{sel.id}</div>
                    <div className={`text-xs mt-0.5 ${th.sub}`}>{sel.instrument}</div>
                  </div>
                  <button onClick={() => setSelected(null)} className={`text-lg leading-none ${th.sub} ${isDark ? 'hover:text-white' : 'hover:text-slate-900'} transition-colors`}>×</button>
                </div>

                <div className={`rounded-lg border px-3 py-2 ${DISC_TYPES[sel.type].bg}`}>
                  <div className={`text-[11px] font-semibold ${DISC_TYPES[sel.type].color}`}>{DISC_TYPES[sel.type].label}</div>
                  <div className={`text-xs mt-1 ${th.sub}`}>{sel.detail}</div>
                </div>

                {[
                  { label: 'Branch',    val: sel.branch },
                  { label: 'Session',   val: sel.session },
                  { label: 'Lot',       val: sel.lot.split('_').slice(-1)[0] },
                  { label: 'MICR Amt',  val: sel.micr_amount },
                  ...(sel.type === 'AMOUNT_MISMATCH' ? [{ label: 'OCR Amt', val: sel.actual_amount }] : []),
                  ...(sel.type === 'WORDS_FIGURES'   ? [{ label: 'Words Amt', val: sel.words_amount }] : []),
                  ...(sel.type === 'LOT_COUNT_DIFF'  ? [
                    { label: 'Physical Count',    val: String(sel.physical_count) },
                    { label: 'Electronic Count',  val: String(sel.electronic_count) },
                  ] : []),
                  { label: 'Raised At', val: new Date(sel.raised_at).toLocaleString('en-IN') },
                  ...(sel.assigned_to ? [{ label: 'Assigned To', val: sel.assigned_to }] : []),
                ].map(({ label, val }) => (
                  <div key={label} className={`flex justify-between text-xs border-b pb-2 ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
                    <span className={th.label}>{label}</span>
                    <span className={`font-medium ${th.val}`}>{val}</span>
                  </div>
                ))}

                {/* Actions */}
                {sel.status === 'OPEN' && (
                  <div className="space-y-2 pt-1">
                    <button className={`w-full text-xs py-1.5 rounded-lg border transition-colors ${isDark ? 'bg-amber-600/20 text-amber-300 border-amber-500/30 hover:bg-amber-600/30' : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'}`}>
                      Escalate to Manager
                    </button>
                    <button className={`w-full text-xs py-1.5 rounded-lg border transition-colors ${isDark ? 'bg-red-600/20 text-red-300 border-red-500/30 hover:bg-red-600/30' : 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100'}`}>
                      Mark as Return
                    </button>
                    <button className={`w-full text-xs py-1.5 rounded-lg border transition-colors ${isDark ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/30' : 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'}`}>
                      Mark Resolved
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
