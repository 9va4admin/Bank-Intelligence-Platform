/**
 * CTS Discrepancy / Exception Report page.
 * Displays per-session exceptions with severity grouping and CSV download.
 * Exception types: IQA Fail, IET Near-Breach, Vault Miss, NGCH Reject,
 *                  Human Review, Words/Figures Mismatch, Alteration Detected,
 *                  OCR Low Confidence, Signature Low Confidence, Fraud High Score.
 */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { MOCK_QUEUE } from '../data/mockQueue'
import { msg } from '../../../shared/messages'

const _API_BASE = import.meta.env.VITE_API_BASE ?? ''

function useExceptions({ pollEnabled }) {
  const [items, setItems] = useState(null)
  const timerRef = useRef(null)
  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${_API_BASE}/v1/cts/exceptions?limit=200`, { credentials: 'include' })
      if (!res.ok) throw new Error(msg('UI_COMMON_HTTP', { status: res.status }))
      const json = await res.json()
      setItems(json.items ?? [])
    } catch { /* keep last */ }
  }, [])
  useEffect(() => {
    if (!pollEnabled) return
    fetch_()
    timerRef.current = setInterval(fetch_, 2 * 60_000)
    return () => clearInterval(timerRef.current)
  }, [fetch_, pollEnabled])
  return items
}

// ── Exception data ────────────────────────────────────────────────────────

function makeSessionMeta(bankIfsc, isSMB) {
  const ifsc = bankIfsc || 'BANK'
  return {
    session_id:      `SES-${ifsc}-20260619-001`,
    clearing_date:   '2026-06-19',
    generated_at:    '2026-06-19T14:30:00Z',
    total_processed: isSMB ? 8 : 47,
  }
}

const SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM']

const EXCEPTIONS = [
  {
    id: 'EX-001',
    instrument_id: 'CHQ-IN-001994',
    exception_type: 'IET_NEAR_BREACH',
    label: msg('UI_EXCEPTIONS_IET_NEAR_BREACH_30S_MARGIN'),
    severity: 'CRITICAL',
    occurred_at: '2026-06-19T13:29:35Z',
    detail: msg('UI_EXCEPTIONS_FILED_25_S_BEFORE_IET'),
    resolved: true,
    margin_seconds: 25,
  },
  {
    id: 'EX-002',
    instrument_id: 'CHQ-IN-001982',
    exception_type: 'NGCH_REJECT',
    label: msg('UI_EXCEPTIONS_NGCH_FILING_REJECTED_RETRIED'),
    severity: 'CRITICAL',
    occurred_at: '2026-06-19T11:42:18Z',
    detail: msg('UI_EXCEPTIONS_NGCH_RETURNED_HTTP_503_AUTO'),
    resolved: true,
    margin_seconds: null,
  },
  {
    id: 'EX-003',
    instrument_id: 'CHQ-IN-001947',
    exception_type: 'IQA_FAIL',
    label: msg('UI_EXCEPTIONS_IMAGE_QUALITY_FAILURE'),
    severity: 'HIGH',
    occurred_at: '2026-06-19T10:14:22Z',
    detail: msg('UI_EXCEPTIONS_FRONT_IMAGE_JPEG_COMPRESSION_ARTEFAC'),
    resolved: true,
    margin_seconds: null,
  },
  {
    id: 'EX-004',
    instrument_id: 'CHQ-IN-001958',
    exception_type: 'VAULT_MISS',
    label: msg('UI_EXCEPTIONS_SIGNATURE_PPS_VAULT_MISS'),
    severity: 'HIGH',
    occurred_at: '2026-06-19T10:31:05Z',
    detail: msg('UI_EXCEPTIONS_NO_SIGNATURE_SPECIMEN_ON_FILE'),
    resolved: true,
    margin_seconds: null,
  },
  {
    id: 'EX-005',
    instrument_id: 'CHQ-IN-001963',
    exception_type: 'WORDS_FIGURES_MISMATCH',
    label: msg('UI_EXCEPTIONS_WORDS_FIGURES_AMOUNT_DIFFER'),
    severity: 'HIGH',
    occurred_at: '2026-06-19T10:55:44Z',
    detail: msg('UI_EXCEPTIONS_FIGURES_1_25_000_WORDS'),
    resolved: false,
    margin_seconds: null,
  },
  {
    id: 'EX-006',
    instrument_id: 'CHQ-IN-001971',
    exception_type: 'ALTERATION_DETECTED',
    label: msg('UI_EXCEPTIONS_POSSIBLE_ALTERATION_DETECTED'),
    severity: 'HIGH',
    occurred_at: '2026-06-19T11:08:33Z',
    detail: msg('UI_EXCEPTIONS_QWEN2_VL_CONFIDENCE_0_91'),
    resolved: false,
    margin_seconds: null,
  },
  {
    id: 'EX-007',
    instrument_id: 'CHQ-IN-001975',
    exception_type: 'FRAUD_HIGH_SCORE',
    label: msg('UI_EXCEPTIONS_FRAUD_SCORE_ABOVE_THRESHOLD'),
    severity: 'HIGH',
    occurred_at: '2026-06-19T11:19:55Z',
    detail: msg('UI_EXCEPTIONS_XGBOOST_FRAUD_SCORE_0_81'),
    resolved: true,
    margin_seconds: null,
  },
  {
    id: 'EX-008',
    instrument_id: 'CHQ-IN-001931',
    exception_type: 'OCR_LOW_CONFIDENCE',
    label: msg('UI_EXCEPTIONS_OCR_CONFIDENCE_BELOW_THRESHOLD'),
    severity: 'MEDIUM',
    occurred_at: '2026-06-19T10:02:11Z',
    detail: msg('UI_EXCEPTIONS_GOT_OCR2_MICR_LINE_CONFIDENCE'),
    resolved: true,
    margin_seconds: null,
  },
  {
    id: 'EX-009',
    instrument_id: 'CHQ-IN-001935',
    exception_type: 'SIGNATURE_LOW_CONF',
    label: msg('UI_EXCEPTIONS_SIGNATURE_MATCH_LOW_CONFIDENCE'),
    severity: 'MEDIUM',
    occurred_at: '2026-06-19T10:07:47Z',
    detail: msg('UI_EXCEPTIONS_SIAMESE_NET_MATCH_SCORE_0'),
    resolved: true,
    margin_seconds: null,
  },
  {
    id: 'EX-010',
    instrument_id: 'CHQ-IN-001989',
    exception_type: 'HUMAN_REVIEW',
    label: msg('UI_EXCEPTIONS_ESCALATED_TO_HUMAN_REVIEW'),
    severity: 'MEDIUM',
    occurred_at: '2026-06-19T12:05:22Z',
    detail: msg('UI_EXCEPTIONS_MULTIPLE_LOW_CONFIDENCE_SIGNALS_COMP'),
    resolved: false,
    margin_seconds: null,
  },
]

// ── CSV generation (mirrors Python DiscrepancyExporter.to_csv) ───────────

function buildCsv(exceptions, meta) {
  const lines = []
  lines.push(['# CTS Discrepancy / Exception Report'])
  lines.push(['# Bank IFSC', meta.bank_ifsc])
  lines.push(['# Session ID', meta.session_id])
  lines.push(['# Clearing Date', meta.clearing_date])
  lines.push(['# Generated At', meta.generated_at])
  lines.push(['# Total Instruments', meta.total_processed])
  lines.push(['# Total Exceptions', exceptions.length])
  lines.push(['# Unresolved', exceptions.filter(e => !e.resolved).length])
  lines.push([])
  lines.push(['InstrumentID', 'ExceptionType', 'Label', 'Severity',
              'OccurredAt', 'Detail', 'Resolved', 'MarginSeconds'])
  for (const e of exceptions) {
    lines.push([
      e.instrument_id,
      e.exception_type,
      e.label,
      e.severity,
      e.occurred_at,
      e.detail,
      e.resolved ? 'Yes' : 'No',
      e.margin_seconds ?? '',
    ])
  }
  return lines.map(row => row.map(cell =>
    String(cell).includes(',') ? `"${String(cell).replace(/"/g, '""')}"` : cell
  ).join(',')).join('\n')
}

function downloadCsv(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── D4: Predictive risk signals derived from live queue ───────────────────

function buildPredictiveSignals(queue) {
  const now = Date.now()
  const ietRisk = queue.filter(item => {
    const minsLeft = (new Date(item.iet_deadline) - now) / 60000
    return minsLeft < 60
  })
  const vaultMisses = queue.filter(i => i.reason === 'VAULT_MISS')
  const fraudCluster = queue.filter(i => i.fraud_score >= 0.78)
  const subMemberItems = queue.filter(i => i.principal_tag === 'SUB_MEMBER')
  const avgFraud = queue.length ? (queue.reduce((a, i) => a + i.fraud_score, 0) / queue.length) : 0
  return { ietRisk, vaultMisses, fraudCluster, subMemberItems, avgFraud }
}

// ── Component ─────────────────────────────────────────────────────────────

export default function CTSExceptions() {
  const { bankIfsc, bankName, isSB, isSMB, isDemo } = useBankContext()
  const SESSION_META = { ...makeSessionMeta(bankIfsc, isSMB), bank_ifsc: bankIfsc, bank_name: bankName }
  const { isDark } = useTheme()
  const [severityFilter, setSeverityFilter] = useState('All')
  const [showResolved, setShowResolved]     = useState(true)

  const liveExceptions = useExceptions({ pollEnabled: !isDemo })

  const ALL_EXCEPTIONS = useMemo(() => {
    if (isDemo) return EXCEPTIONS
    if (!liveExceptions || liveExceptions.length === 0) return []
    return liveExceptions
  }, [isDemo, liveExceptions])

  const predictive = buildPredictiveSignals(isDemo ? MOCK_QUEUE.filter(i => i.status === 'PENDING') : [])

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    faint:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    select:  isDark ? 'bg-navy-900 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    input:   isDark ? 'bg-navy-800 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    badge:   isDark ? 'bg-white/10 text-slate-300' : 'bg-slate-100 text-slate-600',
  }

  const SEV_D = {
    CRITICAL: 'bg-red-900/60 text-red-300 border border-red-700/50',
    HIGH:     'bg-amber-900/50 text-amber-300 border border-amber-700/40',
    MEDIUM:   'bg-sky-900/50 text-sky-300 border border-sky-700/40',
  }
  const SEV_L = {
    CRITICAL: 'bg-red-100 text-red-700 border border-red-300',
    HIGH:     'bg-amber-100 text-amber-700 border border-amber-300',
    MEDIUM:   'bg-sky-100 text-sky-700 border border-sky-300',
  }
  const SEV = isDark ? SEV_D : SEV_L

  const filtered = ALL_EXCEPTIONS.filter(e => {
    if (severityFilter !== 'All' && e.severity !== severityFilter) return false
    if (!showResolved && e.resolved) return false
    return true
  })

  const counts = {
    CRITICAL: ALL_EXCEPTIONS.filter(e => e.severity === 'CRITICAL').length,
    HIGH:     ALL_EXCEPTIONS.filter(e => e.severity === 'HIGH').length,
    MEDIUM:   ALL_EXCEPTIONS.filter(e => e.severity === 'MEDIUM').length,
  }
  const unresolvedCount = ALL_EXCEPTIONS.filter(e => !e.resolved).length

  function handleDownload() {
    const csv = buildCsv(ALL_EXCEPTIONS, SESSION_META)
    const fname = `DISC_${SESSION_META.bank_ifsc}_${SESSION_META.clearing_date.replace(/-/g,'')}_${SESSION_META.session_id}.csv`
    downloadCsv(csv, fname)
  }

  usePageHeader({
    subtitle: msg('UI_EXCEPTIONS_SESSION', { bank_name: SESSION_META.bank_name, session_id: SESSION_META.session_id, clearing_date: SESSION_META.clearing_date }),
    actions: (
      <button
        onClick={handleDownload}
        className="flex items-center gap-2 px-3 py-1.5 rounded text-sm font-medium bg-violet-600 hover:bg-violet-500 text-white"
      >
       {msg('UI_EXCEPTIONS_DOWNLOAD_CSV')}
      </button>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5 space-y-5`}>

        {/* D4: Predictive Risk Signals */}
        <div className={`border rounded-lg p-4 ${th.card}`}>
          <div className="flex items-center gap-2 mb-3">
            <span className={`text-xs font-semibold ${th.heading}`}>{msg('UI_EXCEPTIONS_PREDICTIVE_RISK_SIGNALS')}</span>
            <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-400 border border-violet-400/20 uppercase tracking-wide">{msg('UI_EXCEPTIONS_LIVE_QUEUE')}</span>
            <span className={`text-[10px] ${th.muted} ml-auto`}>{msg('UI_EXCEPTIONS_BASED_ON_PENDING_ITEMS', { count: MOCK_QUEUE.length })}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              {
                label: msg('UI_EXCEPTIONS_IET_RISK_60_MIN'),
                value: predictive.ietRisk.length,
                sub: predictive.ietRisk.length > 0 ? predictive.ietRisk.map(i => i.instrument_id).join(', ') : msg('UI_EXCEPTIONS_ALL_CLEAR'),
                color: predictive.ietRisk.length > 0 ? 'text-red-400' : 'text-emerald-400',
                bg: predictive.ietRisk.length > 0 ? 'border-red-400/20 bg-red-400/3' : 'border-emerald-400/10',
                icon: '⏱',
              },
              {
                label: msg('UI_ANALYTICS_VAULT_MISSES'),
                value: predictive.vaultMisses.length,
                sub: predictive.vaultMisses.length > 0 ? msg('UI_EXCEPTIONS_AUTO_RETURN_BLOCKED_HUMAN_REQUIRED') : msg('UI_EXCEPTIONS_NO_VAULT_MISSES'),
                color: predictive.vaultMisses.length > 0 ? 'text-purple-400' : 'text-emerald-400',
                bg: predictive.vaultMisses.length > 0 ? 'border-purple-400/20 bg-purple-400/3' : 'border-emerald-400/10',
                icon: '🔐',
              },
              {
                label: msg('UI_EXCEPTIONS_FRAUD_CLUSTER_78'),
                value: predictive.fraudCluster.length,
                sub: predictive.fraudCluster.length > 0 ? msg('UI_EXCEPTIONS_AVG_QUEUE_FRAUD', { value: Math.round(predictive.avgFraud * 100) }) : msg('UI_EXCEPTIONS_WITHIN_THRESHOLD'),
                color: predictive.fraudCluster.length >= 3 ? 'text-red-400' : predictive.fraudCluster.length > 0 ? 'text-amber-400' : 'text-emerald-400',
                bg: predictive.fraudCluster.length >= 3 ? 'border-red-400/20 bg-red-400/3' : 'border-amber-400/10',
                icon: '🛡',
              },
              {
                label: msg('UI_EXCEPTIONS_SUB_MEMBER_ITEMS'),
                value: predictive.subMemberItems.length,
                sub: predictive.subMemberItems.length > 0 ? msg('UI_EXCEPTIONS_SPONSOR_BANK_NOTIFICATION_ON_RETURN') : msg('UI_EXCEPTIONS_NONE_IN_QUEUE'),
                color: predictive.subMemberItems.length > 0 ? 'text-amber-400' : 'text-slate-400',
                bg: predictive.subMemberItems.length > 0 ? 'border-amber-400/20 bg-amber-400/3' : isDark ? 'border-white/10' : 'border-slate-200',
                icon: '🏦',
              },
            ].map(sig => (
              <div key={sig.label} className={`border rounded-lg p-3 ${sig.bg}`}>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-sm">{sig.icon}</span>
                  <span className={`text-[10px] font-medium ${th.muted}`}>{sig.label}</span>
                </div>
                <div className={`text-2xl font-bold font-mono ${sig.color}`}>{sig.value}</div>
                <div className={`text-[10px] ${th.muted} mt-0.5 truncate`} title={sig.sub}>{sig.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Summary KPI strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: msg('UI_EXCEPTIONS_TOTAL_EXCEPTIONS'), value: ALL_EXCEPTIONS.length, color: th.heading },
            { label: msg('UI_EXCEPTIONS_CRITICAL'),         value: counts.CRITICAL,   color: 'text-red-400' },
            { label: msg('UI_EXCEPTIONS_HIGH'),             value: counts.HIGH,        color: 'text-amber-400' },
            { label: msg('UI_EXCEPTIONS_UNRESOLVED'),       value: unresolvedCount,    color: 'text-orange-400' },
          ].map(k => (
            <div key={k.label} className={`border rounded-lg p-3 ${th.card}`}>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
              <div className={`text-xs mt-0.5 ${th.muted}`}>{k.label}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`text-xs ${th.muted}`}>{msg('UI_EXCEPTIONS_SEVERITY')}</span>
          {['All', ...SEVERITY_ORDER].map(s => (
            <button
              key={s}
              onClick={() => setSeverityFilter(s)}
              className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors
                ${severityFilter === s
                  ? 'bg-violet-600 border-violet-500 text-white'
                  : `${th.badge} border-transparent`}`}
            >
              {s} {s !== 'All' ? `(${counts[s] ?? 0})` : `(${ALL_EXCEPTIONS.length})`}
            </button>
          ))}
          <label className={`flex items-center gap-1.5 text-xs ${th.muted} cursor-pointer ml-4`}>
            <input
              type="checkbox"
              checked={showResolved}
              onChange={e => setShowResolved(e.target.checked)}
              className="w-3.5 h-3.5 accent-violet-500"
            />
           {msg('UI_EXCEPTIONS_SHOW_RESOLVED')}
          </label>
          <span className={`ml-auto text-xs ${th.muted}`}>{msg('UI_USERMANAGEMENT_SHOWN', { count: filtered.length })}</span>
        </div>

        {/* Exception table */}
        <div className={`border rounded-lg overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider} ${th.muted}`}>
                <th className="px-3 py-2 text-left font-medium">{msg('UI_COMMON_INSTRUMENT_ID')}</th>
                <th className="px-3 py-2 text-left font-medium">{msg('UI_EXCEPTIONS_EXCEPTION')}</th>
                <th className="px-3 py-2 text-left font-medium">{msg('UI_EXCEPTIONS_SEVERITY_2')}</th>
                <th className="px-3 py-2 text-left font-medium hidden md:table-cell">{msg('UI_EXCEPTIONS_OCCURRED_AT')}</th>
                <th className="px-3 py-2 text-left font-medium hidden lg:table-cell">{msg('UI_DISCREPANCY_DETAIL')}</th>
                <th className="px-3 py-2 text-left font-medium">{msg('UI_COMMON_STATUS')}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(ex => (
                <tr key={ex.id} className={`border-b ${th.row}`}>
                  <td className={`px-3 py-2 font-mono ${th.body}`}>{ex.instrument_id}</td>
                  <td className={`px-3 py-2 ${th.body}`}>{ex.label}</td>
                  <td className="px-3 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${SEV[ex.severity]}`}>
                      {ex.severity}
                    </span>
                  </td>
                  <td className={`px-3 py-2 hidden md:table-cell ${th.muted}`}>
                    {ex.occurred_at.replace('T', ' ').replace('Z', '')}
                    {ex.margin_seconds !== null && (
                      <span className="ml-1 text-red-400 font-medium">{msg('UI_EXCEPTIONS_S_MARGIN', { margin_seconds: ex.margin_seconds })}</span>
                    )}
                  </td>
                  <td className={`px-3 py-2 hidden lg:table-cell ${th.muted} max-w-xs truncate`} title={ex.detail}>
                    {ex.detail}
                  </td>
                  <td className="px-3 py-2">
                    {ex.resolved
                      ? <span className="text-emerald-400 text-[11px] font-medium">{msg('UI_EXCEPTIONS_RESOLVED')}</span>
                      : <span className="text-amber-400 text-[11px] font-medium">{msg('UI_EXCEPTIONS_OPEN')}</span>}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className={`px-3 py-8 text-center ${th.muted}`}>
                   {msg('UI_EXCEPTIONS_NO_EXCEPTIONS_MATCH_CURRENT_FILTERS')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Exception type legend */}
        <div className={`border rounded-lg p-4 ${th.card}`}>
          <h3 className={`text-xs font-semibold mb-3 ${th.heading}`}>{msg('UI_EXCEPTIONS_EXCEPTION_TYPE_REFERENCE')}</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-1.5">
            {[
              ['IQA_FAIL',             'Image Quality Failure',            'HIGH'],
              ['IET_NEAR_BREACH',      'IET Near-Breach (< 30s)',          'CRITICAL'],
              ['VAULT_MISS',           'Signature / PPS Vault Miss',       'HIGH'],
              ['NGCH_REJECT',          'NGCH Filing Rejected / Retried',   'CRITICAL'],
              ['HUMAN_REVIEW',         'Escalated to Human Review',        'MEDIUM'],
              ['WORDS_FIGURES_MISMATCH','Words / Figures Amount Differ',   'HIGH'],
              ['ALTERATION_DETECTED',  'Possible Alteration Detected',     'HIGH'],
              ['OCR_LOW_CONFIDENCE',   'OCR Confidence Below Threshold',   'MEDIUM'],
              ['SIGNATURE_LOW_CONF',   'Signature Match Low Confidence',   'HIGH'],
              ['FRAUD_HIGH_SCORE',     'Fraud Score Above Threshold',      'HIGH'],
            ].map(([code, label, sev]) => (
              <div key={code} className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0 ${SEV[sev]}`}>{sev}</span>
                <span className={`text-[10px] font-mono ${th.muted}`}>{code}</span>
                <span className={`text-[10px] ${th.muted}`}>— {label}</span>
              </div>
            ))}
          </div>
        </div>

      </div>
    </AppShell>
  )
}
