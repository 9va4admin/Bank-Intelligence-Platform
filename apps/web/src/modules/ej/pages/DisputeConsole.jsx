/**
 * EJ Dispute Console — full-page dispute management for EJ resolution workflows.
 * Shows: open disputes, NPCI claim details, EJ match status, CCTV evidence, auto-resolve vs escalate.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import EJShell from '../layout/EJShell'
import { useDisputes } from '../hooks/useEJData'
import RaiseDisputeModal from '../components/RaiseDisputeModal'
import {
  AlertTriangle, CheckCircle2, Clock, FileSearch, Video,
  ChevronDown, ChevronRight, Plus, Filter, RefreshCw,
} from 'lucide-react'

const bankId = 'demo-bank'

const STATUS_META = {
  AUTO_RESOLVED:     { label: 'Auto-Resolved', icon: CheckCircle2, colorD: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20', colorL: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  ESCALATED_TO_HUMAN:{ label: 'Escalated',     icon: AlertTriangle, colorD: 'text-amber-400 bg-amber-400/10 border-amber-400/20',     colorL: 'text-amber-700 bg-amber-50 border-amber-200'   },
  FILED_TO_NPCI:     { label: 'Filed to NPCI', icon: FileSearch,    colorD: 'text-blue-400 bg-blue-400/10 border-blue-400/20',        colorL: 'text-blue-700 bg-blue-50 border-blue-200'       },
  PENDING:           { label: 'Pending',        icon: Clock,         colorD: 'text-slate-400 bg-slate-400/10 border-slate-400/20',    colorL: 'text-slate-600 bg-slate-50 border-slate-200'    },
}

const inrFmt = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

function StatusPill({ status, isDark }) {
  const meta = STATUS_META[status] || STATUS_META.PENDING
  const Icon = meta.icon
  const cls = isDark ? meta.colorD : meta.colorL
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${cls}`}>
      <Icon size={11} />
      {meta.label}
    </span>
  )
}

function DisputeRow({ d, isDark, onExpand, expanded }) {
  const th = {
    row:   isDark ? 'border-white/6 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    text:  isDark ? 'text-slate-200' : 'text-slate-800',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    card:  isDark ? 'bg-navy-900/50 border-white/8' : 'bg-slate-50 border-slate-200',
  }
  return (
    <>
      <tr
        className={`border-b cursor-pointer transition-colors ${th.row}`}
        onClick={() => onExpand(d.id)}
      >
        <td className="px-4 py-3">
          {expanded ? <ChevronDown size={14} className={th.muted} /> : <ChevronRight size={14} className={th.muted} />}
        </td>
        <td className={`px-4 py-3 font-mono text-xs ${th.muted}`}>{d.npci_claim_id}</td>
        <td className={`px-4 py-3 font-mono text-xs ${th.text}`}>{d.atm_id}</td>
        <td className={`px-4 py-3 text-sm ${th.text}`}>{inrFmt.format(d.claim_amount)}</td>
        <td className={`px-4 py-3 text-xs ${th.muted}`}>{d.claim_type}</td>
        <td className="px-4 py-3"><StatusPill status={d.status} isDark={isDark} /></td>
        <td className={`px-4 py-3 text-xs ${th.muted}`}>{new Date(d.created_at).toLocaleString('en-IN')}</td>
      </tr>
      {expanded && (
        <tr className={`border-b ${isDark ? 'border-white/4' : 'border-slate-100'}`}>
          <td colSpan={7} className="px-6 py-4">
            <div className={`rounded-lg border p-4 space-y-3 ${th.card}`}>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className={`text-xs font-medium uppercase tracking-wide mb-1 ${th.muted}`}>EJ Match Status</p>
                  <p className={`font-medium ${d.ej_matched ? 'text-emerald-400' : 'text-red-400'}`}>
                    {d.ej_matched ? '✓ EJ Record Matched' : '✗ No EJ Match Found'}
                  </p>
                  {d.canonical_hash && (
                    <p className={`font-mono text-xs mt-0.5 ${th.muted}`}>{d.canonical_hash}</p>
                  )}
                </div>
                <div>
                  <p className={`text-xs font-medium uppercase tracking-wide mb-1 ${th.muted}`}>CCTV Evidence</p>
                  <p className={`font-medium ${d.cctv_available ? 'text-emerald-400' : 'text-amber-400'}`}>
                    {d.cctv_available ? '✓ Clip Available' : '⚠ No CCTV Clip'}
                  </p>
                  {d.cctv_timestamp && (
                    <p className={`text-xs mt-0.5 ${th.muted}`}>{d.cctv_timestamp}</p>
                  )}
                </div>
                {d.resolution_reason && (
                  <div className="col-span-2">
                    <p className={`text-xs font-medium uppercase tracking-wide mb-1 ${th.muted}`}>Resolution Reason</p>
                    <p className={`text-sm ${th.text}`}>{d.resolution_reason}</p>
                  </div>
                )}
              </div>
              {d.cctv_available && (
                <button className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors">
                  <Video size={13} />
                  View CCTV Clip
                </button>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

const SAMPLE_DISPUTES = [
  { id: '1', npci_claim_id: 'CTS-2026-00181', atm_id: 'ATM-MH-0042', claim_amount: 5000, claim_type: 'CASH_NOT_DISPENSED', status: 'AUTO_RESOLVED', ej_matched: true, cctv_available: true, cctv_timestamp: '2026-06-24 10:31:05', canonical_hash: 'a1b2c3d4e5f6...', resolution_reason: 'EJ confirms dispense did not occur. CCTV supports claim.', created_at: '2026-06-24T10:40:00Z' },
  { id: '2', npci_claim_id: 'CTS-2026-00182', atm_id: 'ATM-DL-0011', claim_amount: 10000, claim_type: 'PARTIAL_DISPENSE', status: 'ESCALATED_TO_HUMAN', ej_matched: true, cctv_available: false, resolution_reason: 'EJ matched but CCTV unavailable — requires human review.', created_at: '2026-06-24T11:15:00Z' },
  { id: '3', npci_claim_id: 'CTS-2026-00183', atm_id: 'ATM-MH-0098', claim_amount: 2000, claim_type: 'CASH_NOT_DISPENSED', status: 'PENDING', ej_matched: false, cctv_available: false, created_at: '2026-06-24T12:00:00Z' },
  { id: '4', npci_claim_id: 'CTS-2026-00180', atm_id: 'ATM-KA-0033', claim_amount: 8000, claim_type: 'WRONG_AMOUNT', status: 'FILED_TO_NPCI', ej_matched: true, cctv_available: true, cctv_timestamp: '2026-06-23 14:20:11', canonical_hash: 'f9e8d7c6b5a4...', resolution_reason: 'EJ and CCTV both confirm wrong amount dispensed. Filed to NPCI.', created_at: '2026-06-23T14:30:00Z' },
]

const FILTER_OPTIONS = ['All', 'PENDING', 'AUTO_RESOLVED', 'ESCALATED_TO_HUMAN', 'FILED_TO_NPCI']

export default function DisputeConsole() {
  const { isDark } = useTheme()
  const { data: apiDisputes, isLoading } = useDisputes(bankId)
  const disputes = (apiDisputes && apiDisputes.length > 0) ? apiDisputes : SAMPLE_DISPUTES

  const [expandedId, setExpandedId] = useState(null)
  const [statusFilter, setStatusFilter] = useState('All')
  const [raiseOpen, setRaiseOpen] = useState(false)

  const th = {
    page:    isDark ? 'bg-[#020817]' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    th:      isDark ? 'bg-white/4 text-slate-400' : 'bg-slate-50 text-slate-500',
    pill:    isDark ? 'bg-white/6 hover:bg-white/10 text-slate-300 border-white/8' : 'bg-slate-100 hover:bg-slate-200 text-slate-600 border-slate-200',
    pillActive: isDark ? 'bg-cyan-600/30 text-cyan-300 border-cyan-500/30' : 'bg-cyan-50 text-cyan-700 border-cyan-200',
  }

  const filtered = statusFilter === 'All' ? disputes : disputes.filter(d => d.status === statusFilter)
  const counts = FILTER_OPTIONS.reduce((acc, f) => {
    acc[f] = f === 'All' ? disputes.length : disputes.filter(d => d.status === f).length
    return acc
  }, {})

  const autoResolvedCount = disputes.filter(d => d.status === 'AUTO_RESOLVED').length
  const autoResolveRate = disputes.length > 0 ? Math.round((autoResolvedCount / disputes.length) * 100) : 0

  return (
    <EJShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 space-y-5`}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Dispute Console</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>NPCI claim resolution via EJ + CCTV evidence</p>
          </div>
          <div className="flex items-center gap-2">
            <button className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-colors ${th.pill}`}>
              <RefreshCw size={12} />
              Refresh
            </button>
            <button
              onClick={() => setRaiseOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-cyan-600 hover:bg-cyan-500 text-white transition-colors"
            >
              <Plus size={13} />
              Raise Dispute
            </button>
          </div>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Total Disputes', value: disputes.length, sub: 'All time' },
            { label: 'Auto-Resolved', value: autoResolvedCount, sub: `${autoResolveRate}% auto-resolve rate` },
            { label: 'Escalated', value: disputes.filter(d => d.status === 'ESCALATED_TO_HUMAN').length, sub: 'Requires human review' },
            { label: 'Pending', value: disputes.filter(d => d.status === 'PENDING').length, sub: 'Awaiting EJ/CCTV match' },
          ].map(kpi => (
            <div key={kpi.label} className={`rounded-xl border p-4 ${th.card}`}>
              <p className={`text-xs ${th.muted}`}>{kpi.label}</p>
              <p className={`text-2xl font-bold mt-1 ${th.heading}`}>{kpi.value}</p>
              <p className={`text-xs mt-0.5 ${th.muted}`}>{kpi.sub}</p>
            </div>
          ))}
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-2">
          <Filter size={13} className={th.muted} />
          {FILTER_OPTIONS.map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1 rounded-full text-xs border transition-colors ${statusFilter === f ? th.pillActive : th.pill}`}
            >
              {f} ({counts[f]})
            </button>
          ))}
        </div>

        {/* Disputes table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="min-w-full">
            <thead>
              <tr className={`text-xs font-medium uppercase tracking-wide ${th.th}`}>
                <th className="px-4 py-3 text-left w-8"></th>
                <th className="px-4 py-3 text-left">NPCI Claim ID</th>
                <th className="px-4 py-3 text-left">ATM ID</th>
                <th className="px-4 py-3 text-left">Amount</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Raised At</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                [...Array(4)].map((_, i) => (
                  <tr key={i} className={`border-b ${isDark ? 'border-white/4' : 'border-slate-100'}`}>
                    {[...Array(7)].map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className={`h-4 rounded animate-pulse ${isDark ? 'bg-white/6' : 'bg-slate-200'}`} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className={`px-4 py-12 text-center text-sm ${th.muted}`}>
                    No disputes match the selected filter.
                  </td>
                </tr>
              ) : (
                filtered.map(d => (
                  <DisputeRow
                    key={d.id}
                    d={d}
                    isDark={isDark}
                    expanded={expandedId === d.id}
                    onExpand={id => setExpandedId(expandedId === id ? null : id)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {raiseOpen && (
        <RaiseDisputeModal
          bankId={bankId}
          onClose={() => setRaiseOpen(false)}
        />
      )}
    </EJShell>
  )
}
