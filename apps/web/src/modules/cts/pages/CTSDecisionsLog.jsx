import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// RBI return reason code mapping — mirrors modules/cts/rrf/models.py RBIReturnCode
const RBI_CODE_MAP = {
  'Signature mismatch confirmed':      { code: '06', desc: 'Drawer Signature Differs' },
  'Amount alteration detected':        { code: '07', desc: 'Alterations Require Authentication' },
  'Insufficient funds':                { code: '01', desc: 'Funds Insufficient' },
  'Account dormant / frozen':          { code: '13', desc: 'Account Closed / Transferred / Not Traceable' },
  'Post-dated cheque':                 { code: '14', desc: 'Cheque Post-Dated' },
  'Mutilated / damaged cheque':        { code: '15', desc: 'Cheque Stale / Mutilated / Torn' },
  'Words and figures differ':          { code: '16', desc: 'Amount in Words and Figures Differs' },
  'No specimen on file — cannot verify':{ code: '04', desc: 'Refer to Drawer' },
  'Payee name discrepancy':            { code: '09', desc: "Payee's Endorsement Required" },
  'SIG_MISMATCH':                      { code: '06', desc: 'Drawer Signature Differs' },
  'FRAUD_RISK':                        { code: '04', desc: 'Refer to Drawer' },
  'ALTERATION':                        { code: '07', desc: 'Alterations Require Authentication' },
  'DEFAULT':                           { code: '04', desc: 'Refer to Drawer' },
}

function getRbiCode(reason) {
  return RBI_CODE_MAP[reason] || RBI_CODE_MAP['DEFAULT']
}

const SESSION_META = {
  bank_ifsc:     'SVCB0000001',
  bank_name:     'Saraswat Co-op Bank',
  session_id:    'SES-0619-001',
  clearing_zone: 'MUMBAI',
  generated_at:  new Date().toISOString(),
}

const DECISIONS = [
  { id: 'CHQ-2026-001901', micr: '400160001901', account: '****4521', amount: '₹[1L-5L]', payee: 'R***', reason: 'FRAUD_RISK',    outcome: 'STP_RETURN',   agent_ms: 412, fraud: 0.91, ngch: 'ACK-7821', filed: '11:02:14', reviewer: null,      return_reason: 'FRAUD_RISK',                   iet_deadline: '2026-06-19T13:30:00Z', returned_at: '2026-06-19T11:02:14Z', presenting_ifsc: 'HDFC0001234' },
  { id: 'CHQ-2026-001900', micr: '400160001900', account: '****7103', amount: '₹[<1L]',   payee: 'S***', reason: 'CLEAR',         outcome: 'STP_CONFIRM',  agent_ms: 388, fraud: 0.08, ngch: 'ACK-7820', filed: '11:01:52', reviewer: null,      return_reason: null,                           iet_deadline: null,                   returned_at: null,                   presenting_ifsc: 'ICIC0001234' },
  { id: 'CHQ-2026-001899', micr: '400160001899', account: '****2290', amount: '₹[5L-10L]',payee: 'M***', reason: 'VAULT_MISS',    outcome: 'HUMAN_REVIEW', agent_ms: 201, fraud: null, ngch: 'ACK-7819', filed: '10:58:31', reviewer: 'Rahul S.', return_reason: null,                           iet_deadline: null,                   returned_at: null,                   presenting_ifsc: 'SBIN0001234' },
  { id: 'CHQ-2026-001898', micr: '400160001898', account: '****8812', amount: '₹[<1L]',   payee: 'A***', reason: 'ALTERATION',    outcome: 'STP_RETURN',   agent_ms: 544, fraud: 0.87, ngch: 'ACK-7818', filed: '10:55:09', reviewer: null,      return_reason: 'Amount alteration detected',   iet_deadline: '2026-06-19T13:30:00Z', returned_at: '2026-06-19T10:55:09Z', presenting_ifsc: 'AXIS0001234' },
  { id: 'CHQ-2026-001897', micr: '400160001897', account: '****3301', amount: '₹[1L-5L]', payee: 'P***', reason: 'CLEAR',         outcome: 'STP_CONFIRM',  agent_ms: 361, fraud: 0.12, ngch: 'ACK-7817', filed: '10:52:43', reviewer: null,      return_reason: null,                           iet_deadline: null,                   returned_at: null,                   presenting_ifsc: 'HDFC0001234' },
  { id: 'CHQ-2026-001896', micr: '400160001896', account: '****5509', amount: '₹[>1Cr]',  payee: 'N***', reason: 'HIGH_VALUE',    outcome: 'HUMAN_REVIEW', agent_ms: 298, fraud: 0.44, ngch: 'ACK-7816', filed: '10:49:17', reviewer: 'Priya K.', return_reason: null,                           iet_deadline: null,                   returned_at: null,                   presenting_ifsc: 'ICIC0001234' },
  { id: 'CHQ-2026-001895', micr: '400160001895', account: '****1122', amount: '₹[<1L]',   payee: 'V***', reason: 'CLEAR',         outcome: 'STP_CONFIRM',  agent_ms: 402, fraud: 0.05, ngch: 'ACK-7815', filed: '10:47:01', reviewer: null,      return_reason: null,                           iet_deadline: null,                   returned_at: null,                   presenting_ifsc: 'SBIN0001234' },
  { id: 'CHQ-2026-001894', micr: '400160001894', account: '****6634', amount: '₹[1L-5L]', payee: 'D***', reason: 'SIG_MISMATCH',  outcome: 'STP_RETURN',   agent_ms: 478, fraud: 0.79, ngch: 'ACK-7814', filed: '10:44:22', reviewer: null,      return_reason: 'Signature mismatch confirmed', iet_deadline: '2026-06-19T13:30:00Z', returned_at: '2026-06-19T10:44:22Z', presenting_ifsc: 'HDFC0001234' },
]

const OUTCOME_STYLE = {
  STP_CONFIRM:  'text-emerald-700 bg-emerald-50 dark:text-emerald-400 dark:bg-emerald-400/10',
  STP_RETURN:   'text-red-700 bg-red-50 dark:text-red-400 dark:bg-red-400/10',
  HUMAN_REVIEW: 'text-amber-700 bg-amber-50 dark:text-amber-400 dark:bg-amber-400/10'
}


const FILTERS = ['All', 'STP_CONFIRM', 'STP_RETURN', 'HUMAN_REVIEW']

// ── Client-side RRF XML generation (mirrors Python backend logic) ─────────────
function buildRrfXml(returns, sessionMeta) {
  const now = new Date().toISOString().replace(/\.\d+Z$/, 'Z')
  const filedCount = returns.filter(r => r.returned_at && r.iet_deadline && r.returned_at <= r.iet_deadline).length

  const items = returns.map(r => {
    const rbi = getRbiCode(r.return_reason || r.reason)
    const withinIet = r.returned_at && r.iet_deadline
      ? new Date(r.returned_at) <= new Date(r.iet_deadline)
      : true
    return `    <ReturnItem>
      <InstrumentID>${r.id}</InstrumentID>
      <MICRCode>${r.micr}</MICRCode>
      <ReturnReasonCode>${rbi.code}</ReturnReasonCode>
      <ReturnReasonDescription>${rbi.desc}</ReturnReasonDescription>
      <DraweeIFSC>${sessionMeta.bank_ifsc}</DraweeIFSC>
      <PresentingIFSC>${r.presenting_ifsc}</PresentingIFSC>
      <IETDeadline>${r.iet_deadline || ''}</IETDeadline>
      <ReturnedAt>${r.returned_at || now}</ReturnedAt>
      <FiledWithinIET>${withinIet ? 'true' : 'false'}</FiledWithinIET>
      <DecidedBy>${r.reviewer || 'STP_AGENT'}</DecidedBy>
      <AmountRange>${r.amount}</AmountRange>
    </ReturnItem>`
  }).join('\n')

  return `<?xml version="1.0" encoding="UTF-8"?>
<ReturnReasonFile xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="2.0">
  <Header>
    <BankIFSC>${sessionMeta.bank_ifsc}</BankIFSC>
    <SessionID>${sessionMeta.session_id}</SessionID>
    <ClearingZone>${sessionMeta.clearing_zone}</ClearingZone>
    <GeneratedAt>${now}</GeneratedAt>
    <TotalReturns>${returns.length}</TotalReturns>
    <FiledWithinIETCount>${filedCount}</FiledWithinIETCount>
  </Header>
  <Returns>
${items}
  </Returns>
</ReturnReasonFile>`
}

function downloadXml(xml, filename) {
  const blob = new Blob([xml], { type: 'application/xml' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── RRF Preview Modal ─────────────────────────────────────────────────────────
function RrfModal({ returns, sessionMeta, onClose }) {
  const xml = buildRrfXml(returns, sessionMeta)
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const filename = `RRF_${sessionMeta.bank_ifsc}_${date}_${sessionMeta.session_id}.xml`

  const th = {
    overlay: 'fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6',
    modal:   'bg-white border-slate-200 text-slate-900 dark:bg-navy-900 dark:border-white/10 dark:text-white',
    code:    'bg-slate-50 text-emerald-700 border-slate-200 dark:bg-navy-950/80 dark:text-emerald-400 dark:border-white/8',
    muted:   'text-slate-500 dark:text-slate-400',
    btn:     'bg-amber-50 border-amber-300 text-amber-700 hover:bg-amber-100 dark:bg-gold-400/10 dark:border-gold-400/30 dark:text-gold-400 dark:hover:bg-gold-400/20',
  }

  return (
    <div className={th.overlay} onClick={onClose}>
      <div className={`w-full max-w-3xl max-h-[80vh] rounded-2xl border shadow-2xl flex flex-col ${th.modal}`}
        onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className={`flex items-center justify-between px-5 py-3 border-b ${'border-slate-200 dark:border-white/8'}`}>
          <div>
            <div className="text-sm font-semibold">Return Reason File (RRF)</div>
            <div className={`text-[10px] font-mono ${th.muted}`}>{filename}</div>
          </div>
          <div className="flex items-center gap-2">
            <div className={`text-[10px] px-2 py-0.5 rounded border ${'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-400'}`}>
              {returns.length} returns · CTS-2010 XML
            </div>
            <button onClick={() => downloadXml(xml, filename)}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.btn}`}>
              ↓ Download XML
            </button>
            <button onClick={onClose} className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm ${'hover:bg-slate-100 text-slate-500 dark:hover:bg-white/8 dark:text-slate-400'}`}>✕</button>
          </div>
        </div>

        {/* Summary row */}
        <div className={`shrink-0 px-5 py-2 border-b ${'border-slate-200 dark:border-white/8'} flex gap-6 text-[11px] ${th.muted}`}>
          <span>Bank: <span className="font-mono font-semibold">{sessionMeta.bank_ifsc}</span></span>
          <span>Session: <span className="font-mono">{sessionMeta.session_id}</span></span>
          <span>Zone: <span className="font-mono">{sessionMeta.clearing_zone}</span></span>
          <span className={'text-emerald-600 dark:text-emerald-400'}>
            ✓ NGCH-ready · HSM sign pending (backend)
          </span>
        </div>

        {/* XML preview */}
        <pre className={`flex-1 overflow-auto text-[10px] font-mono p-4 rounded-b-2xl border-t ${th.code} leading-relaxed`}>
          {xml}
        </pre>
      </div>
    </div>
  )
}

export default function CTSDecisionsLog() {
  const [filter, setFilter]     = useState('All')
  const [rrfModal, setRrfModal] = useState(null) // null | 'session' | rowId
  const returned = DECISIONS.filter(d => d.outcome === 'STP_RETURN')
  const rows     = filter === 'All' ? DECISIONS : DECISIONS.filter(d => d.outcome === filter)

  const th = {
    page:    'bg-slate-50 dark:bg-transparent',
    card:    'bg-white border-slate-200 dark:bg-white/8 dark:border-white/8',
    heading: 'text-slate-900 dark:text-white',
    body:    'text-slate-700 dark:text-slate-300',
    muted:   'text-slate-500 dark:text-slate-400',
    faint:   'text-slate-400 dark:text-slate-500',
    divider: 'border-slate-200 dark:border-white/8',
    thead:   'bg-slate-50 border-slate-200 text-slate-400 dark:bg-white/2 dark:border-white/8 dark:text-slate-500',
    row:     'border-slate-100 hover:bg-slate-50 dark:border-white/4 dark:hover:bg-white/2',
    filterActive: 'bg-amber-100 text-amber-700 dark:bg-gold-400/15 dark:text-gold-400',
    filterIdle:   'text-slate-400 hover:text-slate-700 dark:text-slate-500 dark:hover:text-slate-300',
    rrfBtn:  'border-red-300 text-red-600 hover:bg-red-50 dark:border-red-500/25 dark:text-red-400 dark:hover:bg-red-500/10',
    sessionRrf: 'border-amber-400 bg-amber-50 text-amber-700 hover:bg-amber-100 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400 dark:hover:bg-amber-500/20',
  }

  const modalReturns = rrfModal === 'session'
    ? returned
    : returned.filter(d => d.id === rrfModal)

  usePageHeader({
    subtitle: `Session: ${SESSION_META.session_id} · ${SESSION_META.bank_name} · ${SESSION_META.clearing_zone}`,
    actions: (
      <div className="flex items-center gap-2">
        {returned.length > 0 && (
          <button onClick={() => setRrfModal('session')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${th.sessionRrf}`}>
            <span>📄</span>
            <span>RRF ({returned.length} returns)</span>
          </button>
        )}
        <div className="flex gap-1">
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${filter === f ? th.filterActive : th.filterIdle}`}>
              {f.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* Summary strip */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {[
            { label: 'Total Filed',   value: DECISIONS.length,                                            color: th.heading },
            { label: 'STP Confirmed', value: DECISIONS.filter(d => d.outcome === 'STP_CONFIRM').length,   color: 'text-emerald-600 dark:text-emerald-400' },
            { label: 'STP Returned',  value: returned.length,                                             color: 'text-red-600 dark:text-red-400' },
            { label: 'Human Review',  value: DECISIONS.filter(d => d.outcome === 'HUMAN_REVIEW').length,  color: 'text-amber-600 dark:text-amber-400' },
            { label: 'RRF Generated', value: returned.length > 0 ? '✓' : '—',                            color: returned.length > 0 ? ('text-emerald-600 dark:text-emerald-400') : th.faint },
          ].map(s => (
            <div key={s.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{s.label}</div>
              <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thead} border-b`}>
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
                <th className="text-left px-4 py-3 font-normal">RRF</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d, i) => {
                const isReturn = d.outcome === 'STP_RETURN'
                const rbi = isReturn ? getRbiCode(d.return_reason || d.reason) : null
                return (
                  <tr key={i} className={`border-b ${th.row} transition-colors`}>
                    <td className={`px-4 py-2.5 ${th.body} font-mono text-[11px]`}>{d.id}</td>
                    <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{d.account}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{d.amount}</td>
                    <td className={`px-4 py-2.5 ${th.muted}`}>{d.reason.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${OUTCOME_STYLE[d.outcome]}`}>
                        {d.outcome.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 text-right ${th.body} font-mono`}>{d.agent_ms}</td>
                    <td className="px-4 py-2.5 text-right">
                      {d.fraud !== null
                        ? <span className={d.fraud > 0.7 ? ('text-red-600 dark:text-red-400') : ('text-emerald-600 dark:text-emerald-400')}>{(d.fraud * 100).toFixed(0)}%</span>
                        : <span className={th.faint}>—</span>}
                    </td>
                    <td className={`px-4 py-2.5 ${th.muted} font-mono text-[10px]`}>{d.ngch}</td>
                    <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{d.filed}</td>
                    <td className={`px-4 py-2.5 ${th.faint}`}>{d.reviewer ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      {isReturn ? (
                        <button onClick={() => setRrfModal(d.id)}
                          className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-medium transition-all ${th.rrfBtn}`}>
                          <span>📄</span>
                          <span className="font-mono">{rbi.code}</span>
                        </button>
                      ) : (
                        <span className={th.faint}>—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* RBI code legend */}
        {returned.length > 0 && (
          <div className={`mt-4 border rounded-xl px-5 py-3 ${th.card}`}>
            <div className={`text-[10px] uppercase tracking-widest ${th.faint} mb-2`}>RBI Return Reason Codes — This Session</div>
            <div className="flex flex-wrap gap-3">
              {[...new Set(returned.map(r => {
                const rbi = getRbiCode(r.return_reason || r.reason)
                return `${rbi.code} — ${rbi.desc}`
              }))].map(entry => (
                <span key={entry} className={`text-[10px] font-mono ${th.muted}`}>{entry}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* RRF Modal */}
      {rrfModal && (
        <RrfModal
          returns={modalReturns}
          sessionMeta={SESSION_META}
          onClose={() => setRrfModal(null)}
        />
      )}
    </AppShell>
  )
}
