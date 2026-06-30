import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ── Mock batch ────────────────────────────────────────────────────────────────
const TEMPLATE = {
  bank_name: 'South View Co-operative Bank',
  branch_name: 'Fort Branch',
  bank_ifsc: 'SVCB0000001',
  endorsement_text: "Payee's Account Credited. Received for Collection.",
}

const INSTRUMENTS = [
  // LOT-01
  { id: 'CHQ-IN-20260619-001', cheque: '500001', suffix: '4521', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-002', cheque: '500002', suffix: '7832', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-003', cheque: '500003', suffix: '2291', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-004', cheque: '500004', suffix: '6610', lot: 'LOT-01' },
  { id: 'CHQ-IN-20260619-005', cheque: '500005', suffix: '3347', lot: 'LOT-01' },
  // LOT-02
  { id: 'CHQ-IN-20260619-006', cheque: '500006', suffix: '9901', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-007', cheque: '500007', suffix: '1123', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-008', cheque: '500008', suffix: '5580', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-009', cheque: '500009', suffix: '8812', lot: 'LOT-02' },
  { id: 'CHQ-IN-20260619-010', cheque: '500010', suffix: '4400', lot: 'LOT-02' },
  // LOT-03
  { id: 'CHQ-IN-20260619-011', cheque: '500011', suffix: '7265', lot: 'LOT-03' },
  { id: 'CHQ-IN-20260619-012', cheque: '500012', suffix: '3319', lot: 'LOT-03' },
  { id: 'CHQ-IN-20260619-013', cheque: '500013', suffix: '9042', lot: 'LOT-03' },
  { id: 'CHQ-IN-20260619-014', cheque: '500014', suffix: '6178', lot: 'LOT-03' },
  { id: 'CHQ-IN-20260619-015', cheque: '500015', suffix: '2256', lot: 'LOT-03' },
  // LOT-04
  { id: 'CHQ-IN-20260619-016', cheque: '500016', suffix: '8834', lot: 'LOT-04' },
  { id: 'CHQ-IN-20260619-017', cheque: '500017', suffix: '1190', lot: 'LOT-04' },
  { id: 'CHQ-IN-20260619-018', cheque: '500018', suffix: '5523', lot: 'LOT-04' },
  { id: 'CHQ-IN-20260619-019', cheque: '500019', suffix: '7741', lot: 'LOT-04' },
  { id: 'CHQ-IN-20260619-020', cheque: '500020', suffix: '3367', lot: 'LOT-04' },
]

const LOTS = ['LOT-01', 'LOT-02', 'LOT-03', 'LOT-04']

const PRESENTATION_DATE = '2026-06-19'
const MAX_ENDORSEMENT_TEXT_LEN = 120

function buildQrData(instr) {
  return `ASTRA-ENDORSE|${TEMPLATE.bank_ifsc}|${instr.id}|${instr.suffix}|${PRESENTATION_DATE}`
}

export default function CTSEndorsement() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input:   isDark ? 'bg-navy-800 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    mono:    isDark ? 'text-slate-300 font-mono text-xs' : 'text-slate-600 font-mono text-xs',
  }

  const STATUS_D = {
    ENDORSED: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    PENDING:  'bg-slate-800 text-slate-400 border-slate-700',
  }
  const STATUS_L = {
    ENDORSED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    PENDING:  'bg-slate-100 text-slate-500 border-slate-300',
  }
  const STATUS = isDark ? STATUS_D : STATUS_L

  const [statuses, setStatuses] = useState(() =>
    Object.fromEntries(INSTRUMENTS.map(i => [i.id, 'PENDING']))
  )
  const [endorsing, setEndorsing]           = useState(false)
  const [endorsingLot, setEndorsingLot]     = useState(null)
  const [selected, setSelected]             = useState(null)
  const [endorsementText, setEndorsementText] = useState(TEMPLATE.endorsement_text)

  const endorsed = Object.values(statuses).filter(s => s === 'ENDORSED').length
  const pending  = Object.values(statuses).filter(s => s === 'PENDING').length

  const lotsComplete = LOTS.filter(lot =>
    INSTRUMENTS.filter(i => i.lot === lot).every(i => statuses[i.id] === 'ENDORSED')
  ).length

  function endorseIds(ids, onDone) {
    const pendingIds = ids.filter(id => statuses[id] === 'PENDING')
    if (pendingIds.length === 0) { onDone?.(); return }
    pendingIds.forEach((id, idx) => {
      setTimeout(() => {
        setStatuses(prev => ({ ...prev, [id]: 'ENDORSED' }))
        if (idx === pendingIds.length - 1) onDone?.()
      }, (idx + 1) * 200)
    })
  }

  function endorseAll() {
    setEndorsing(true)
    const ids = INSTRUMENTS.filter(i => statuses[i.id] === 'PENDING').map(i => i.id)
    endorseIds(ids, () => setEndorsing(false))
  }

  function endorseLot(lot) {
    setEndorsingLot(lot)
    const ids = INSTRUMENTS.filter(i => i.lot === lot && statuses[i.id] === 'PENDING').map(i => i.id)
    endorseIds(ids, () => setEndorsingLot(null))
  }

  usePageHeader({
    subtitle: `Automated reverse-image stamping — ${TEMPLATE.bank_name} · ${TEMPLATE.bank_ifsc}`,
    actions: (
      <button
        onClick={endorseAll}
        disabled={endorsing || pending === 0}
        className={`flex items-center gap-2 text-xs rounded-lg px-4 py-2 font-medium transition-colors ${
          pending === 0
            ? isDark
              ? 'bg-white/5 text-slate-500 cursor-not-allowed'
              : 'bg-slate-100 text-slate-400 cursor-not-allowed'
            : 'bg-violet-600 hover:bg-violet-500 text-white'
        }`}
      >
        {endorsing && <span className="w-2 h-2 rounded-full bg-white animate-pulse" />}
        {endorsing ? 'Endorsing…' : pending === 0 ? 'All Endorsed' : `Endorse All (${pending})`}
      </button>
    ),
  })

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            {
              label: 'Total Instruments',
              value: INSTRUMENTS.length,
              color: th.heading,
            },
            {
              label: 'Endorsed',
              value: endorsed,
              color: isDark ? 'text-emerald-400' : 'text-emerald-600',
            },
            {
              label: 'Pending',
              value: pending,
              color: pending > 0
                ? (isDark ? 'text-amber-400' : 'text-amber-600')
                : (isDark ? 'text-emerald-400' : 'text-emerald-600'),
            },
            {
              label: 'Lots Complete',
              value: `${lotsComplete} / 4`,
              color: isDark ? 'text-violet-400' : 'text-violet-600',
            },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Endorsement template editor */}
        <div className={`border rounded-xl p-4 mb-4 ${th.card}`}>
          <div className={`text-xs font-medium ${th.heading} mb-2`}>Endorsement Stamp Template</div>

          {/* Static stamp preview */}
          <div className={`border rounded-lg px-4 py-3 text-xs mb-3 ${
            isDark ? 'border-violet-700/40 bg-violet-900/10' : 'border-violet-200 bg-violet-50'
          }`}>
            <div className={`font-semibold ${isDark ? 'text-violet-300' : 'text-violet-700'}`}>
              {TEMPLATE.bank_name}
            </div>
            <div className={`${th.muted} mt-0.5`}>
              {TEMPLATE.branch_name} · IFSC: {TEMPLATE.bank_ifsc}
            </div>
            <div className={`mt-1 ${th.body}`}>Payee's Account Credited: ****XXXX</div>
            <div className={th.body}>Date of Presentation: {PRESENTATION_DATE}</div>
            <div className={`mt-1 italic ${th.muted}`}>{endorsementText}</div>
          </div>

          {/* Editable endorsement text */}
          <div className="flex flex-col gap-1">
            <label className={`text-[10px] font-medium ${th.faint} uppercase tracking-wider`}>
              Endorsement Text (editable)
            </label>
            <textarea
              value={endorsementText}
              onChange={e => {
                if (e.target.value.length <= MAX_ENDORSEMENT_TEXT_LEN)
                  setEndorsementText(e.target.value)
              }}
              rows={2}
              className={`w-full border rounded-lg px-3 py-2 text-xs resize-none outline-none focus:ring-1 focus:ring-violet-500 transition ${th.input}`}
            />
            <div className={`text-[10px] text-right ${
              endorsementText.length >= MAX_ENDORSEMENT_TEXT_LEN
                ? (isDark ? 'text-red-400' : 'text-red-500')
                : th.faint
            }`}>
              {endorsementText.length} / {MAX_ENDORSEMENT_TEXT_LEN}
            </div>
          </div>
        </div>

        {/* Instruments table — grouped by lot */}
        {LOTS.map(lot => {
          const lotInstruments = INSTRUMENTS.filter(i => i.lot === lot)
          const lotPending = lotInstruments.filter(i => statuses[i.id] === 'PENDING').length
          const lotEndorsed = lotInstruments.length - lotPending
          const isLotDone = lotPending === 0
          const isLotEndorsing = endorsingLot === lot

          return (
            <div key={lot} className={`border rounded-xl overflow-hidden mb-4 ${th.card}`}>
              {/* Lot header */}
              <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
                <div className="flex items-center gap-3">
                  <span className={`text-sm font-medium ${th.heading}`}>{lot}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${STATUS[isLotDone ? 'ENDORSED' : 'PENDING']}`}>
                    {isLotDone ? '✓ Complete' : `${lotPending} pending`}
                  </span>
                  <span className={`text-xs ${th.muted}`}>
                    {lotEndorsed} / {lotInstruments.length} endorsed
                  </span>
                </div>
                <button
                  onClick={() => endorseLot(lot)}
                  disabled={isLotDone || endorsing || isLotEndorsing}
                  className={`flex items-center gap-1.5 text-[11px] rounded-lg px-3 py-1.5 font-medium transition-colors ${
                    isLotDone || endorsing
                      ? isDark
                        ? 'bg-white/5 text-slate-500 cursor-not-allowed'
                        : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                      : 'bg-violet-600 hover:bg-violet-500 text-white'
                  }`}
                >
                  {isLotEndorsing && <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />}
                  {isLotEndorsing ? 'Endorsing…' : isLotDone ? 'Endorsed' : `Endorse ${lot}`}
                </button>
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

              {lotInstruments.map(instr => {
                const status = statuses[instr.id]
                return (
                  <div
                    key={instr.id}
                    className={`grid grid-cols-12 gap-2 px-4 py-2.5 border-b ${th.row} transition-colors text-xs`}
                  >
                    <div className={`col-span-4 ${th.mono}`}>{instr.id}</div>
                    <div className={`col-span-2 ${th.body}`}>{instr.cheque}</div>
                    <div className={`col-span-2 ${th.muted} font-mono`}>****{instr.suffix}</div>
                    <div className={`col-span-1 ${th.faint} text-xs`}>{instr.lot}</div>
                    <div className="col-span-2 text-center">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${STATUS[status]}`}>
                        {status === 'ENDORSED' ? '✓ Endorsed' : 'Pending'}
                      </span>
                    </div>
                    <div className="col-span-1 text-right">
                      <button
                        onClick={() => setSelected(instr)}
                        disabled={status !== 'ENDORSED'}
                        className={`text-[10px] px-2 py-0.5 rounded font-medium transition-colors ${
                          status === 'ENDORSED'
                            ? isDark
                              ? 'bg-white/10 hover:bg-white/15 text-slate-300'
                              : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                            : isDark
                              ? 'text-slate-500 cursor-not-allowed'
                              : 'text-slate-300 cursor-not-allowed'
                        }`}
                      >
                        View
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })}

        {/* Stamp preview modal */}
        {selected && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
            onClick={() => setSelected(null)}
          >
            <div
              className={`w-96 border rounded-2xl p-6 shadow-2xl ${
                isDark ? 'bg-navy-900 border-white/12' : 'bg-white border-slate-200'
              }`}
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <span className={`text-sm font-semibold ${th.heading}`}>Endorsement Stamp Preview</span>
                <button
                  onClick={() => setSelected(null)}
                  className={`text-xs ${th.muted}`}
                >
                  ✕ Close
                </button>
              </div>

              {/* Stamp card */}
              <div className={`border-2 rounded-xl p-4 text-xs ${
                isDark ? 'border-violet-600/50 bg-violet-900/10' : 'border-violet-300 bg-violet-50'
              }`}>
                <div className={`font-bold text-sm ${isDark ? 'text-violet-300' : 'text-violet-800'}`}>
                  {TEMPLATE.bank_name}
                </div>
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
                <div className={`border-t pt-2 italic ${
                  isDark ? 'border-violet-700/40 text-violet-300' : 'border-violet-200 text-violet-700'
                }`}>
                  {endorsementText}
                </div>
              </div>

              {/* QR data */}
              <div className={`mt-3 rounded-lg px-3 py-2 text-[10px] font-mono break-all ${
                isDark ? 'bg-white/10 text-slate-400' : 'bg-slate-50 text-slate-500'
              }`}>
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
