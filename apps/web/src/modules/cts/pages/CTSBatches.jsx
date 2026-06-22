import { useState, useMemo } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Constants ────────────────────────────────────────────────────────────────

const LOT_STATUSES = {
  RECEIVED:     { label: 'Received',       color: 'text-slate-400',   bg: 'bg-slate-800/60 border-slate-600/40',     dot: 'bg-slate-400'   },
  IQA_COMPLETE: { label: 'IQA Complete',   color: 'text-blue-400',    bg: 'bg-blue-900/30 border-blue-700/40',       dot: 'bg-blue-400'    },
  EXTRACTED:    { label: 'AI Extracted',   color: 'text-violet-400',  bg: 'bg-violet-900/30 border-violet-700/40',   dot: 'bg-violet-400'  },
  PKI_SIGNED:   { label: 'PKI Signed',     color: 'text-cyan-400',    bg: 'bg-cyan-900/30 border-cyan-700/40',       dot: 'bg-cyan-400'    },
  SUBMITTED:    { label: 'Submitted',      color: 'text-amber-400',   bg: 'bg-amber-900/30 border-amber-700/40',     dot: 'bg-amber-400'   },
  NGCH_ACK:     { label: 'NGCH Ack',       color: 'text-emerald-400', bg: 'bg-emerald-900/30 border-emerald-700/40', dot: 'bg-emerald-400' },
  SETTLED:      { label: 'Settled',        color: 'text-emerald-300', bg: 'bg-emerald-900/40 border-emerald-600/40', dot: 'bg-emerald-300' },
  PARTIAL_FAIL: { label: 'Partial Fail',   color: 'text-red-400',     bg: 'bg-red-900/30 border-red-700/40',         dot: 'bg-red-400'     },
}

const STATUS_ORDER = ['RECEIVED', 'IQA_COMPLETE', 'EXTRACTED', 'PKI_SIGNED', 'SUBMITTED', 'NGCH_ACK', 'SETTLED']

const BRANCHES = ['Andheri (W)', 'Bandra (E)', 'Churchgate', 'Dadar', 'Goregaon', 'Kurla', 'Malad', 'Vashi', 'Borivali', 'Thane']
const SESSIONS = [
  { id: 'SES-0619-001', label: '10:00–12:00', status: 'CLOSED'  },
  { id: 'SES-0619-002', label: '12:00–14:00', status: 'ACTIVE'  },
  { id: 'SES-0619-003', label: '14:00–16:00', status: 'UPCOMING'},
]

// ─── Mock generators ──────────────────────────────────────────────────────────

function makeInstruments(lotId, count, baseStatus) {
  const instStatuses  = baseStatus === 'RECEIVED' ? ['CAPTURED'] :
                        baseStatus === 'IQA_COMPLETE' ? ['IQA_PASS', 'IQA_FAIL'] :
                        baseStatus === 'EXTRACTED' ? ['AI_EXTRACTED', 'IQA_FAIL'] :
                        baseStatus === 'PKI_SIGNED' ? ['PKI_SIGNED'] :
                        ['NGCH_ACK', 'NGCH_REJECT', 'PKI_SIGNED']
  const payees = ['Reliance Ind.','HDFC Securities','Tata Cons.','Infosys Ltd.','SBI MF','ICICI Pru.','Bajaj Fin.']
  return Array.from({ length: count }, (_, i) => {
    const st = instStatuses[(i * 3) % instStatuses.length]
    const amt = 10000 + ((i + lotId.length) * 13751) % 990000
    return {
      id: `${lotId}-${String(i + 1).padStart(3, '0')}`,
      micr: `0${i % 9}200000${String(i).padStart(4, '0')}`,
      payee: payees[i % payees.length],
      amount: `₹${amt.toLocaleString('en-IN')}`,
      amtRaw: amt,
      account: `****${1000 + ((i * 37 + lotId.length) % 9000)}`,
      status: st,
      ocr_conf: st === 'IQA_FAIL' ? null : (0.88 + Math.random() * 0.11).toFixed(2),
      sig_score: st === 'IQA_FAIL' ? null : (0.82 + Math.random() * 0.17).toFixed(2),
      fraud_score: ['AI_EXTRACTED','PKI_SIGNED','NGCH_ACK','NGCH_REJECT'].includes(st) ? (Math.random() * 0.45).toFixed(2) : null,
      decision: st === 'NGCH_ACK' ? 'CONFIRM' : st === 'NGCH_REJECT' ? 'RETURN' : null,
    }
  })
}

function makeLots(n) {
  const now = Date.now()
  const statusSeq = ['SETTLED','SETTLED','NGCH_ACK','NGCH_ACK','SUBMITTED','PKI_SIGNED','EXTRACTED','IQA_COMPLETE','RECEIVED','PARTIAL_FAIL']
  return Array.from({ length: n }, (_, i) => {
    const branch  = BRANCHES[i % BRANCHES.length]
    const session = SESSIONS[i % 2]
    const count   = 12 + (i * 7) % 9        // 12–20 instruments per lot
    const status  = statusSeq[i % statusSeq.length]
    const physicalCount = status === 'PARTIAL_FAIL' ? count + 1 : count
    const totalAmt = (count * (50000 + (i * 23751) % 450000))
    const lotNum  = String(i + 1).padStart(7, '0')
    const lotId   = `LOT_SVCB${lotNum}_20260619_${session.id}`
    const instruments = makeInstruments(lotId, count, status)
    const confirmed   = instruments.filter(x => x.decision === 'CONFIRM').length
    const returned    = instruments.filter(x => x.decision === 'RETURN').length
    return {
      id: lotId,
      lot_number: lotNum,
      branch,
      session: session.id,
      session_label: session.label,
      instrument_count: count,
      physical_count: physicalCount,
      count_match: physicalCount === count,
      status,
      total_amount: `₹${totalAmt.toLocaleString('en-IN')}`,
      totalAmtRaw: totalAmt,
      iqa_fail: instruments.filter(x => x.status === 'IQA_FAIL').length,
      confirmed,
      returned,
      created_at: new Date(now - (n - i) * 4 * 60000).toISOString(),
      scanner_id: `SCN-0${(i % 4) + 1}`,
      instruments,
    }
  })
}

const ALL_LOTS = makeLots(30)

const SUMMARY = {
  lots:      ALL_LOTS.length,
  instruments: ALL_LOTS.reduce((s, l) => s + l.instrument_count, 0),
  totalAmt:  '₹' + ALL_LOTS.reduce((s, l) => s + l.totalAmtRaw, 0).toLocaleString('en-IN'),
  settled:   ALL_LOTS.filter(l => l.status === 'SETTLED').length,
  pending:   ALL_LOTS.filter(l => !['SETTLED','PARTIAL_FAIL'].includes(l.status)).length,
  failures:  ALL_LOTS.filter(l => l.status === 'PARTIAL_FAIL').length,
  countMismatch: ALL_LOTS.filter(l => !l.count_match).length,
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const m = LOT_STATUSES[status]
  return (
    <span className={`px-2 py-0.5 rounded border text-[10px] font-semibold ${m.color} ${m.bg}`}>
      {m.label}
    </span>
  )
}

function ProgressBar({ lot }) {
  const idx = STATUS_ORDER.indexOf(lot.status)
  const pct = lot.status === 'PARTIAL_FAIL' ? 85 : idx === -1 ? 0 : Math.round((idx / (STATUS_ORDER.length - 1)) * 100)
  const color = lot.status === 'PARTIAL_FAIL' ? 'bg-red-500' :
                lot.status === 'SETTLED'       ? 'bg-emerald-500' : 'bg-cyan-500'
  return (
    <div className="w-full bg-white/8 rounded-full h-1 overflow-hidden">
      <div className={`${color} h-full rounded-full transition-all`} style={{ width: `${pct}%` }} />
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function CTSBatches() {
  const { isDark } = useTheme()
  const [sessionFilter, setSessionFilter] = useState('ALL')
  const [statusFilter,  setStatusFilter]  = useState('ALL')
  const [branchFilter,  setBranchFilter]  = useState('ALL')
  const [selectedLot,   setSelectedLot]   = useState(null)
  const [selInst,       setSelInst]       = useState(null)

  const th = {
    page:  isDark ? 'bg-[#020817] text-white'         : 'bg-slate-50 text-slate-900',
    card:  isDark ? 'bg-white/4 border-white/8'        : 'bg-white border-slate-200',
    h1:    isDark ? 'text-white'                       : 'text-slate-900',
    sub:   isDark ? 'text-slate-400'                   : 'text-slate-500',
    label: isDark ? 'text-slate-400'                   : 'text-slate-500',
    val:   isDark ? 'text-white'                       : 'text-slate-900',
    row:   isDark ? 'border-white/5 hover:bg-white/3'  : 'border-slate-100 hover:bg-slate-50',
    rowSel:isDark ? 'bg-cyan-900/20 border-cyan-700/30': 'bg-cyan-50 border-cyan-200',
    sel:   isDark ? 'bg-white/5 border-white/10 text-slate-200' : 'bg-white border-slate-300 text-slate-700',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    mono:  isDark ? 'text-slate-300' : 'text-slate-700',
    panel: isDark ? 'bg-white/2 border-white/8' : 'bg-slate-50 border-slate-200',
  }

  const filtered = useMemo(() => ALL_LOTS.filter(l => {
    if (sessionFilter !== 'ALL' && l.session !== sessionFilter) return false
    if (statusFilter  !== 'ALL' && l.status  !== statusFilter)  return false
    if (branchFilter  !== 'ALL' && l.branch  !== branchFilter)  return false
    return true
  }), [sessionFilter, statusFilter, branchFilter])

  const lot = selectedLot ? ALL_LOTS.find(l => l.id === selectedLot) : null

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col min-h-0 ${th.page}`}>

        {/* ── Header ── */}
        <div className={`shrink-0 border-b px-6 py-4 ${th.divider}`}>
          <div className="flex items-start justify-between">
            <div>
              <h1 className={`text-lg font-semibold ${th.h1}`}>Batch / Lot Processing</h1>
              <p className={`text-xs mt-0.5 ${th.sub}`}>Branch lots · Physical vs electronic count · IQA · NGCH submission status</p>
            </div>
            <div className="flex items-center gap-2">
              {SESSIONS.map(s => (
                <span key={s.id} className={`text-[10px] px-2 py-1 rounded border font-mono ${
                  s.status === 'ACTIVE'  ? 'text-emerald-300 bg-emerald-900/30 border-emerald-700/40 animate-pulse' :
                  s.status === 'CLOSED' ? 'text-slate-500 border-white/10' :
                  'text-slate-600 border-white/5'}`}>
                  {s.id.split('-')[2]} · {s.label} · {s.status}
                </span>
              ))}
            </div>
          </div>

          {/* KPIs */}
          <div className="grid grid-cols-6 gap-3 mt-4">
            {[
              { label: 'Total Lots',      val: SUMMARY.lots,           color: 'text-white' },
              { label: 'Instruments',     val: SUMMARY.instruments,    color: 'text-white' },
              { label: 'Total Value',     val: SUMMARY.totalAmt,       color: 'text-cyan-300' },
              { label: 'Settled',         val: SUMMARY.settled,        color: 'text-emerald-400' },
              { label: 'In Progress',     val: SUMMARY.pending,        color: 'text-amber-400' },
              { label: 'Count Mismatch',  val: SUMMARY.countMismatch,  color: SUMMARY.countMismatch > 0 ? 'text-red-400 animate-pulse' : 'text-slate-500' },
            ].map(k => (
              <div key={k.label} className={`rounded-lg border px-4 py-3 ${th.card}`}>
                <div className={`text-xl font-bold font-mono ${k.color}`}>{k.val}</div>
                <div className={`text-[11px] mt-0.5 ${th.label}`}>{k.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Filters ── */}
        <div className={`shrink-0 px-6 py-2 border-b flex items-center gap-2 ${th.divider}`}>
          <select className={`text-xs px-2 py-1.5 rounded-lg border ${th.sel}`} value={sessionFilter} onChange={e => setSessionFilter(e.target.value)}>
            <option value="ALL">All Sessions</option>
            {SESSIONS.map(s => <option key={s.id} value={s.id}>{s.id} ({s.label})</option>)}
          </select>
          <select className={`text-xs px-2 py-1.5 rounded-lg border ${th.sel}`} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="ALL">All Status</option>
            {Object.entries(LOT_STATUSES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <select className={`text-xs px-2 py-1.5 rounded-lg border ${th.sel}`} value={branchFilter} onChange={e => setBranchFilter(e.target.value)}>
            <option value="ALL">All Branches</option>
            {BRANCHES.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
          <span className={`text-xs ml-auto ${th.sub}`}>{filtered.length} lots · {filtered.reduce((s, l) => s + l.instrument_count, 0)} instruments</span>
        </div>

        {/* ── Body ── */}
        <div className="flex-1 min-h-0 flex overflow-hidden">

          {/* Lot list */}
          <div className={`${lot ? 'w-[520px] shrink-0' : 'flex-1'} overflow-y-auto`}>
            <table className="w-full text-xs">
              <thead className={`sticky top-0 ${isDark ? 'bg-[#020817]' : 'bg-slate-50'}`}>
                <tr className={`border-b ${th.divider}`}>
                  {['Lot #', 'Branch', 'Session', 'Count (P/E)', 'Total Value', 'IQA Fail', 'Progress', 'Status'].map(h => (
                    <th key={h} className={`text-left px-3 py-2 font-medium whitespace-nowrap ${th.label}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(l => {
                  const isSel = selectedLot === l.id
                  return (
                    <tr
                      key={l.id}
                      onClick={() => { setSelectedLot(isSel ? null : l.id); setSelInst(null) }}
                      className={`border-b cursor-pointer transition-colors ${isSel ? th.rowSel : th.row}`}
                    >
                      <td className={`px-3 py-2 font-mono font-semibold ${th.mono}`}>
                        <div>{l.lot_number}</div>
                        <div className={`text-[10px] ${th.sub}`}>{l.scanner_id}</div>
                      </td>
                      <td className={`px-3 py-2 ${th.sub}`}>{l.branch}</td>
                      <td className={`px-3 py-2 font-mono ${th.sub}`}>{l.session_label}</td>
                      <td className="px-3 py-2">
                        <span className={`font-mono font-semibold ${l.count_match ? th.val : 'text-red-400'}`}>
                          {l.physical_count}/{l.instrument_count}
                        </span>
                        {!l.count_match && <span className="ml-1 text-red-400 font-bold">!</span>}
                      </td>
                      <td className={`px-3 py-2 font-mono ${th.mono}`}>{l.total_amount}</td>
                      <td className="px-3 py-2">
                        {l.iqa_fail > 0
                          ? <span className="text-red-400 font-mono font-semibold">{l.iqa_fail}</span>
                          : <span className={th.sub}>—</span>}
                      </td>
                      <td className="px-3 py-2 w-28"><ProgressBar lot={l} /></td>
                      <td className="px-3 py-2"><StatusBadge status={l.status} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Lot detail panel */}
          {lot && (
            <div className={`flex-1 min-w-0 border-l flex flex-col min-h-0 ${th.divider}`}>
              {/* Lot header */}
              <div className={`shrink-0 px-5 py-3 border-b flex items-start justify-between ${th.divider}`}>
                <div>
                  <div className={`font-mono font-semibold ${th.val}`}>Lot {lot.lot_number}</div>
                  <div className={`text-xs ${th.sub}`}>{lot.branch} · {lot.session_label} · {lot.scanner_id}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={lot.status} />
                  <button onClick={() => { setSelectedLot(null); setSelInst(null) }} className={`text-xl leading-none ${th.sub} hover:text-white`}>×</button>
                </div>
              </div>

              {/* Lot KPIs */}
              <div className={`shrink-0 grid grid-cols-4 gap-2 px-4 py-3 border-b ${th.divider}`}>
                {[
                  { label: 'Instruments',    val: lot.instrument_count },
                  { label: 'Physical Count', val: lot.physical_count, warn: !lot.count_match },
                  { label: 'Total Value',    val: lot.total_amount },
                  { label: 'IQA Fail',       val: lot.iqa_fail, warn: lot.iqa_fail > 0 },
                ].map(k => (
                  <div key={k.label} className={`rounded-lg border px-3 py-2 ${th.card}`}>
                    <div className={`text-base font-bold font-mono ${k.warn ? 'text-red-400' : th.val}`}>{k.val}</div>
                    <div className={`text-[10px] ${th.label}`}>{k.label}</div>
                  </div>
                ))}
              </div>

              {/* Instrument table */}
              <div className="flex-1 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className={`sticky top-0 ${isDark ? 'bg-[#020817]' : 'bg-slate-50'}`}>
                    <tr className={`border-b ${th.divider}`}>
                      {['Instrument', 'Payee', 'Amount', 'OCR', 'Sig', 'Fraud', 'Decision', 'Status'].map(h => (
                        <th key={h} className={`text-left px-3 py-2 font-medium ${th.label}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {lot.instruments.map(inst => {
                      const isSel = selInst === inst.id
                      return (
                        <tr
                          key={inst.id}
                          onClick={() => setSelInst(isSel ? null : inst.id)}
                          className={`border-b cursor-pointer transition-colors ${isSel ? th.rowSel : th.row}`}
                        >
                          <td className={`px-3 py-1.5 font-mono text-[11px] ${th.mono}`}>{inst.id.split('-').slice(-1)[0]}</td>
                          <td className={`px-3 py-1.5 ${th.sub} max-w-[120px] truncate`}>{inst.payee}</td>
                          <td className={`px-3 py-1.5 font-mono ${th.mono}`}>{inst.amount}</td>
                          <td className="px-3 py-1.5">
                            {inst.ocr_conf
                              ? <span className={Number(inst.ocr_conf) >= 0.95 ? 'text-emerald-400' : 'text-amber-400'}>{inst.ocr_conf}</span>
                              : <span className="text-red-400">—</span>}
                          </td>
                          <td className="px-3 py-1.5">
                            {inst.sig_score
                              ? <span className={Number(inst.sig_score) >= 0.90 ? 'text-emerald-400' : 'text-amber-400'}>{inst.sig_score}</span>
                              : <span className="text-red-400">—</span>}
                          </td>
                          <td className="px-3 py-1.5">
                            {inst.fraud_score !== null
                              ? <span className={Number(inst.fraud_score) > 0.35 ? 'text-red-400' : 'text-emerald-400'}>{inst.fraud_score}</span>
                              : <span className={th.sub}>—</span>}
                          </td>
                          <td className="px-3 py-1.5">
                            {inst.decision === 'CONFIRM' && <span className="text-emerald-400 font-semibold">✓ CONFIRM</span>}
                            {inst.decision === 'RETURN'  && <span className="text-red-400 font-semibold">✕ RETURN</span>}
                            {!inst.decision && <span className={th.sub}>—</span>}
                          </td>
                          <td className="px-3 py-1.5">
                            <span className={`text-[10px] font-medium ${
                              inst.status === 'NGCH_ACK'    ? 'text-emerald-400' :
                              inst.status === 'NGCH_REJECT' ? 'text-red-400'     :
                              inst.status === 'IQA_FAIL'    ? 'text-red-400'     :
                              inst.status === 'PKI_SIGNED'  ? 'text-cyan-400'    :
                              inst.status === 'AI_EXTRACTED'? 'text-violet-400'  :
                              'text-slate-400'
                            }`}>{inst.status.replace('_', ' ')}</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
