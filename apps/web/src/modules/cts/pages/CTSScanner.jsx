import { useState, useEffect, useRef, useCallback } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import ChequeImageViewer from '../components/ChequeImageViewer'

// ── Constants ──────────────────────────────────────────────────────────────────

const SCANNER_AGENT_DEFAULT_URL = 'http://localhost:9201'

// Message taxonomy — mirrors shared/messages/locales/messages.yaml CTS_OUT_* entries
const MSG_TAXONOMY = [
  { key: 'CTS_OUT_CTS2010_FAIL',         sev: 'ERROR',    surface: ['AUDIT','NOTIFICATION'],        text: 'CTS-2010 validation failed for instrument {instrument_id}: {failure_reason}.' },
  { key: 'CTS_OUT_MISMATCH_HELD',        sev: 'WARN',     surface: ['UI','AUDIT','NOTIFICATION'],   text: 'Amount mismatch detected — instrument {instrument_id} held for manual resolution.' },
  { key: 'CTS_OUT_HUMAN_REVIEW',         sev: 'WARN',     surface: ['UI','AUDIT','NOTIFICATION'],   text: 'Instrument {instrument_id} routed to human review: {review_reason}.' },
  { key: 'CTS_OUT_LOT_INSTRUMENT_ADDED', sev: 'INFO',     surface: ['UI','AUDIT'],                  text: 'Instrument {instrument_id} added to lot {lot_id}.' },
  { key: 'CTS_OUT_LOT_SEALED',           sev: 'INFO',     surface: ['UI','AUDIT'],                  text: 'Lot {lot_id} sealed with {instrument_count} instruments — ready for endorsement.' },
  { key: 'CTS_OUT_LOT_ENDORSED',         sev: 'INFO',     surface: ['UI','AUDIT'],                  text: 'Lot {lot_id} endorsed and submitted to NGCH.' },
  { key: 'CTS_OUT_SCAN_ACCEPTED',        sev: 'INFO',     surface: ['UI'],                           text: 'Scan {scan_id} accepted via {path} path — workflow {workflow_id} started.' },
  { key: 'CTS_OUT_DOUBLE_FEED',          sev: 'WARN',     surface: ['UI','NOTIFICATION'],            text: 'Double feed detected in session {session_id} — cheque ejected, rescan required.' },
  { key: 'CTS_OUT_MICR_FAIL',            sev: 'ERROR',    surface: ['UI','AUDIT','NOTIFICATION'],   text: 'Hardware MICR read failed for scan {scan_id} — operator intervention required.' },
  { key: 'CTS_OUT_SCANNER_OFFLINE',      sev: 'CRITICAL', surface: ['UI','NOTIFICATION'],            text: 'Scanner agent at {agent_url} is unreachable — outward scanning paused.' },
]

// Kafka topics for outward clearing
const KAFKA_TOPICS = (bankId) => [
  { topic: `cts.outward.scanned.${bankId}`,    label: 'scanned',   display: 'Scanned',    desc: 'Scanner → OutwardScanWorkflow',      color: 'violet' },
  { topic: `cts.outward.lot.sealed.${bankId}`, label: 'sealed',    display: 'Lot Sealed', desc: 'Lot Manager → EndorsementWorkflow',  color: 'amber'  },
  { topic: `cts.outward.submitted.${bankId}`,  label: 'submitted', display: 'Submitted',  desc: 'NGCHSubmission → Audit + Analytics', color: 'emerald'},
]

// ── Mock scanner registry (kept for SDK reference section) ────────────────────
const SCANNERS = [
  { id: 'SCN-001', oem: 'PANINI',  model: 'Panini I:Deal',    status: 'READY',    counter: 1287, operator: 'Ramesh K.' },
  { id: 'SCN-002', oem: 'CANON',   model: 'Canon CR-190i',    status: 'SCANNING', counter: 943,  operator: 'Priya M.' },
  { id: 'SCN-003', oem: 'PANINI',  model: 'Panini MyMicr',    status: 'READY',    counter: 2104, operator: 'Anil S.' },
  { id: 'SCN-004', oem: 'CANON',   model: 'Canon CR-120',     status: 'OFFLINE',  counter: 621,  operator: '—' },
  { id: 'SCN-005', oem: 'GENERIC', model: 'TWAIN Compatible', status: 'ERROR',    counter: 88,   operator: 'Suresh P.' },
]

const CHEQUE_NOS = ['100001','100002','100003','100004','100005','100006','100007','100008','100009','100010']
const ACCOUNTS   = ['4521','7832','2291','6610','3347','9901','1123','5580','7744','2256']

const SEV_D = {
  INFO:     'bg-slate-700/60 text-slate-300 border-slate-600/50',
  WARN:     'bg-amber-900/50 text-amber-300 border-amber-700/50',
  ERROR:    'bg-red-900/50   text-red-300   border-red-700/50',
  CRITICAL: 'bg-red-950/80   text-red-200   border-red-600/70',
}
const SEV_L = {
  INFO:     'bg-slate-100 text-slate-600 border-slate-300',
  WARN:     'bg-amber-50  text-amber-700 border-amber-300',
  ERROR:    'bg-red-50    text-red-700   border-red-300',
  CRITICAL: 'bg-red-100   text-red-800   border-red-400',
}

function mkScan(idx) {
  const i = idx % 10
  const hasMicr = Math.random() > 0.05
  const iqa = +(0.82 + Math.random() * 0.17).toFixed(3)
  const outcomes = ['ACCEPTED','ACCEPTED','ACCEPTED','ACCEPTED','CTS_REJECTED','MISMATCH_HELD','HUMAN_REVIEW']
  const outcome = hasMicr && iqa > 0.80 ? 'ACCEPTED' : outcomes[Math.floor(Math.random() * outcomes.length)]
  return {
    scan_id:       `SCAN-20260720-MUM-${String(idx + 1).padStart(5, '0')}`,
    instrument_id: `INS-SCAN-20260720-MUM-${String(idx + 1).padStart(5, '0')}`,
    cheque_no:     CHEQUE_NOS[i],
    acct_suffix:   ACCOUNTS[i],
    micr_ok:       hasMicr,
    iqa,
    path:          hasMicr ? 'CR120' : 'LEGACY',
    outcome,
    lot_id:        `LOT-${String(Math.floor(idx / 25) + 1).padStart(4, '0')}`,
    ts:            new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    front_bw_url:  null,
    back_bw_url:   null,
    front_gray_url: null,
  }
}

function mkAuditEvent(idx, bankId) {
  const keys = ['CTS_OUT_LOT_INSTRUMENT_ADDED','CTS_OUT_SCAN_ACCEPTED','CTS_OUT_MISMATCH_HELD','CTS_OUT_CTS2010_FAIL','CTS_OUT_LOT_SEALED']
  const key = keys[idx % keys.length]
  const entry = MSG_TAXONOMY.find(m => m.key === key)
  return {
    id:  `EVT-${idx}`,
    key,
    sev: entry?.sev ?? 'INFO',
    ts:  new Date(Date.now() - idx * 18000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    msg: (entry?.text ?? '')
      .replace('{instrument_id}', `INS-SCAN-20260720-MUM-${String(idx + 1).padStart(5, '0')}`)
      .replace('{lot_id}',        `LOT-${String(Math.floor(idx / 25) + 1).padStart(4, '0')}`)
      .replace('{scan_id}',       `SCAN-20260720-MUM-${String(idx + 1).padStart(5, '0')}`)
      .replace('{instrument_count}', '25')
      .replace('{workflow_id}',   `cts-outscan-${bankId}-SCAN-001`)
      .replace('{path}',          'CR120')
      .replace('{failure_reason}','IQA_BELOW_THRESHOLD')
      .replace('{review_reason}', 'ALTERATION_DETECTED'),
  }
}

function mkLot(i) {
  const statuses = ['OPEN','OPEN','SEALED','SUBMITTED']
  const status = statuses[i % statuses.length]
  return {
    lot_id:    `LOT-${String(i + 1).padStart(4, '0')}`,
    count:     Math.floor(Math.random() * 25) + 1,
    max:       25,
    status,
    opened_at: new Date(Date.now() - (i + 1) * 600000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
  }
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SeverityBadge({ sev, isDark }) {
  const cls = (isDark ? SEV_D : SEV_L)[sev] ?? (isDark ? SEV_D.INFO : SEV_L.INFO)
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase tracking-wide ${cls}`}>
      {sev}
    </span>
  )
}

function SurfaceChips({ surface }) {
  const MAP = {
    UI:           'bg-blue-500/20 text-blue-300',
    AUDIT:        'bg-violet-500/20 text-violet-300',
    NOTIFICATION: 'bg-amber-500/20 text-amber-300',
  }
  return (
    <div className="flex gap-1 flex-wrap">
      {surface.map(s => (
        <span key={s} className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${MAP[s]}`}>{s}</span>
      ))}
    </div>
  )
}

function OutcomePill({ outcome, isDark }) {
  const D = {
    ACCEPTED:      'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    CTS_REJECTED:  'bg-red-900/40     text-red-300     border-red-700/40',
    MISMATCH_HELD: 'bg-amber-900/40   text-amber-300   border-amber-700/40',
    HUMAN_REVIEW:  'bg-blue-900/40    text-blue-300    border-blue-700/40',
  }
  const L = {
    ACCEPTED:      'bg-emerald-50 text-emerald-700 border-emerald-200',
    CTS_REJECTED:  'bg-red-50     text-red-700     border-red-200',
    MISMATCH_HELD: 'bg-amber-50   text-amber-700   border-amber-200',
    HUMAN_REVIEW:  'bg-blue-50    text-blue-700    border-blue-200',
  }
  const cls = (isDark ? D : L)[outcome] ?? (isDark ? D.ACCEPTED : L.ACCEPTED)
  return <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-semibold ${cls}`}>{outcome.replace('_',' ')}</span>
}

function ScanImagePanel({ scan, isDark, onClose }) {
  const th = {
    panel: isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200',
    head:  isDark ? 'bg-navy-950/60 border-white/8' : 'bg-slate-50 border-slate-200',
    label: isDark ? 'text-slate-500' : 'text-slate-400',
    val:   isDark ? 'text-slate-200' : 'text-slate-800',
  }
  const iqaFront = scan.iqa
  const iqaBack  = +(iqaFront * (0.95 + Math.random() * 0.05)).toFixed(3)
  const micrStr  = `⑆${scan.cheque_no}⑆ ⑆000550050⑆ ⑆****${scan.acct_suffix}⑆`

  return (
    <div className={`flex flex-col border rounded-xl overflow-hidden ${th.panel}`} style={{ width: 400, minWidth: 400 }}>
      <div className={`flex items-center justify-between px-4 py-2.5 border-b shrink-0 ${th.head}`}>
        <div>
          <div className={`text-[10px] ${th.label} uppercase tracking-widest`}>Scan Images · CTS-2010</div>
          <div className={`text-xs font-mono font-medium ${th.val} mt-0.5`}>{scan.scan_id}</div>
        </div>
        <button onClick={onClose} className={`text-lg leading-none ${th.label} hover:opacity-60`}>✕</button>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <ChequeImageViewer
          views={[
            { key: 'BFB', label: 'Front B/W',  url: scan.front_bw_url  ?? null, iqaScore: iqaFront },
            { key: 'BBB', label: 'Back B/W',   url: scan.back_bw_url   ?? null, iqaScore: iqaBack  },
            { key: 'BFG', label: 'Front Gray', url: scan.front_gray_url ?? null, iqaScore: +(iqaFront * 0.98).toFixed(3) },
          ]}
          fields={{ micr: micrStr, date: new Date().toLocaleDateString('en-IN') }}
          isDark={isDark} compact={false} title={scan.scan_id}
        />
        <div className="mt-3 grid grid-cols-2 gap-2">
          {[
            ['Scan ID',    scan.scan_id],
            ['Instrument', scan.instrument_id],
            ['Cheque No.', scan.cheque_no],
            ['Account',    `****${scan.acct_suffix}`],
            ['IQA Score',  String(scan.iqa)],
            ['MICR',       scan.micr_ok ? '✓ Valid' : '✗ Failed'],
            ['Path',       scan.path],
            ['Lot',        scan.lot_id],
            ['Outcome',    scan.outcome],
            ['Time',       scan.ts],
          ].map(([k, v]) => (
            <div key={k}>
              <div className={`text-[9px] uppercase tracking-wider ${th.label}`}>{k}</div>
              <div className={`text-[11px] font-medium mt-0.5 ${
                k === 'MICR'
                  ? (scan.micr_ok ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-red-400' : 'text-red-600'))
                  : k === 'Outcome'
                    ? (scan.outcome === 'ACCEPTED' ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-amber-400' : 'text-amber-600'))
                    : (isDark ? 'text-slate-200' : 'text-slate-800')
              }`}>{v}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function CTSScanner() {
  const { bankId, bankIfsc } = useBankContext()
  const { isDark } = useTheme()

  // Scanner agent config
  const [agentUrl, setAgentUrl]             = useState(SCANNER_AGENT_DEFAULT_URL)
  const [agentConnected, setAgentConnected] = useState(false)
  const [editingConfig, setEditingConfig]   = useState(false)
  const [cfgDraft, setCfgDraft]             = useState({
    agentUrl:        SCANNER_AGENT_DEFAULT_URL,
    sessionPrefix:   'MUM',
    endorsementText: 'ASTRA/CTS/OUTWARD',
    enableImprinter: true,
    enableUV:        false,
    bankIfsc:        bankIfsc ?? '',
  })

  // Session
  const [sessionActive, setSessionActive] = useState(false)
  const [sessionId, setSessionId]         = useState('')
  const [sessionCount, setSessionCount]   = useState(0)

  // Scan feed
  const [scans, setScans]               = useState([])
  const [selectedScan, setSelectedScan] = useState(null)
  const scanIdxRef                      = useRef(0)
  const intervalRef                     = useRef(null)

  // Pipeline KPIs
  const [kpis, setKpis] = useState({ accepted: 0, cts_rejected: 0, mismatch: 0, human_review: 0 })

  // Audit feed
  const [auditEvents, setAuditEvents] = useState(() =>
    Array.from({ length: 8 }, (_, i) => mkAuditEvent(i, bankId ?? 'demo-bank'))
  )
  const auditIdxRef = useRef(8)

  // Lots
  const [lots, setLots] = useState(() => Array.from({ length: 3 }, (_, i) => mkLot(i)))

  // Kafka mock stats
  const [kafkaStats, setKafkaStats] = useState({
    scanned:   { lag: 0, rate: 0 },
    sealed:    { lag: 0, rate: 0 },
    submitted: { lag: 0, rate: 0 },
  })

  // Right panel tab
  const [rightTab, setRightTab] = useState('audit') // 'audit' | 'lots' | 'taxonomy'

  // ── Agent ping ──────────────────────────────────────────────────────────────
  const pingAgent = useCallback(async () => {
    try {
      const r = await fetch(`${agentUrl}/health`, { signal: AbortSignal.timeout(2000) })
      setAgentConnected(r.ok)
    } catch {
      setAgentConnected(false)
    }
  }, [agentUrl])

  useEffect(() => {
    pingAgent()
    const t = setInterval(pingAgent, 10000)
    return () => clearInterval(t)
  }, [pingAgent])

  // ── Session control ─────────────────────────────────────────────────────────
  function startSession() {
    const sid = `SES-${Date.now().toString(36).toUpperCase()}`
    setSessionId(sid)
    setSessionActive(true)
    setKpis({ accepted: 0, cts_rejected: 0, mismatch: 0, human_review: 0 })
    scanIdxRef.current = 0
    setScans([])

    intervalRef.current = setInterval(() => {
      const scan = mkScan(scanIdxRef.current)
      scanIdxRef.current++
      setSessionCount(c => c + 1)
      setScans(prev => [scan, ...prev].slice(0, 60))
      setKpis(prev => ({
        accepted:     prev.accepted     + (scan.outcome === 'ACCEPTED'      ? 1 : 0),
        cts_rejected: prev.cts_rejected + (scan.outcome === 'CTS_REJECTED'  ? 1 : 0),
        mismatch:     prev.mismatch     + (scan.outcome === 'MISMATCH_HELD' ? 1 : 0),
        human_review: prev.human_review + (scan.outcome === 'HUMAN_REVIEW'  ? 1 : 0),
      }))

      // Audit feed
      const ae = mkAuditEvent(auditIdxRef.current, bankId ?? 'demo-bank')
      auditIdxRef.current++
      setAuditEvents(prev => [ae, ...prev].slice(0, 20))

      // Kafka lag simulation
      setKafkaStats({
        scanned:   { lag: Math.max(0, Math.floor(Math.random() * 3)), rate: +(0.7  + Math.random() * 0.4 ).toFixed(1) },
        sealed:    { lag: 0,                                           rate: +(0.03 + Math.random() * 0.04).toFixed(2) },
        submitted: { lag: 0,                                           rate: +(0.02 + Math.random() * 0.03).toFixed(2) },
      })

      // Lot fill simulation
      setLots(prev => {
        const updated = [...prev]
        const openIdx = updated.findIndex(l => l.status === 'OPEN')
        if (openIdx >= 0) {
          const filled = { ...updated[openIdx], count: updated[openIdx].count + 1 }
          if (filled.count >= filled.max) {
            updated[openIdx] = { ...filled, status: 'SEALED' }
            return [...updated, { ...mkLot(updated.length), status: 'OPEN', count: 0 }]
          }
          updated[openIdx] = filled
        }
        return updated
      })
    }, 1800)
  }

  function stopSession() {
    setSessionActive(false)
    clearInterval(intervalRef.current)
  }

  useEffect(() => () => clearInterval(intervalRef.current), [])

  function saveConfig() {
    setAgentUrl(cfgDraft.agentUrl)
    setEditingConfig(false)
  }

  // ── Theme ───────────────────────────────────────────────────────────────────
  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    rowSel:  isDark ? 'bg-white/5 border-white/10' : 'bg-amber-50 border-amber-200',
    input:   isDark
      ? 'bg-navy-950 border-white/12 text-white placeholder-slate-600'
      : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400',
    tab: (active) => active
      ? (isDark ? 'bg-white/10 text-white' : 'bg-slate-900 text-white')
      : (isDark ? 'text-slate-400 hover:text-white' : 'text-slate-500 hover:text-slate-800'),
  }

  const micrOk   = scans.filter(s => s.micr_ok).length
  const micrFail  = scans.filter(s => !s.micr_ok).length
  const avgIqa   = scans.length ? (scans.reduce((a, s) => a + s.iqa, 0) / scans.length).toFixed(3) : '—'

  usePageHeader({
    subtitle: 'CR-120 · Ranger API bridge — configure, monitor, and audit outward scan sessions',
    actions: (
      <div className="flex items-center gap-3">
        <button
          onClick={() => { setEditingConfig(v => !v); setCfgDraft(d => ({ ...d, agentUrl })) }}
          className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors ${isDark ? 'border-white/12 text-slate-300 hover:bg-white/5' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}
        >
          Configure
        </button>
        <button
          onClick={sessionActive ? stopSession : startSession}
          className={`flex items-center gap-2 text-xs rounded-lg px-4 py-2 font-medium transition-colors ${
            sessionActive ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-emerald-600 hover:bg-emerald-500 text-white'
          }`}
        >
          <span className={`w-2 h-2 rounded-full bg-white ${sessionActive ? 'animate-pulse' : ''}`} />
          {sessionActive ? 'Stop Session' : 'Start Session'}
        </button>
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5 min-h-full flex flex-col gap-4`}>

        {/* ── Scanner Agent Status bar ───────────────────────────────────── */}
        <div className={`border rounded-xl px-4 py-3 flex items-center justify-between ${th.card}`}>
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${agentConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
              <span className={`text-xs font-medium ${th.heading}`}>Scanner Agent</span>
              <span className={`text-[11px] font-mono ${th.muted}`}>{agentUrl}</span>
              <span className={`text-[10px] font-medium ${agentConnected ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-red-400' : 'text-red-600')}`}>
                {agentConnected ? 'CONNECTED' : 'OFFLINE'}
              </span>
            </div>
            {sessionActive && (
              <div className="flex items-center gap-4 border-l pl-6" style={{ borderColor: isDark ? 'rgba(255,255,255,0.08)' : '#e2e8f0' }}>
                <div>
                  <span className={`text-[10px] ${th.faint}`}>Session</span>
                  <span className={`ml-2 text-[11px] font-mono font-medium ${th.body}`}>{sessionId}</span>
                </div>
                <div>
                  <span className={`text-[10px] ${th.faint}`}>Scanned</span>
                  <span className={`ml-2 text-sm font-bold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>{sessionCount}</span>
                </div>
                <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                  <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                  LIVE
                </span>
              </div>
            )}
          </div>
          <span className={`text-[10px] ${th.faint}`}>
            GET {agentUrl}/health · POST {agentUrl}/session/start|stop
          </span>
        </div>

        {/* ── Config panel (collapsible) ─────────────────────────────────── */}
        {editingConfig && (
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-sm font-semibold ${th.heading} mb-4`}>Scanner Agent Configuration</div>
            <div className="grid grid-cols-3 gap-4 mb-4">
              {[
                { label: 'Agent URL',        key: 'agentUrl',        placeholder: 'http://localhost:9201' },
                { label: 'Bank IFSC',        key: 'bankIfsc',        placeholder: 'SVCB0000001' },
                { label: 'Session Prefix',   key: 'sessionPrefix',   placeholder: 'MUM' },
                { label: 'Endorsement Text', key: 'endorsementText', placeholder: 'ASTRA/CTS/OUTWARD' },
              ].map(f => (
                <div key={f.key}>
                  <label className={`text-[10px] uppercase tracking-wider ${th.faint} mb-1 block`}>{f.label}</label>
                  <input
                    type="text"
                    value={cfgDraft[f.key]}
                    onChange={e => setCfgDraft(d => ({ ...d, [f.key]: e.target.value }))}
                    placeholder={f.placeholder}
                    className={`w-full text-xs px-3 py-2 rounded-lg border outline-none focus:ring-1 focus:ring-violet-500 ${th.input}`}
                  />
                </div>
              ))}
              <div>
                <label className={`text-[10px] uppercase tracking-wider ${th.faint} mb-1 block`}>API Token (Vault-managed)</label>
                <input type="password" value="••••••••••••••••" readOnly
                  className={`w-full text-xs px-3 py-2 rounded-lg border outline-none ${th.input} opacity-60 cursor-not-allowed`} />
              </div>
            </div>
            <div className="flex items-center gap-6 mb-4">
              {[
                { key: 'enableImprinter', label: 'Enable Imprinter (endorsement stamp)' },
                { key: 'enableUV',        label: 'Enable UV Scan (CR-120 UV model only)' },
              ].map(f => (
                <label key={f.key} className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={cfgDraft[f.key]}
                    onChange={e => setCfgDraft(d => ({ ...d, [f.key]: e.target.checked }))}
                    className="rounded" />
                  <span className={`text-xs ${th.body}`}>{f.label}</span>
                </label>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <button onClick={saveConfig}
                className="text-xs px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white font-medium">
                Save &amp; Apply
              </button>
              <button onClick={() => setEditingConfig(false)}
                className={`text-xs px-4 py-2 rounded-lg border font-medium ${isDark ? 'border-white/12 text-slate-400 hover:bg-white/5' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}>
                Cancel
              </button>
              <span className={`text-[10px] ${th.faint} ml-2`}>
                Token is Vault-managed — change via Admin UI (Layer 5). Other settings take effect at next session start.
              </span>
            </div>
          </div>
        )}

        {/* ── Pipeline KPI strip ────────────────────────────────────────────── */}
        <div className="grid grid-cols-8 gap-3">
          {[
            { label: 'Accepted',      value: kpis.accepted,      color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'CTS Rejected',  value: kpis.cts_rejected,  color: isDark ? 'text-red-400'     : 'text-red-600'     },
            { label: 'Mismatch Held', value: kpis.mismatch,      color: isDark ? 'text-amber-400'   : 'text-amber-600'   },
            { label: 'Human Review',  value: kpis.human_review,  color: isDark ? 'text-blue-400'    : 'text-blue-600'    },
            { label: 'MICR OK',       value: micrOk,             color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
            { label: 'MICR Fail',     value: micrFail,           color: micrFail > 0 ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-slate-400' : 'text-slate-500') },
            { label: 'Avg IQA',       value: avgIqa,             color: isDark ? 'text-violet-400'  : 'text-violet-600'  },
            { label: 'Lots Active',   value: lots.filter(l => l.status === 'OPEN').length, color: isDark ? 'text-amber-400' : 'text-amber-600' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-3 py-2.5 ${th.card}`}>
              <div className={`text-[9px] ${th.faint} mb-1 uppercase tracking-wider`}>{k.label}</div>
              <div className={`text-xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* ── Kafka Topics ───────────────────────────────────────────────────── */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-medium ${th.heading}`}>Kafka Topics — Outward Clearing</span>
            <span className={`text-[10px] ${th.faint}`}>bank_id: {bankId ?? 'demo-bank'} · redis-cts cluster (isolated from redis-ej)</span>
          </div>
          <div className="grid grid-cols-3 divide-x" style={{ borderColor: isDark ? 'rgba(255,255,255,0.08)' : '#e2e8f0' }}>
            {KAFKA_TOPICS(bankId ?? 'demo-bank').map(t => {
              const stat = kafkaStats[t.label]
              const lagColor = (stat?.lag ?? 0) > 10
                ? (isDark ? 'text-red-400' : 'text-red-600')
                : (stat?.lag ?? 0) > 0
                  ? (isDark ? 'text-amber-400' : 'text-amber-600')
                  : (isDark ? 'text-emerald-400' : 'text-emerald-600')
              const TOPIC_COLOR = {
                violet:  isDark ? 'text-violet-400' : 'text-violet-600',
                amber:   isDark ? 'text-amber-400'  : 'text-amber-600',
                emerald: isDark ? 'text-emerald-400': 'text-emerald-600',
              }
              return (
                <div key={t.topic} className="px-4 py-3">
                  <div className={`text-[10px] font-semibold ${TOPIC_COLOR[t.color]} mb-0.5`}>{t.display}</div>
                  <div className={`text-[10px] font-mono ${th.faint} mb-2 truncate`}>{t.topic}</div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <div className={`text-[9px] ${th.faint}`}>Consumer Lag</div>
                      <div className={`text-sm font-bold ${lagColor}`}>{stat?.lag ?? 0}</div>
                    </div>
                    <div>
                      <div className={`text-[9px] ${th.faint}`}>msg/s</div>
                      <div className={`text-sm font-bold ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{stat?.rate ?? 0}</div>
                    </div>
                  </div>
                  <div className={`text-[9px] ${th.faint} mt-1`}>{t.desc}</div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Main split: Scan Feed | Right column ──────────────────────────── */}
        <div className="flex gap-4 items-start">

          {/* Scan Feed */}
          <div className={`flex-1 min-w-0 border rounded-xl overflow-hidden ${th.card}`}>
            <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
              <span className={`text-sm font-medium ${th.heading}`}>Live Scan Feed</span>
              <div className="flex items-center gap-3">
                {selectedScan && (
                  <span className={`text-[10px] ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>← click row to view images</span>
                )}
                {sessionActive && (
                  <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                    <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                    LIVE
                  </span>
                )}
              </div>
            </div>

            {/* Column headers */}
            <div className={`grid grid-cols-12 gap-1 px-4 py-2 border-b ${th.divider} text-[9px] ${th.faint} font-medium uppercase tracking-wider`}>
              <div className="col-span-3">Scan ID</div>
              <div className="col-span-2">Cheque / Acct</div>
              <div className="col-span-1 text-center">MICR</div>
              <div className="col-span-1 text-center">IQA</div>
              <div className="col-span-1 text-center">Path</div>
              <div className="col-span-2">Outcome</div>
              <div className="col-span-1">Lot</div>
              <div className="col-span-1 text-right">Time</div>
            </div>

            {scans.length === 0 && (
              <div className={`px-4 py-10 text-center text-sm ${th.muted}`}>
                Press <strong>Start Session</strong> to begin live scanning.
              </div>
            )}

            {scans.map(scan => {
              const sel = selectedScan?.scan_id === scan.scan_id
              return (
                <div key={scan.scan_id}
                  onClick={() => setSelectedScan(sel ? null : scan)}
                  className={`grid grid-cols-12 gap-1 px-4 py-2 border-b cursor-pointer transition-colors text-xs ${sel ? th.rowSel : th.row}`}
                >
                  <div className={`col-span-3 font-mono text-[10px] ${isDark ? 'text-slate-300' : 'text-slate-600'} truncate`}>{scan.scan_id}</div>
                  <div className={`col-span-2 ${th.muted}`}>
                    <div>{scan.cheque_no}</div>
                    <div className={`text-[10px] ${th.faint}`}>****{scan.acct_suffix}</div>
                  </div>
                  <div className={`col-span-1 text-center font-medium ${scan.micr_ok ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-red-400' : 'text-red-600')}`}>
                    {scan.micr_ok ? '✓' : '✗'}
                  </div>
                  <div className={`col-span-1 text-center text-[10px] ${scan.iqa >= 0.90 ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : scan.iqa >= 0.70 ? (isDark ? 'text-amber-400' : 'text-amber-600') : (isDark ? 'text-red-400' : 'text-red-600')}`}>
                    {scan.iqa}
                  </div>
                  <div className={`col-span-1 text-[10px] font-medium ${scan.path === 'CR120' ? (isDark ? 'text-violet-400' : 'text-violet-600') : th.faint}`}>{scan.path}</div>
                  <div className="col-span-2"><OutcomePill outcome={scan.outcome} isDark={isDark} /></div>
                  <div className={`col-span-1 text-[10px] font-mono ${th.faint}`}>{scan.lot_id}</div>
                  <div className={`col-span-1 text-right text-[10px] ${th.faint}`}>{scan.ts}</div>
                </div>
              )
            })}
          </div>

          {/* Right column — Audit | Lots | Taxonomy (hidden when image panel open) */}
          {!selectedScan && (
            <div className={`border rounded-xl overflow-hidden ${th.card}`} style={{ width: 380, minWidth: 380 }}>
              <div className={`flex border-b ${th.divider}`}>
                {[
                  { id: 'audit',    label: 'Audit Events' },
                  { id: 'lots',     label: 'Lots' },
                  { id: 'taxonomy', label: 'Msg Taxonomy' },
                ].map(t => (
                  <button key={t.id} onClick={() => setRightTab(t.id)}
                    className={`flex-1 text-xs py-2.5 font-medium transition-colors ${th.tab(rightTab === t.id)}`}>
                    {t.label}
                  </button>
                ))}
              </div>

              {/* Audit Events tab */}
              {rightTab === 'audit' && (
                <div className="overflow-y-auto" style={{ maxHeight: 440 }}>
                  {auditEvents.map(e => (
                    <div key={e.id} className={`px-3 py-2.5 border-b ${th.divider} ${th.row}`}>
                      <div className="flex items-center justify-between mb-1">
                        <span className={`text-[9px] font-mono ${th.faint}`}>{e.key}</span>
                        <div className="flex items-center gap-1.5">
                          <SeverityBadge sev={e.sev} isDark={isDark} />
                          <span className={`text-[9px] ${th.faint}`}>{e.ts}</span>
                        </div>
                      </div>
                      <div className={`text-[10px] ${th.body} leading-relaxed`}>{e.msg}</div>
                      <div className={`text-[9px] ${th.faint} mt-0.5`}>→ Immudb collection: cts_events · platform.audit.events</div>
                    </div>
                  ))}
                  {auditEvents.length === 0 && (
                    <div className={`py-8 text-center text-sm ${th.muted}`}>No audit events yet</div>
                  )}
                </div>
              )}

              {/* Lots tab */}
              {rightTab === 'lots' && (
                <div className="overflow-y-auto" style={{ maxHeight: 440 }}>
                  <div className={`px-3 py-1.5 border-b ${th.divider} grid grid-cols-5 gap-1 text-[9px] ${th.faint} uppercase tracking-wider font-medium`}>
                    <div className="col-span-2">Lot ID</div>
                    <div className="col-span-1 text-center">Items</div>
                    <div className="col-span-1">Status</div>
                    <div className="col-span-1 text-right">Opened</div>
                  </div>
                  {lots.map(l => {
                    const pct = Math.min(100, Math.round((l.count / l.max) * 100))
                    const statusCls = {
                      OPEN:      isDark ? 'text-emerald-400' : 'text-emerald-600',
                      SEALED:    isDark ? 'text-amber-400'   : 'text-amber-600',
                      SUBMITTED: isDark ? 'text-violet-400'  : 'text-violet-600',
                    }[l.status]
                    return (
                      <div key={l.lot_id} className={`px-3 py-2 border-b ${th.divider} ${th.row}`}>
                        <div className="grid grid-cols-5 gap-1 text-[10px] mb-1">
                          <div className={`col-span-2 font-mono font-medium ${th.body}`}>{l.lot_id}</div>
                          <div className={`col-span-1 text-center ${th.body}`}>{l.count}/{l.max}</div>
                          <div className={`col-span-1 font-medium ${statusCls}`}>{l.status}</div>
                          <div className={`col-span-1 text-right ${th.faint}`}>{l.opened_at}</div>
                        </div>
                        {l.status === 'OPEN' && (
                          <div className={`h-1 rounded-full ${isDark ? 'bg-white/8' : 'bg-slate-200'}`}>
                            <div className="h-1 rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
                          </div>
                        )}
                      </div>
                    )
                  })}
                  <div className={`px-3 py-2 text-[9px] ${th.faint}`}>
                    Redis key: lot:{bankId ?? 'demo-bank'}:* · Lot max: 25 (Layer 3 config, hot-reload)
                  </div>
                </div>
              )}

              {/* Message Taxonomy tab */}
              {rightTab === 'taxonomy' && (
                <div className="overflow-y-auto" style={{ maxHeight: 440 }}>
                  {MSG_TAXONOMY.map(m => (
                    <div key={m.key} className={`px-3 py-2.5 border-b ${th.divider} ${th.row}`}>
                      <div className="flex items-center justify-between mb-1">
                        <span className={`text-[9px] font-mono font-semibold ${th.body}`}>{m.key}</span>
                        <SeverityBadge sev={m.sev} isDark={isDark} />
                      </div>
                      <div className={`text-[10px] ${th.muted} mb-1.5 leading-relaxed`}>{m.text}</div>
                      <SurfaceChips surface={m.surface} />
                    </div>
                  ))}
                  <div className={`px-3 py-2 text-[9px] ${th.faint}`}>
                    Source: shared/messages/locales/messages.yaml · build: python -m shared.messages.build
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Image panel — replaces right column when scan row clicked */}
          {selectedScan && (
            <ScanImagePanel scan={selectedScan} isDark={isDark} onClose={() => setSelectedScan(null)} />
          )}
        </div>

        {/* ── SDK / Integration Reference ────────────────────────────────────── */}
        <div className={`border rounded-xl p-4 ${th.card}`}>
          <div className={`text-xs font-semibold ${th.heading} mb-3`}>SDK Integration Reference</div>
          <div className="grid grid-cols-4 gap-4 mb-3">
            {[
              { label: 'Canon CR-120',     detail: 'Ranger Transport API · C SDK via cgo bridge',               path: 'edge/cts-scanner-agent/ranger_windows.go',          note: 'Hardware MICR + duplex TIFF · triggers CR120 path' },
              { label: 'Scanner Agent',    detail: 'Go binary · Windows service · localhost:9201',               path: 'edge/cts-scanner-agent/',                           note: 'GET /health · POST /session/start|stop · GET /session/status' },
              { label: 'MinIO Upload',     detail: 'Pre-signed URL · PUT image/tiff from agent',                 path: 'POST /v1/cts/outward/scan/upload-url',              note: 'Agent never holds MinIO credentials — ASTRA issues per-scan URL' },
              { label: 'Outward Workflow', detail: 'OutwardScanWorkflow forks on micr_hardware_raw presence',    path: 'modules/cts/workflows/outward_scan_workflow.py',    note: 'GOT-OCR2 skipped on CR120 path · single Qwen2-VL call' },
            ].map(s => (
              <div key={s.label}>
                <div className={`text-xs font-semibold ${th.heading}`}>{s.label}</div>
                <div className={`text-[10px] ${th.muted} mt-0.5`}>{s.detail}</div>
                <div className={`text-[10px] font-mono ${th.faint} mt-1`}>{s.path}</div>
                <div className={`text-[10px] ${th.faint}`}>{s.note}</div>
              </div>
            ))}
          </div>
          <div className={`pt-3 border-t ${th.divider} text-[10px] ${th.faint}`}>
            <span className="font-mono">cts.outward.scanned.{bankId ?? '{bank_id}'}</span>
            {' → '}
            <span className="font-mono">cts.outward.lot.sealed.{bankId ?? '{bank_id}'}</span>
            {' → '}
            <span className="font-mono">cts.outward.submitted.{bankId ?? '{bank_id}'}</span>
            {' · Redis: '}
            <span className="font-mono">redis-cts</span>
            {' (isolated from redis-ej per blast isolation rules)'}
            {' · Audit → Immudb collection: '}
            <span className="font-mono">cts_events</span>
          </div>
        </div>

      </div>
    </AppShell>
  )
}
