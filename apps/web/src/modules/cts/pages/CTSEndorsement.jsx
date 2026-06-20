import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ── Mock batch ────────────────────────────────────────────────────────────────
const TEMPLATE = {
  bank_name: 'South View Co-operative Bank',
  branch_name: 'Fort Branch',
  bank_ifsc: 'SVCB0000001',
  endorsement_text: "Payee's Account Credited. Received for Collection.",
}

const INSTRUMENTS = [
  { id: 'CHQ-IN-20260619-001', cheque: '500001', suffix: '4521', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-002', cheque: '500002', suffix: '7832', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-003', cheque: '500003', suffix: '2291', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-004', cheque: '500004', suffix: '6610', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-005', cheque: '500005', suffix: '3347', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-006', cheque: '500006', suffix: '9901', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-007', cheque: '500007', suffix: '1123', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-008', cheque: '500008', suffix: '5580', lot: 'LOT-02' },
]

const PRESENTATION_DATE = '2026-06-19'

function buildQrData(instr) {
  return `ASTRA-ENDORSE|${TEMPLATE.bank_ifsc}|${instr.id}|${instr.suffix}|${PRESENTATION_DATE}`
}

export default function CTSEndorsement() {
  const { isDark } = useTheme()
  const [statuses, setStatuses] = useState(() =>
    Object.fromEntries(INSTRUMENTS.map(i => [i.id, 'PENDING']))
  )
  const [endorsing, setEndorsing] = useState(false)
  const [selected, setSelected]   = useState(null)

  const th = {
    page:    isDark ? 'bg-transparent'                     : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8'      : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                      : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                  : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                  : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'                  : 'text-slate-400',
    divider: isDark ? 'border-white/8'                  : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    mono:    isDark ? 'text-slate-300 font-mono text-xs': 'text-slate-600 font-mono text-xs',
    input:   isDark ? 'bg-navy-800 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
  }

  const endorsed = Object.values(statuses).filter(s => s === 'ENDORSED').length
  const pending  = Object.values(statuses).filter(s => s === 'PENDING').length

  function endorseAll() {
    setEndorsing(true)
    const pending_ids = INSTRUMENTS.filter(i => statuses[i.id] === 'PENDING').map(i => i.id)
    pending_ids.forEach((id, idx) => {
      setTimeout(() => {
        setStatuses(prev => ({ ...prev, [id]: 'ENDORSED' }))
        if (idx === pending_ids.length - 1) setEndorsing(false)
      }, (idx + 1) * 200)
    })
  }

  const endorsedInstr = INSTRUMENTS.filter(i => statuses[i.id] === 'ENDORSED')

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Endorsement</h1>
            <p className={`text-xs ${th.muted} mt-0.5`}>
              Automated reverse-image stamping — {TEMPLATE.bank_name} · {TEMPLATE.bank_ifsc}
            </p>
          </div>
          <button
            onClick={endorseAll}
            disabled={endorsing || pending === 0}
            className={`flex items-center gap-2 text-xs rounded-lg px-4 py-2 font-medium transition-colors ${
              pending === 0
                ? isDark ? 'bg-white/5 text-slate-500 cursor-not-allowed' : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-violet-600 hover:bg-violet-500 text-white'
            }`}
          >
            {endorsing && <span className="w-2 h-2 rounded-full bg-white animate-pulse" />}
            {endorsing ? 'Endorsing…' : pending === 0 ? 'All Endorsed' : `Endorse All (${pending})`}
          </button>
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Total Instruments', value: INSTRUMENTS.length,  color: th.heading },
            { label: 'Endorsed',          value: endorsed,            color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'Pending',           value: pending,             color: pending > 0 ? (isDark ? 'text-amber-400' : 'text-amber-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600') },
            { label: 'Completion',        value: `${Math.round((endorsed / INSTRUMENTS.length) * 100)}%`, color: isDark ? 'text-violet-400' : 'text-violet-600' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Endorsement stamp reference card */}
        <div className={`border rounded-xl p-4 mb-4 ${th.card}`}>
          <div className={`text-xs font-medium ${th.heading} mb-2`}>Endorsement Stamp Template</div>
          <div className={`border rounded-lg px-4 py-3 text-xs ${isDark ? 'border-violet-700/40 bg-violet-900/10' : 'border-violet-200 bg-violet-50'}`}>
            <div className={`font-semibold ${isDark ? 'text-violet-300' : 'text-violet-700'}`}>{TEMPLATE.bank_name}</div>
            <div className={`${th.muted} mt-0.5`}>{TEMPLATE.branch_name} · IFSC: {TEMPLATE.bank_ifsc}</div>
            <div className={`mt-1 ${th.body}`}>Payee's Account Credited: ****XXXX</div>
            <div className={`${th.body}`}>Date of Presentation: {PRESENTATION_DATE}</div>
            <div className={`mt-1 italic ${th.muted}`}>{TEMPLATE.endorsement_text}</div>
          </div>
        </div>

        {/* Instruments table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-medium ${th.heading}`}>Inward Cheque Batch — {PRESENTATION_DATE}</span>
            <span className={`text-xs ${th.muted}`}>{INSTRUMENTS.length} instruments · 2 lots</span>
          </div>

          {/* Table header */}
          <div className={`grid grid-cols-12 gap-2 px-4 py-2 border-b ${th.divider} text-[10px] ${th.faint} font-medium uppercase tracking-wider`}>
            <div className="col-span-4">Instrument ID</div>
            <div className="col-span-2">Cheque No</div>
            <div className="col-span-2">Account</div>
            <div className="col-span-1">Lot</div>
            <div className="col-span-2 text-center">Status</div>
            <div className="col-span-1 text-right">Action</div>
          </div>

          {INSTRUMENTS.map(instr => {
            const status = statuses[instr.id]
            return (
              <div key={instr.id} className={`grid grid-cols-12 gap-2 px-4 py-2.5 border-b ${th.row} transition-colors text-xs`}>
                <div className={`col-span-4 ${th.mono}`}>{instr.id}</div>
                <div className={`col-span-2 ${th.body}`}>{instr.cheque}</div>
                <div className={`col-span-2 ${th.muted} font-mono`}>****{instr.suffix}</div>
                <div className={`col-span-1 ${th.faint} text-xs`}>{instr.lot}</div>
                <div className="col-span-2 text-center">
                  {status === 'ENDORSED' ? (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${isDark ? 'bg-emerald-900/40 text-emerald-300' : 'bg-emerald-50 text-emerald-700'}`}>
                      ✓ Endorsed
                    </span>
                  ) : (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${isDark ? 'bg-amber-900/40 text-amber-300' : 'bg-amber-50 text-amber-700'}`}>
                      Pending
                    </span>
                  )}
                </div>
                <div className="col-span-1 text-right">
                  <button
                    onClick={() => setSelected(instr)}
                    disabled={status !== 'ENDORSED'}
                    className={`text-[10px] px-2 py-0.5 rounded font-medium transition-colors ${
                      status === 'ENDORSED'
                        ? isDark ? 'bg-white/8 hover:bg-white/12 text-slate-300' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                        : isDark ? 'text-slate-600 cursor-not-allowed' : 'text-slate-300 cursor-not-allowed'
                    }`}
                  >
                    View
                  </button>
                </div>
              </div>
            )
          })}
        </div>

        {/* Stamp preview modal */}
        {selected && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setSelected(null)}>
            <div
              className={`w-96 border rounded-2xl p-6 shadow-2xl ${isDark ? 'bg-navy-900 border-white/12' : 'bg-white border-slate-200'}`}
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <span className={`text-sm font-semibold ${th.heading}`}>Endorsement Stamp Preview</span>
                <button onClick={() => setSelected(null)} className={`text-xs ${th.muted} hover:${th.body}`}>✕ Close</button>
              </div>

              {/* Stamp card */}
              <div className={`border-2 rounded-xl p-4 text-xs ${isDark ? 'border-violet-600/50 bg-violet-900/10' : 'border-violet-300 bg-violet-50'}`}>
                <div className={`font-bold text-sm ${isDark ? 'text-violet-300' : 'text-violet-800'}`}>{TEMPLATE.bank_name}</div>
                <div className={`${th.muted} mb-2`}>{TEMPLATE.branch_name}</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1 mb-2">
                  <div className={th.faint}>IFSC</div>
                  <div className={`font-mono ${th.body}`}>{TEMPLATE.bank_ifsc}</div>
                  <div className={th.faint}>Instrument ID</div>
                  <div className={`font-mono ${th.body} text-[10px]`}>{selected.id}</div>
                  <div className={th.faint}>Cheque No</div>
                  <div className={th.body}>{selected.cheque}</div>
                  <div className={th.faint}>Account Credited</div>
                  <div className={`font-mono ${th.body}`}>****{selected.suffix}</div>
                  <div className={th.faint}>Presentation Date</div>
                  <div className={th.body}>{PRESENTATION_DATE}</div>
                </div>
                <div className={`border-t pt-2 italic ${isDark ? 'border-violet-700/40 text-violet-300' : 'border-violet-200 text-violet-700'}`}>
                  {TEMPLATE.endorsement_text}
                </div>
              </div>

              {/* QR data */}
              <div className={`mt-3 rounded-lg px-3 py-2 text-[10px] font-mono break-all ${isDark ? 'bg-white/4 text-slate-400' : 'bg-slate-50 text-slate-500'}`}>
                <div className={`text-[9px] uppercase tracking-wider ${th.faint} mb-1`}>QR Data</div>
                {buildQrData(selected)}
              </div>
            </div>
          </div>
        )}

      </div>
    </AppShell>
  )
}
