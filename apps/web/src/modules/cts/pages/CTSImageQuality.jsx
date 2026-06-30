import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { useTheme } from '../../../shared/theme/ThemeContext'

// ─── Mock Data ──────────────────────────────────────────────────────────────

const SCANNERS = [
  { id: 'SCN-01', model: 'Panini Vision X',   location: 'Branch A — Counter 1', status: 'ONLINE'  },
  { id: 'SCN-02', model: 'Digital Check CX30', location: 'Branch A — Counter 2', status: 'ONLINE'  },
  { id: 'SCN-03', model: 'Burroughs Verifye',  location: 'Branch B — Counter 1', status: 'OFFLINE' },
  { id: 'SCN-04', model: 'Panini Vision X',   location: 'Branch B — Counter 2', status: 'ONLINE'  },
]

const IQA_FAIL_REASONS = {
  DARK:      'Image too dark — rescan required',
  MICR:      'MICR band not readable',
  SKEW:      'Image skew > 2°',
  TORN:      'Torn corner — rescan',
  DUPLICATE: 'Duplicate instrument detected',
  BLUR:      'Focus blur — rescan required',
  FOLD:      'Fold crease over amount field',
}

function makeInstruments(n) {
  const entries = Object.entries(IQA_FAIL_REASONS)
  const payees  = ['Reliance Ind.', 'HDFC Sec.', 'Tata Cons.', 'Infosys', 'SBI MF', 'Kotak AMC']
  const amts    = ['₹12,500', '₹45,000', '₹2,00,000', '₹8,75,000', '₹15,000', '₹3,50,000']
  return Array.from({ length: n }, (_, i) => {
    const scnId  = `SCN-0${(i % 4) + 1}`
    const lot    = Math.floor(i / 15) + 1
    const fail   = Math.random() < 0.09   // ~9% fail rate
    const rescan = fail && Math.random() < 0.55
    const [reasonKey] = entries[i % entries.length]
    return {
      id:          `CHQ-OUT-${String(i + 1).padStart(5, '0')}`,
      account:     `****${1000 + ((i * 37) % 9000)}`,
      payee:       payees[i % payees.length],
      amount:      amts[i % amts.length],
      scanner:     scnId,
      lot:         `LOT-${String(lot).padStart(2, '0')}`,
      lot_seq:     lot,
      status:      fail ? (rescan ? 'RESCAN_PASS' : 'IQA_FAIL') : 'IQA_PASS',
      fail_reason: fail ? reasonKey : null,
      fail_label:  fail ? IQA_FAIL_REASONS[reasonKey] : null,
      scanned_at:  new Date(Date.now() - (n - i) * 4100).toISOString(),
      ocr_conf:    fail ? null : (0.78 + Math.random() * 0.21).toFixed(2),
      dpi:         fail ? (100 + Math.floor(Math.random() * 100)) : 200 + Math.floor(Math.random() * 100),
      contrast:    fail ? (0.2 + Math.random() * 0.3).toFixed(2) : (0.6 + Math.random() * 0.35).toFixed(2),
    }
  })
}

const INSTRUMENTS = makeInstruments(62)

// ─── Derived stats ──────────────────────────────────────────────────────────

function buildStats(instruments) {
  const total   = instruments.length
  const fails   = instruments.filter(x => x.status === 'IQA_FAIL')
  const passes  = instruments.filter(x => x.status === 'IQA_PASS')
  const rescans = instruments.filter(x => x.status === 'RESCAN_PASS')

  const byReason = {}
  for (const r of Object.keys(IQA_FAIL_REASONS)) byReason[r] = 0
  for (const f of fails) if (f.fail_reason) byReason[f.fail_reason]++

  const byScanner = {}
  for (const scn of SCANNERS) {
    const scnItems = instruments.filter(x => x.scanner === scn.id)
    const scnFails = scnItems.filter(x => x.status === 'IQA_FAIL')
    byScanner[scn.id] = {
      total: scnItems.length,
      fails: scnFails.length,
      rate:  scnItems.length ? (scnFails.length / scnItems.length * 100).toFixed(1) : '0.0',
    }
  }

  const lots = [...new Set(instruments.map(x => x.lot))].sort()
  const byLot = lots.map(lot => {
    const items = instruments.filter(x => x.lot === lot)
    const lotFails = items.filter(x => x.status === 'IQA_FAIL')
    return { lot, total: items.length, fails: lotFails.length, pass_rate: ((1 - lotFails.length / items.length) * 100).toFixed(1) }
  })

  return { total, fails: fails.length, passes: passes.length, rescans: rescans.length, byReason, byScanner, byLot }
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function CTSImageQuality() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const [instruments, setInstruments] = useState(INSTRUMENTS)
  const [selected, setSelected]       = useState(null)
  const [filter, setFilter]           = useState('ALL')  // ALL | IQA_FAIL | IQA_PASS | RESCAN_PASS
  const [scannerFilter, setScannerFilter] = useState('ALL')
  const [rescanQueue, setRescanQueue] = useState([])

  usePageHeader({ subtitle: 'IQA Gate · Scanner Fleet · Lot Pass Rates' })

  const stats = buildStats(instruments)

  const filtered = instruments.filter(x =>
    (filter === 'ALL' || x.status === filter) &&
    (scannerFilter === 'ALL' || x.scanner === scannerFilter)
  )

  const triggerRescan = (id) => {
    setRescanQueue(prev => [...prev, id])
    setTimeout(() => {
      setInstruments(prev => prev.map(x =>
        x.id === id ? { ...x, status: 'RESCAN_PASS', fail_reason: null, fail_label: null } : x
      ))
      setRescanQueue(prev => prev.filter(v => v !== id))
      if (selected?.id === id) setSelected(prev => ({ ...prev, status: 'RESCAN_PASS' }))
    }, 1800)
  }

  const th = {
    page:    isDark ? 'text-white'                         : 'bg-slate-50 text-slate-900',
    card:    isDark ? 'bg-white/5 border-white/10'         : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                     : 'text-slate-500',
    faint:   isDark ? 'text-slate-500'                     : 'text-slate-400',
    divider: isDark ? 'border-white/10'                    : 'border-slate-200',
    divSm:   isDark ? 'border-white/5'                     : 'border-slate-100',
    row:     isDark ? 'border-white/5 hover:bg-white/5'    : 'border-slate-100 hover:bg-slate-50',
    rowSel:  isDark ? 'bg-gold-400/8 border-gold-400/25'   : 'bg-amber-50 border-amber-200',
    badge:   isDark ? 'bg-white/5 border-white/10'         : 'bg-slate-100 border-slate-200',
    input:   isDark ? 'bg-white/5 border-white/10 text-slate-300 focus:border-gold-400/40' : 'bg-white border-slate-200 text-slate-700 focus:border-amber-400',
    thCell:  isDark ? 'text-slate-500'                     : 'text-slate-400',
    thead:   isDark ? 'bg-white/5 border-white/10'         : 'bg-slate-50 border-slate-200',
  }

  const passRate = stats.total ? ((stats.passes + stats.rescans) / stats.total * 100).toFixed(1) : '—'

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5 min-h-full`}>

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {[
            { label: 'Total Scanned',  value: stats.total,                          color: th.heading },
            { label: 'IQA Pass',       value: stats.passes,                         color: 'text-emerald-500' },
            { label: 'IQA Fail',       value: stats.fails,                          color: stats.fails > 0 ? 'text-red-400' : 'text-emerald-500' },
            { label: 'Rescan Pass',    value: stats.rescans,                        color: 'text-sky-400' },
            { label: 'Net Pass Rate',  value: `${passRate}%`,                       color: parseFloat(passRate) >= 95 ? 'text-emerald-500' : 'text-amber-400' },
          ].map(kpi => (
            <div key={kpi.label} className={`border rounded-xl p-4 ${th.card}`}>
              <div className={`text-[10px] ${th.muted} mb-1`}>{kpi.label}</div>
              <div className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</div>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-[1fr_320px] gap-4">

          {/* Left: lot table + instrument list */}
          <div className="space-y-4">

            {/* Lot pass-rate table */}
            <div className={`border rounded-xl ${th.card}`}>
              <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
                <span className={`text-sm font-medium ${th.heading}`}>Lot Pass Rates</span>
                <span className={`text-[10px] ${th.faint}`}>{stats.byLot.length} lots · LOT size 15</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className={`${th.thCell} border-b ${th.divSm}`}>
                      <th className="text-left px-4 py-2 font-normal">Lot</th>
                      <th className="text-right px-4 py-2 font-normal">Instruments</th>
                      <th className="text-right px-4 py-2 font-normal">IQA Fail</th>
                      <th className="text-right px-4 py-2 font-normal">Pass Rate</th>
                      <th className="px-4 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.byLot.map(lot => (
                      <tr key={lot.lot} className={`border-b ${th.row} transition-colors`}>
                        <td className={`px-4 py-2.5 font-mono ${th.body}`}>{lot.lot}</td>
                        <td className={`px-4 py-2.5 text-right ${th.muted}`}>{lot.total}</td>
                        <td className={`px-4 py-2.5 text-right font-semibold ${lot.fails > 0 ? 'text-red-400' : th.faint}`}>{lot.fails}</td>
                        <td className="px-4 py-2.5 text-right">
                          <span className={`font-semibold ${parseFloat(lot.pass_rate) >= 95 ? 'text-emerald-500' : parseFloat(lot.pass_rate) >= 85 ? 'text-amber-400' : 'text-red-400'}`}>
                            {lot.pass_rate}%
                          </span>
                        </td>
                        <td className="px-4 py-2.5">
                          {lot.fails > 0 && (
                            <button
                              className="text-[10px] px-2 py-0.5 rounded border text-amber-500 border-amber-500/30 hover:bg-amber-500/10 transition-colors"
                              onClick={() => setFilter('IQA_FAIL')}
                            >
                              View fails
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Instrument list */}
            <div className={`border rounded-xl ${th.card}`}>
              <div className={`px-4 py-3 border-b ${th.divider} flex items-center gap-3 flex-wrap`}>
                <span className={`text-sm font-medium ${th.heading} mr-auto`}>Instruments</span>

                {/* Status filter */}
                <div className="flex items-center gap-1">
                  {[['ALL','All'],['IQA_FAIL','Fails Only'],['IQA_PASS','Passed'],['RESCAN_PASS','Rescanned']].map(([v,l]) => (
                    <button
                      key={v}
                      onClick={() => setFilter(v)}
                      className={`text-[10px] px-2.5 py-1 rounded-full border transition-colors ${
                        filter === v
                          ? 'bg-gold-400/20 border-gold-400/40 text-amber-400'
                          : `${th.badge} ${th.muted} hover:border-white/20`
                      }`}
                    >
                      {l}
                    </button>
                  ))}
                </div>

                {/* Scanner filter */}
                <select
                  className={`text-[10px] px-2 py-1 rounded-lg border ${th.input} outline-none`}
                  value={scannerFilter}
                  onChange={e => setScannerFilter(e.target.value)}
                >
                  <option value="ALL">All Scanners</option>
                  {SCANNERS.map(s => <option key={s.id} value={s.id}>{s.id}</option>)}
                </select>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className={`${th.thCell} ${th.thead} border-b ${th.divSm}`}>
                      <th className="text-left px-4 py-2 font-normal">Instrument</th>
                      <th className="text-left px-4 py-2 font-normal">Payee</th>
                      <th className="text-left px-4 py-2 font-normal">Amount</th>
                      <th className="text-left px-4 py-2 font-normal">Scanner</th>
                      <th className="text-left px-4 py-2 font-normal">Lot</th>
                      <th className="text-left px-4 py-2 font-normal">Status</th>
                      <th className="text-left px-4 py-2 font-normal">Fail Reason</th>
                      <th className="px-4 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.slice(0, 30).map(item => (
                      <tr
                        key={item.id}
                        onClick={() => setSelected(item)}
                        className={`border-b transition-colors cursor-pointer ${selected?.id === item.id ? th.rowSel : th.row}`}
                      >
                        <td className={`px-4 py-2.5 font-mono ${th.muted}`}>{item.id}</td>
                        <td className={`px-4 py-2.5 ${th.body}`}>{item.payee}</td>
                        <td className={`px-4 py-2.5 ${th.muted}`}>{item.amount}</td>
                        <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{item.scanner}</td>
                        <td className={`px-4 py-2.5 ${th.faint} font-mono`}>{item.lot}</td>
                        <td className="px-4 py-2.5">
                          <StatusBadge status={item.status} />
                        </td>
                        <td className={`px-4 py-2.5 ${item.fail_label ? 'text-red-400' : th.faint} max-w-[180px] truncate`}>
                          {item.fail_label ?? '—'}
                        </td>
                        <td className="px-4 py-2.5">
                          {item.status === 'IQA_FAIL' && (
                            <button
                              disabled={rescanQueue.includes(item.id)}
                              onClick={e => { e.stopPropagation(); triggerRescan(item.id) }}
                              className="text-[10px] px-2 py-0.5 rounded border transition-colors text-sky-400 border-sky-400/30 hover:bg-sky-400/10 disabled:opacity-40"
                            >
                              {rescanQueue.includes(item.id) ? '⟳ Scanning…' : 'Rescan'}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {filtered.length > 30 && (
                  <div className={`px-4 py-2 text-[10px] ${th.faint} border-t ${th.divSm}`}>
                    Showing 30 of {filtered.length} — apply filter to narrow
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right: detail panel + scanner health */}
          <div className="space-y-4">

            {/* Instrument detail */}
            {selected ? (
              <div className={`border rounded-xl ${th.card}`}>
                <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
                  <span className={`text-sm font-medium ${th.heading}`}>{selected.id}</span>
                  <button onClick={() => setSelected(null)} className={`text-[10px] ${th.faint} hover:${th.muted}`}>✕</button>
                </div>
                <div className="px-4 py-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className={`text-xs ${th.muted}`}>Status</span>
                    <StatusBadge status={selected.status} />
                  </div>
                  {selected.fail_label && (
                    <div className={`rounded-lg px-3 py-2.5 border text-xs ${isDark ? 'bg-red-400/10 border-red-400/20 text-red-300' : 'bg-red-50 border-red-200 text-red-700'}`}>
                      ⚠ {selected.fail_label}
                    </div>
                  )}
                  {[
                    ['Payee',    selected.payee],
                    ['Amount',   selected.amount],
                    ['Account',  selected.account],
                    ['Scanner',  selected.scanner],
                    ['Lot',      selected.lot],
                    ['DPI',      `${selected.dpi} dpi`],
                    ['Contrast', selected.contrast],
                  ].map(([k, v]) => (
                    <div key={k} className={`flex justify-between text-xs border-b ${th.divSm} pb-2`}>
                      <span className={th.muted}>{k}</span>
                      <span className={`font-mono ${th.body}`}>{v}</span>
                    </div>
                  ))}
                  {selected.ocr_conf && (
                    <div className={`flex justify-between text-xs`}>
                      <span className={th.muted}>OCR Confidence</span>
                      <span className={`font-mono font-semibold ${parseFloat(selected.ocr_conf) >= 0.90 ? 'text-emerald-500' : 'text-amber-400'}`}>
                        {(parseFloat(selected.ocr_conf) * 100).toFixed(0)}%
                      </span>
                    </div>
                  )}
                  {selected.status === 'IQA_FAIL' && (
                    <button
                      disabled={rescanQueue.includes(selected.id)}
                      onClick={() => triggerRescan(selected.id)}
                      className="w-full mt-2 py-2 rounded-lg text-xs font-medium border transition-colors text-sky-400 border-sky-400/30 hover:bg-sky-400/10 disabled:opacity-40"
                    >
                      {rescanQueue.includes(selected.id) ? '⟳ Rescanning…' : 'Trigger Rescan'}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className={`border rounded-xl ${th.card} px-4 py-8 text-center`}>
                <div className="text-2xl mb-2">🔍</div>
                <div className={`text-xs ${th.faint}`}>Select an instrument to inspect</div>
              </div>
            )}

            {/* Failure reason breakdown */}
            <div className={`border rounded-xl ${th.card}`}>
              <div className={`px-4 py-3 border-b ${th.divider}`}>
                <span className={`text-sm font-medium ${th.heading}`}>Failure Breakdown</span>
              </div>
              <div className="px-4 py-3 space-y-2">
                {Object.entries(stats.byReason).filter(([,v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([key, count]) => (
                  <div key={key} className="flex items-center gap-2">
                    <div className="flex-1">
                      <div className={`text-[11px] ${th.body} mb-1`}>{IQA_FAIL_REASONS[key]}</div>
                      <div className={`h-1.5 rounded-full ${isDark ? 'bg-white/10' : 'bg-slate-100'} overflow-hidden`}>
                        <div
                          className="h-full bg-red-400 rounded-full"
                          style={{ width: `${stats.fails ? (count / stats.fails) * 100 : 0}%` }}
                        />
                      </div>
                    </div>
                    <span className="text-xs font-mono text-red-400 w-5 text-right shrink-0">{count}</span>
                  </div>
                ))}
                {Object.values(stats.byReason).every(v => v === 0) && (
                  <div className={`text-center text-xs ${th.faint} py-4`}>No failures in current batch</div>
                )}
              </div>
            </div>

            {/* Scanner fleet health */}
            <div className={`border rounded-xl ${th.card}`}>
              <div className={`px-4 py-3 border-b ${th.divider}`}>
                <span className={`text-sm font-medium ${th.heading}`}>Scanner Fleet</span>
              </div>
              <div className={`divide-y ${th.divSm}`}>
                {SCANNERS.map(scn => {
                  const s = stats.byScanner[scn.id]
                  const failRate = parseFloat(s.rate)
                  return (
                    <div key={scn.id} className="px-4 py-3">
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className={`w-1.5 h-1.5 rounded-full ${scn.status === 'ONLINE' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                          <span className={`text-xs font-mono font-semibold ${th.heading}`}>{scn.id}</span>
                        </div>
                        <span className={`text-[10px] font-semibold ${failRate > 10 ? 'text-red-400' : failRate > 5 ? 'text-amber-400' : 'text-emerald-500'}`}>
                          {s.rate}% fail
                        </span>
                      </div>
                      <div className={`text-[10px] ${th.faint} mb-2`}>{scn.model} · {scn.location}</div>
                      <div className={`h-1 rounded-full ${isDark ? 'bg-white/10' : 'bg-slate-100'} overflow-hidden`}>
                        <div
                          className={`h-full rounded-full ${failRate > 10 ? 'bg-red-400' : failRate > 5 ? 'bg-amber-400' : 'bg-emerald-400'}`}
                          style={{ width: `${s.total ? (s.fails / s.total) * 100 : 0}%` }}
                        />
                      </div>
                      <div className={`flex justify-between text-[10px] ${th.faint} mt-1`}>
                        <span>{s.total} scanned</span>
                        <span>{s.fails} fail{s.fails !== 1 ? 's' : ''}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}

function StatusBadge({ status }) {
  const cfg = {
    IQA_PASS:    { label: 'IQA Pass',    cls: 'text-sky-400 bg-sky-400/10 border-sky-400/20'         },
    IQA_FAIL:    { label: 'IQA Fail',    cls: 'text-red-400 bg-red-400/10 border-red-400/20'         },
    RESCAN_PASS: { label: 'Rescan ✓',   cls: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' },
  }
  const { label, cls } = cfg[status] ?? { label: status, cls: 'text-slate-400 bg-white/5 border-white/10' }
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${cls}`}>{label}</span>
  )
}
