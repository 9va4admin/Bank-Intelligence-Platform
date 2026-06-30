import { useState, useEffect, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ─── Constants ────────────────────────────────────────────────────────────────

const SESSION_ID = 'SES-0619-001'
const DATE_STR   = '20260619'

// DBC check failure reasons (maps to which AI check failed)
const FAIL_REASONS = [
  { code: 'UV_FAIL',       label: 'UV watermark not detected',           category: 'Fraud' },
  { code: 'DATE_STALE',    label: 'Cheque date > 3 months old',          category: 'Date'  },
  { code: 'DATE_FUTURE',   label: 'Post-dated beyond permissible limit',  category: 'Date'  },
  { code: 'AMT_MISMATCH',  label: 'Amount figures ≠ amount in words',    category: 'Amount'},
  { code: 'ALTERATION',    label: 'Alteration / overwriting detected',    category: 'Fraud' },
  { code: 'NO_SIGNATURE',  label: 'Signature absent or not detectable',  category: 'Sign'  },
  { code: 'MICR_UNREAD',   label: 'MICR line unreadable',                category: 'MICR'  },
  { code: 'CTS_NON_COMP',  label: 'Non-CTS-2010 compliant cheque',       category: 'Comp'  },
  { code: 'DUPLICATE',     label: 'Duplicate instrument already presented',category: 'Dup'  },
]

function pickFailReason(seed) {
  return FAIL_REASONS[seed % FAIL_REASONS.length]
}

function makeInstrument(idx, batchNo, sbIfsc) {
  const payees   = ['Reliance Ind.', 'HDFC Securities', 'Tata Cons.', 'Infosys Ltd.', 'SBI MF', 'L&T Fin.']
  const amounts  = ['12500', '45000', '200000', '875000', '15000', '350000']
  const fail     = Math.random() < 0.18 // ~18% rejection rate
  const reason   = fail ? pickFailReason(idx) : null
  return {
    instrument_id:   `CHQ-DBC-${String(idx).padStart(5,'0')}`,
    account_display: `****${1000 + ((idx * 37) % 9000)}`,
    payee:           payees[idx % payees.length],
    amount:          amounts[idx % amounts.length],
    micr:            `0${idx % 9}2000${String(idx).padStart(6,'0')}`,
    date_on_cheque:  '19-Jun-2026',
    passed:          !fail,
    fail_code:       reason?.code ?? null,
    fail_label:      reason?.label ?? null,
    fail_category:   reason?.category ?? null,
    seq_in_batch:    idx,
    image_bw:        `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_${String(idx).padStart(4,'0')}_FRONT_BW.TIF`,
    images_all:      fail ? [
      `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_${String(idx).padStart(4,'0')}_FRONT_COL.TIF`,
      `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_${String(idx).padStart(4,'0')}_FRONT_BW.TIF`,
      `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_${String(idx).padStart(4,'0')}_BACK_BW.TIF`,
      `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_${String(idx).padStart(4,'0')}_UV.TIF`,
    ] : [],
    arrived_at: new Date().toISOString(),
  }
}

function makeBatch(batchNo, seedCount = 12, sbIfsc = '') {
  const items = Array.from({ length: seedCount }, (_, i) => makeInstrument(i + 1, batchNo, sbIfsc))
  return {
    batchNo,
    batchId:   `BATCH-${sbIfsc}-${DATE_STR}-${String(batchNo).padStart(2,'0')}`,
    cxfFile:   `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}.CXF`,
    rejFile:   `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_REJ.CXF`,
    folder:    `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}/`,
    rejFolder: `${sbIfsc}_${DATE_STR}_${SESSION_ID}_B${String(batchNo).padStart(2,'0')}_REJ/`,
    status:    'OPEN',   // OPEN | CLOSED
    items,
    openedAt:  new Date().toISOString(),
    closedAt:  null,
    nextSeq:   seedCount + 1,
  }
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function BatchHeader({ batch, onClose, isDark }) {
  const th = {
    bar:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    label:  isDark ? 'text-slate-400' : 'text-slate-500',
    muted:  isDark ? 'text-slate-500' : 'text-slate-400',
    open:   isDark ? 'text-emerald-400' : 'text-emerald-600',
    closed: isDark ? 'text-slate-400'   : 'text-slate-500',
  }
  const passed  = batch.items.filter(i => i.passed).length
  const failed  = batch.items.filter(i => !i.passed).length
  const isOpen  = batch.status === 'OPEN'
  return (
    <div className={`shrink-0 border-b ${th.bar} px-5 py-3 flex items-center gap-4 flex-wrap`}>
      <div>
        <div className={`text-[10px] uppercase tracking-widest ${th.label} mb-0.5`}>Current Batch</div>
        <div className="flex items-center gap-2">
          <span className={`text-[13px] font-mono font-semibold ${isDark ? 'text-white' : 'text-slate-900'}`}>
            {batch.batchId}
          </span>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold
            ${isOpen
              ? (isDark ? 'bg-emerald-400/10 text-emerald-400 border border-emerald-400/20' : 'bg-emerald-50 text-emerald-700 border border-emerald-200')
              : (isDark ? 'bg-slate-700 text-slate-400 border border-white/8' : 'bg-slate-100 text-slate-500 border border-slate-200')
            }`}>
            {isOpen ? '● OPEN' : '■ CLOSED'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-6 ml-2">
        <div>
          <div className={`text-[9px] uppercase tracking-wider ${th.muted}`}>Total</div>
          <div className={`text-lg font-bold font-mono ${isDark ? 'text-white' : 'text-slate-900'}`}>{batch.items.length}</div>
        </div>
        <div>
          <div className={`text-[9px] uppercase tracking-wider ${th.muted}`}>Passed</div>
          <div className={`text-lg font-bold font-mono ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>{passed}</div>
        </div>
        <div>
          <div className={`text-[9px] uppercase tracking-wider ${th.muted}`}>Rejected</div>
          <div className={`text-lg font-bold font-mono ${failed > 0 ? 'text-red-400' : (isDark ? 'text-slate-500' : 'text-slate-400')}`}>{failed}</div>
        </div>
        <div>
          <div className={`text-[9px] uppercase tracking-wider ${th.muted}`}>Session</div>
          <div className={`text-[11px] font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{SESSION_ID}</div>
        </div>
      </div>

      {isOpen && (
        <button onClick={onClose}
          className={`ml-auto flex items-center gap-2 px-4 py-2 rounded-xl border font-semibold text-[11px] transition-all
            ${isDark
              ? 'border-amber-500/40 bg-amber-900/20 text-amber-400 hover:bg-amber-900/30 hover:border-amber-400/60'
              : 'border-amber-400 bg-amber-50 text-amber-700 hover:bg-amber-100'
            }`}>
          <span>■</span> Close Batch
        </button>
      )}
      {!isOpen && (
        <div className={`ml-auto text-[10px] font-mono ${th.muted}`}>
          Closed {new Date(batch.closedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </div>
      )}
    </div>
  )
}

function DownloadBtn({ label, icon, filename, disabled, isDark }) {
  const [state, setState] = useState('idle') // idle | busy | done

  function handleClick() {
    if (disabled || state !== 'idle') return
    setState('busy')
    setTimeout(() => {
      setState('done')
      setTimeout(() => setState('idle'), 3000)
    }, 900)
  }

  const base = `flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[10px] font-semibold transition-all`

  if (disabled) return (
    <div className={`${base} cursor-not-allowed ${isDark ? 'border-white/6 text-slate-600 bg-white/2' : 'border-slate-200 text-slate-300 bg-slate-50'}`}>
      {icon} {label}
    </div>
  )
  if (state === 'busy') return (
    <div className={`${base} ${isDark ? 'border-amber-600/30 text-amber-400 bg-amber-900/10' : 'border-amber-300 text-amber-600 bg-amber-50'}`}>
      <span className="w-3 h-3 rounded-full border border-current border-t-transparent animate-spin" />
      Preparing…
    </div>
  )
  if (state === 'done') return (
    <div title={filename}
      className={`${base} ${isDark ? 'border-emerald-600/40 text-emerald-400 bg-emerald-900/10' : 'border-emerald-300 text-emerald-600 bg-emerald-50'}`}>
      ✓ Ready — {filename}
    </div>
  )
  return (
    <button onClick={handleClick} title={filename}
      className={`${base} ${isDark
        ? 'border-white/10 text-slate-300 bg-white/4 hover:border-gold-400/30 hover:text-gold-400'
        : 'border-slate-300 text-slate-600 bg-white hover:border-amber-400 hover:text-amber-600'
      }`}>
      {icon} {label}
    </button>
  )
}

function CxfPreview({ items, filename, isDark, type }) {
  const passed  = items.filter(i => i.passed)
  const failed  = items.filter(i => !i.passed)
  const rows    = type === 'success' ? passed : failed
  const total   = rows.length
  const totalAmt = rows.reduce((s, i) => s + parseInt(i.amount, 10), 0)

  return (
    <div>
      <div className={`text-[9px] font-semibold uppercase tracking-widest mb-1.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        CXF Preview — {filename}
      </div>
      <div className={`rounded-lg border font-mono text-[9px] overflow-x-auto p-3 leading-relaxed
        ${isDark ? 'bg-black/40 border-white/8 text-slate-400' : 'bg-slate-900 border-slate-700 text-slate-300'}`}>
        <div className="text-emerald-400">{`# NPCI CTS-2010 · ${type === 'success' ? 'Presentment' : 'Rejected'} File`}</div>
        <div className="text-slate-500">{`# Presenting Bank: ${SB_NAME} (${SB_IFSC}) · Date: ${DATE_STR}`}</div>
        <div>{`HDR|${SB_IFSC}|${DATE_STR}|${SESSION_ID}|${String(total).padStart(6,'0')}|CTS2010`}</div>
        {rows.slice(0, 4).map((item, i) => (
          <div key={i} className={type === 'success' ? 'text-slate-300' : 'text-red-400/80'}>
            {type === 'success'
              ? `DTL|${String(i+1).padStart(6,'0')}|${item.micr}|${item.account_display}|${item.amount}|${item.date_on_cheque.replace(/-/g,'')}|${item.image_bw}`
              : `DTL|${String(i+1).padStart(6,'0')}|${item.micr}|${item.account_display}|${item.amount}|${item.date_on_cheque.replace(/-/g,'')}|${item.fail_code}|${item.fail_label}`
            }
          </div>
        ))}
        {total > 4 && <div className="text-slate-600">{`... ${total - 4} more records ...`}</div>}
        <div className={type === 'success' ? 'text-slate-300' : 'text-red-400/80'}>
          {`TRL|${String(total).padStart(6,'0')}|${totalAmt.toLocaleString()}`}
        </div>
      </div>
    </div>
  )
}

function ImageManifest({ items, isDark, type }) {
  const rows = type === 'success'
    ? items.filter(i => i.passed).map(i => ({ name: i.image_bw, spec: '200DPI · 1-bit B&W · G4', size: `${42 + Math.floor(Math.random()*40)}KB` }))
    : items.filter(i => !i.passed).flatMap(i => i.images_all.map(img => ({ name: img, spec: img.includes('UV') ? 'UV image' : img.includes('COL') ? 'Colour' : '1-bit B&W · G4', size: `${30 + Math.floor(Math.random()*60)}KB` })))

  const th = {
    head: isDark ? 'bg-white/3 border-white/6' : 'bg-slate-50 border-slate-200',
    row:  isDark ? 'border-white/4' : 'border-slate-100',
    lbl:  isDark ? 'text-slate-400' : 'text-slate-500',
    body: isDark ? 'text-slate-300' : 'text-slate-700',
    faint:isDark ? 'text-slate-500' : 'text-slate-400',
  }

  return (
    <div>
      <div className={`text-[9px] font-semibold uppercase tracking-widest mb-1.5 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        Image Folder — {rows.length} file{rows.length !== 1 ? 's' : ''}
        {type === 'success' && <span className={`ml-2 ${th.faint}`}>(front face B&W only)</span>}
        {type === 'rejected' && <span className={`ml-2 ${th.faint}`}>(all images — front/back/UV)</span>}
      </div>
      <div className={`rounded-lg border overflow-hidden ${isDark ? 'bg-white/2 border-white/6' : 'bg-white border-slate-200'}`}>
        <div className={`grid grid-cols-3 px-3 py-1.5 border-b ${th.head}`}>
          <span className={`text-[8px] uppercase tracking-wider ${th.faint}`}>Filename</span>
          <span className={`text-[8px] uppercase tracking-wider ${th.faint}`}>Spec</span>
          <span className={`text-[8px] uppercase tracking-wider ${th.faint}`}>Size</span>
        </div>
        {rows.slice(0, 6).map((r, i) => (
          <div key={i} className={`grid grid-cols-3 px-3 py-1.5 border-b ${th.row} text-[9px]`}>
            <span className={`font-mono truncate ${th.body}`}>{r.name}</span>
            <span className={th.faint}>{r.spec}</span>
            <span className={`font-mono ${th.faint}`}>{r.size}</span>
          </div>
        ))}
        {rows.length > 6 && (
          <div className={`px-3 py-1.5 text-[9px] ${th.faint}`}>+ {rows.length - 6} more files</div>
        )}
        {rows.length === 0 && (
          <div className={`px-3 py-3 text-[9px] text-center ${th.faint}`}>No images yet</div>
        )}
      </div>
    </div>
  )
}

function RejectBreakdown({ items, isDark }) {
  const failed = items.filter(i => !i.passed)
  if (failed.length === 0) return null

  const byCat = {}
  failed.forEach(i => {
    const cat = i.fail_category ?? 'Other'
    byCat[cat] = (byCat[cat] || 0) + 1
  })

  const th = {
    card:  isDark ? 'bg-red-900/10 border-red-500/20' : 'bg-red-50 border-red-200',
    lbl:   isDark ? 'text-red-400' : 'text-red-600',
    body:  isDark ? 'text-red-300' : 'text-red-700',
    faint: isDark ? 'text-red-500/70' : 'text-red-400',
  }

  return (
    <div className={`rounded-xl border px-4 py-3 ${th.card}`}>
      <div className={`text-[9px] uppercase tracking-widest font-semibold mb-2 ${th.lbl}`}>Rejection Breakdown</div>
      <div className="flex flex-wrap gap-3">
        {Object.entries(byCat).map(([cat, count]) => (
          <div key={cat} className="flex items-center gap-1.5">
            <span className={`text-[10px] font-bold font-mono ${th.body}`}>{count}</span>
            <span className={`text-[9px] ${th.faint}`}>{cat}</span>
          </div>
        ))}
      </div>
      <div className={`mt-2 text-[9px] ${th.faint}`}>
        Not sent to NGCH · Available for operator review · Download for records
      </div>
    </div>
  )
}

// ─── Batch History Row ────────────────────────────────────────────────────────

function HistoryRow({ batch, isDark }) {
  const passed = batch.items.filter(i => i.passed).length
  const failed = batch.items.filter(i => !i.passed).length
  const th = {
    row:   isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    mono:  isDark ? 'text-slate-300' : 'text-slate-700',
    faint: isDark ? 'text-slate-500' : 'text-slate-400',
  }
  return (
    <div className={`flex items-center gap-4 px-5 py-3 border-b ${th.row} transition-colors`}>
      <div className="min-w-0 flex-1">
        <div className={`text-[11px] font-mono font-semibold ${th.mono}`}>{batch.batchId}</div>
        <div className={`text-[9px] ${th.faint} mt-0.5`}>
          {passed} passed · {failed} rejected · Closed {new Date(batch.closedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <DownloadBtn label="Success CXF"  icon="📄" filename={batch.cxfFile} disabled={passed === 0} isDark={isDark} />
        <DownloadBtn label="Success Images" icon="🗂" filename={batch.folder}  disabled={passed === 0} isDark={isDark} />
        <DownloadBtn label="Reject CXF"   icon="📋" filename={batch.rejFile} disabled={failed === 0} isDark={isDark} />
        <DownloadBtn label="Reject Images" icon="🗂" filename={batch.rejFolder} disabled={failed === 0} isDark={isDark} />
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CTSPresentmentFile() {
  const { bankIfsc, bankName, isSB, isSMB } = useBankContext()
  const SB_IFSC = bankIfsc
  const SB_NAME = bankName
  const { isDark } = useTheme()

  const [currentBatch, setCurrentBatch] = useState(() => makeBatch(1, 14, bankIfsc))
  const [history, setHistory]           = useState([])
  const [batchCounter, setBatchCounter] = useState(1)
  const [expandSuccess, setExpandSuccess] = useState(true)
  const [expandReject, setExpandReject]   = useState(true)
  const seqRef = useRef(currentBatch.nextSeq)

  // Simulate Kafka listener: instruments arrive and get appended to current batch
  useEffect(() => {
    const timer = setInterval(() => {
      if (Math.random() > 0.45) return
      if (currentBatch.status !== 'OPEN') return

      setCurrentBatch(prev => {
        const newItem = makeInstrument(seqRef.current, prev.batchNo, SB_IFSC)
        seqRef.current += 1
        return { ...prev, items: [...prev.items, newItem], nextSeq: seqRef.current }
      })
    }, 2200)
    return () => clearInterval(timer)
  }, [currentBatch.status])

  function handleCloseBatch() {
    const closed = { ...currentBatch, status: 'CLOSED', closedAt: new Date().toISOString() }
    setHistory(prev => [closed, ...prev])
    const newBatchNo = batchCounter + 1
    setBatchCounter(newBatchNo)
    seqRef.current = 1
    setCurrentBatch(makeBatch(newBatchNo, 0, SB_IFSC))
  }

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    divider: isDark ? 'border-white/10' : 'border-slate-200',
    heading: isDark ? 'text-white'      : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'  : 'text-slate-500',
    lbl:     isDark ? 'text-slate-500'  : 'text-slate-400',
    card:    isDark ? 'bg-navy-900/60 border-white/8' : 'bg-white border-slate-200',
    section: isDark ? 'bg-white/2 border-white/6'  : 'bg-slate-50 border-slate-200',
  }

  const passed = currentBatch.items.filter(i => i.passed)
  const failed = currentBatch.items.filter(i => !i.passed)
  const isOpen = currentBatch.status === 'OPEN'

  return (
    <AppShell>
      <div className={`flex flex-col h-full ${th.page}`}>

        {/* Batch header bar */}
        <BatchHeader batch={currentBatch} onClose={handleCloseBatch} isDark={isDark} />

        {/* Format spec strip */}
        <div className={`shrink-0 border-b ${th.divider} px-5 py-2 flex items-center gap-5 flex-wrap`}>
          {[
            { tag: 'CXF',  desc: 'Cheque eXchange File · NPCI CTS-2010 fixed-width format' },
            { tag: 'TIFF', desc: 'Front face · 200 DPI · 1-bit B&W · Group 4 · ≤100 KB' },
            { tag: 'PKI',  desc: 'HSM SHA-256 .sig · FIPS 140-2 Level 3' },
            { tag: 'MinIO',desc: 'All images archived to object store on arrival' },
          ].map(f => (
            <div key={f.tag} className="flex items-baseline gap-1.5">
              <span className={`text-[9px] font-bold font-mono px-1.5 py-0.5 rounded ${isDark ? 'bg-white/8 text-slate-300' : 'bg-slate-100 text-slate-600'}`}>{f.tag}</span>
              <span className={`text-[9px] ${th.lbl}`}>{f.desc}</span>
            </div>
          ))}
          {isOpen && (
            <span className={`ml-auto text-[9px] font-mono ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
              ● Kafka listener active — auto-updating
            </span>
          )}
        </div>

        {/* Main two-panel body */}
        <div className="flex flex-1 min-h-0 gap-0">

          {/* ── Success file panel ────────────────────────────────────────── */}
          <div className={`flex-1 min-w-0 border-r ${th.divider} flex flex-col`}>

            {/* Panel header */}
            <button
              onClick={() => setExpandSuccess(v => !v)}
              className={`shrink-0 flex items-center gap-3 px-5 py-3 border-b ${th.divider} w-full text-left transition-colors
                ${isDark ? 'hover:bg-white/2' : 'hover:bg-slate-50'}`}>
              <span className={`text-[10px] transition-transform ${expandSuccess ? 'rotate-90' : ''} ${th.lbl}`}>▶</span>
              <div className="flex-1">
                <div className={`text-[10px] uppercase tracking-widest font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
                  ✓ Success File
                </div>
                <div className={`text-[9px] ${th.lbl} mt-0.5`}>{currentBatch.cxfFile}</div>
              </div>
              <div className={`text-2xl font-bold font-mono ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>
                {passed.length}
              </div>
            </button>

            {expandSuccess && (
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

                {/* Download buttons */}
                <div className="flex items-center gap-2 flex-wrap">
                  <DownloadBtn
                    label="Download CXF"
                    icon="📄"
                    filename={currentBatch.cxfFile}
                    disabled={passed.length === 0}
                    isDark={isDark}
                  />
                  <DownloadBtn
                    label="Download Image Folder"
                    icon="🗂"
                    filename={currentBatch.folder}
                    disabled={passed.length === 0}
                    isDark={isDark}
                  />
                  <span className={`text-[9px] ${th.lbl} ml-1`}>
                    Send to NGCH — coming soon
                  </span>
                </div>

                {/* Live instrument list */}
                <div>
                  <div className={`text-[9px] font-semibold uppercase tracking-widest mb-2 ${th.muted}`}>
                    Instruments in file ({passed.length})
                    {isOpen && <span className={`ml-2 font-normal ${isDark ? 'text-emerald-400/70' : 'text-emerald-600/70'}`}>live</span>}
                  </div>
                  <div className={`rounded-xl border overflow-hidden ${th.card}`}>
                    {passed.length === 0 && (
                      <div className={`px-4 py-6 text-center text-[11px] ${th.lbl}`}>
                        Waiting for instruments to pass AI pipeline…
                      </div>
                    )}
                    {passed.slice(-8).reverse().map((item, i) => (
                      <div key={item.instrument_id}
                        className={`flex items-center gap-3 px-4 py-2 border-b ${isDark ? 'border-white/4' : 'border-slate-100'} last:border-0`}>
                        <div className="min-w-0 flex-1">
                          <span className={`text-[10px] font-mono font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>
                            {item.instrument_id}
                          </span>
                          <span className={`text-[9px] ml-2 ${th.lbl}`}>{item.payee} · ₹{parseInt(item.amount).toLocaleString()}</span>
                        </div>
                        <span className={`text-[9px] font-mono ${th.lbl} shrink-0`}>
                          {item.image_bw.split('/').pop?.() ?? item.image_bw}
                        </span>
                      </div>
                    ))}
                    {passed.length > 8 && (
                      <div className={`px-4 py-2 text-[9px] ${th.lbl}`}>
                        + {passed.length - 8} earlier instruments in file
                      </div>
                    )}
                  </div>
                </div>

                {/* CXF preview */}
                {passed.length > 0 && (
                  <CxfPreview items={currentBatch.items} filename={currentBatch.cxfFile} isDark={isDark} type="success" />
                )}

                {/* Image manifest */}
                {passed.length > 0 && (
                  <ImageManifest items={currentBatch.items} isDark={isDark} type="success" />
                )}
              </div>
            )}
          </div>

          {/* ── Rejected file panel ───────────────────────────────────────── */}
          <div className={`flex-1 min-w-0 flex flex-col`}>

            {/* Panel header */}
            <button
              onClick={() => setExpandReject(v => !v)}
              className={`shrink-0 flex items-center gap-3 px-5 py-3 border-b ${th.divider} w-full text-left transition-colors
                ${isDark ? 'hover:bg-white/2' : 'hover:bg-slate-50'}`}>
              <span className={`text-[10px] transition-transform ${expandReject ? 'rotate-90' : ''} ${th.lbl}`}>▶</span>
              <div className="flex-1">
                <div className={`text-[10px] uppercase tracking-widest font-semibold ${failed.length > 0 ? 'text-red-400' : (isDark ? 'text-slate-500' : 'text-slate-400')}`}>
                  ✕ Rejected File
                </div>
                <div className={`text-[9px] ${th.lbl} mt-0.5`}>{currentBatch.rejFile}</div>
              </div>
              <div className={`text-2xl font-bold font-mono ${failed.length > 0 ? 'text-red-400' : (isDark ? 'text-slate-600' : 'text-slate-300')}`}>
                {failed.length}
              </div>
            </button>

            {expandReject && (
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

                {/* Rejection breakdown */}
                <RejectBreakdown items={currentBatch.items} isDark={isDark} />

                {/* Download buttons */}
                <div className="flex items-center gap-2 flex-wrap">
                  <DownloadBtn
                    label="Download Rejected CXF"
                    icon="📋"
                    filename={currentBatch.rejFile}
                    disabled={failed.length === 0}
                    isDark={isDark}
                  />
                  <DownloadBtn
                    label="Download All Images"
                    icon="🗂"
                    filename={currentBatch.rejFolder}
                    disabled={failed.length === 0}
                    isDark={isDark}
                  />
                </div>

                {/* Rejected instrument list */}
                <div>
                  <div className={`text-[9px] font-semibold uppercase tracking-widest mb-2 ${th.muted}`}>
                    Rejected instruments ({failed.length})
                  </div>
                  <div className={`rounded-xl border overflow-hidden ${th.card}`}>
                    {failed.length === 0 && (
                      <div className={`px-4 py-6 text-center text-[11px] ${th.lbl}`}>No rejections in this batch</div>
                    )}
                    {failed.map(item => (
                      <div key={item.instrument_id}
                        className={`flex items-start gap-3 px-4 py-2.5 border-b ${isDark ? 'border-white/4' : 'border-slate-100'} last:border-0`}>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] font-mono font-semibold text-red-400`}>
                              {item.instrument_id}
                            </span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold
                              ${isDark ? 'bg-red-900/30 text-red-400 border border-red-500/20' : 'bg-red-50 text-red-600 border border-red-200'}`}>
                              {item.fail_category}
                            </span>
                          </div>
                          <div className={`text-[9px] mt-0.5 ${isDark ? 'text-red-400/70' : 'text-red-500'}`}>
                            {item.fail_label}
                          </div>
                          <div className={`text-[9px] mt-0.5 ${th.lbl}`}>
                            {item.payee} · ₹{parseInt(item.amount).toLocaleString()} · {item.images_all.length} images
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* CXF preview */}
                {failed.length > 0 && (
                  <CxfPreview items={currentBatch.items} filename={currentBatch.rejFile} isDark={isDark} type="rejected" />
                )}

                {/* Image manifest */}
                {failed.length > 0 && (
                  <ImageManifest items={currentBatch.items} isDark={isDark} type="rejected" />
                )}
              </div>
            )}
          </div>
        </div>

        {/* Batch history */}
        {history.length > 0 && (
          <div className={`shrink-0 border-t ${th.divider}`}>
            <div className={`px-5 py-2 border-b ${th.divider}`}>
              <span className={`text-[10px] uppercase tracking-widest ${th.lbl}`}>
                Closed Batches — {history.length}
              </span>
            </div>
            <div className="max-h-40 overflow-y-auto">
              {history.map(b => (
                <HistoryRow key={b.batchId} batch={b} isDark={isDark} />
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
