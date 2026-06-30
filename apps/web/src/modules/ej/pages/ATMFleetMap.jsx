/**
 * ATM Fleet Map — full-page fleet observability with health status, OEM breakdown, and pending upload tracking.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import EJShell from '../layout/EJShell'
import { useATMFleet } from '../hooks/useEJData'
import {
  CheckCircle2, AlertTriangle, XCircle, RefreshCw, Filter,
  Activity, Upload, Calendar, Cpu,
} from 'lucide-react'

const bankId = 'demo-bank'

const HEALTH_META = {
  HEALTHY:  { label: 'Healthy',  Icon: CheckCircle2, colorD: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20', colorL: 'text-emerald-700 bg-emerald-50 border-emerald-200' },
  DEGRADED: { label: 'Degraded', Icon: AlertTriangle, colorD: 'text-amber-400 bg-amber-400/10 border-amber-400/20',   colorL: 'text-amber-700 bg-amber-50 border-amber-200'   },
  CRITICAL: { label: 'Critical', Icon: XCircle,      colorD: 'text-red-400 bg-red-400/10 border-red-400/20',          colorL: 'text-red-700 bg-red-50 border-red-200'         },
}

const OEM_COLORS = {
  NCR_SELFSERV:    'bg-blue-500',
  DIEBOLD_NIXDORF: 'bg-violet-500',
  HYOSUNG:         'bg-cyan-500',
  GRG_BANKING:     'bg-orange-500',
  WINCOR_NIXDORF:  'bg-pink-500',
}

function HealthPill({ status, isDark }) {
  const meta = HEALTH_META[status] || HEALTH_META.DEGRADED
  const { Icon } = meta
  const cls = isDark ? meta.colorD : meta.colorL
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${cls}`}>
      <Icon size={11} />
      {meta.label}
    </span>
  )
}

function OEMDot({ oem }) {
  const bg = OEM_COLORS[oem] || 'bg-slate-400'
  return <span className={`inline-block w-2 h-2 rounded-full ${bg} mr-1.5`} />
}

function ATMCard({ atm, isDark }) {
  const th = {
    card:    isDark ? 'bg-navy-900/60 border-white/8 hover:border-white/16' : 'bg-white border-slate-200 hover:border-slate-300',
    text:    isDark ? 'text-slate-200' : 'text-slate-800',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    subtext: isDark ? 'text-slate-500' : 'text-slate-400',
  }

  const pendingCls = atm.pending_uploads > 0
    ? (atm.pending_uploads > 5 ? 'text-red-400' : 'text-amber-400')
    : (isDark ? 'text-emerald-400' : 'text-emerald-600')

  return (
    <div className={`rounded-xl border p-4 transition-colors ${th.card}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className={`font-mono text-xs font-semibold ${th.text}`}>{atm.atm_id}</p>
          <p className={`text-xs mt-0.5 ${th.muted}`}>{atm.branch}</p>
        </div>
        <HealthPill status={atm.status} isDark={isDark} />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className={`flex items-center gap-1 text-xs ${th.subtext}`}><Cpu size={11} /> OEM</span>
          <span className={`text-xs ${th.muted}`}>
            <OEMDot oem={atm.oem} />
            {atm.oem.replace(/_/g, ' ')}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className={`flex items-center gap-1 text-xs ${th.subtext}`}><Calendar size={11} /> Last EJ</span>
          <span className={`text-xs ${th.muted}`}>{atm.last_ej_date}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className={`flex items-center gap-1 text-xs ${th.subtext}`}><Upload size={11} /> Pending</span>
          <span className={`text-xs font-medium ${pendingCls}`}>
            {atm.pending_uploads === 0 ? '— none' : `${atm.pending_uploads} upload${atm.pending_uploads > 1 ? 's' : ''}`}
          </span>
        </div>
      </div>
    </div>
  )
}

const STATUS_FILTERS = ['All', 'HEALTHY', 'DEGRADED', 'CRITICAL']

export default function ATMFleetMap() {
  const { isDark } = useTheme()
  const { data: fleet = [], isLoading, refetch } = useATMFleet(bankId)

  const [statusFilter, setStatusFilter] = useState('All')
  const [oemFilter, setOemFilter] = useState('All')

  const th = {
    page:    isDark ? 'bg-[#020817]' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    pill:    isDark ? 'bg-white/6 hover:bg-white/10 text-slate-300 border-white/8' : 'bg-slate-100 hover:bg-slate-200 text-slate-600 border-slate-200',
    pillActive: isDark ? 'bg-cyan-600/30 text-cyan-300 border-cyan-500/30' : 'bg-cyan-50 text-cyan-700 border-cyan-200',
  }

  const allOEMs = ['All', ...Array.from(new Set(fleet.map(a => a.oem))).sort()]

  const filtered = fleet.filter(a => {
    if (statusFilter !== 'All' && a.status !== statusFilter) return false
    if (oemFilter !== 'All' && a.oem !== oemFilter) return false
    return true
  })

  const counts = {
    total:    fleet.length,
    healthy:  fleet.filter(a => a.status === 'HEALTHY').length,
    degraded: fleet.filter(a => a.status === 'DEGRADED').length,
    critical: fleet.filter(a => a.status === 'CRITICAL').length,
  }
  const pendingTotal = fleet.reduce((s, a) => s + (a.pending_uploads || 0), 0)

  return (
    <EJShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5 space-y-5`}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>ATM Fleet Map</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Real-time health status across {counts.total} ATMs</p>
          </div>
          <button
            onClick={() => refetch()}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs transition-colors ${th.pill}`}
          >
            <RefreshCw size={12} />
            Refresh
          </button>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: 'Total ATMs',       value: counts.total,    Icon: Activity,      color: isDark ? 'text-slate-200' : 'text-slate-800' },
            { label: 'Healthy',          value: counts.healthy,  Icon: CheckCircle2,  color: 'text-emerald-400' },
            { label: 'Degraded',         value: counts.degraded, Icon: AlertTriangle, color: 'text-amber-400'   },
            { label: 'Critical',         value: counts.critical, Icon: XCircle,       color: 'text-red-400'     },
          ].map(({ label, value, Icon, color }) => (
            <div key={label} className={`rounded-xl border p-4 ${th.card}`}>
              <div className="flex items-center gap-2 mb-1">
                <Icon size={14} className={color} />
                <p className={`text-xs ${th.muted}`}>{label}</p>
              </div>
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>

        {/* Pending uploads callout */}
        {pendingTotal > 0 && (
          <div className={`rounded-xl border px-4 py-3 flex items-center gap-3 ${
            isDark ? 'bg-amber-400/8 border-amber-400/20' : 'bg-amber-50 border-amber-200'
          }`}>
            <Upload size={15} className="text-amber-400 shrink-0" />
            <p className={`text-sm ${isDark ? 'text-amber-300' : 'text-amber-700'}`}>
              <span className="font-semibold">{pendingTotal} EJ log upload{pendingTotal > 1 ? 's' : ''}</span> pending across the fleet. Check edge agent connectivity for CRITICAL ATMs.
            </p>
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          <Filter size={13} className={th.muted} />
          {STATUS_FILTERS.map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1 rounded-full text-xs border transition-colors ${statusFilter === f ? th.pillActive : th.pill}`}
            >
              {f}
            </button>
          ))}
          <span className={`text-xs ${th.muted} mx-1`}>|</span>
          {allOEMs.map(o => (
            <button
              key={o}
              onClick={() => setOemFilter(o)}
              className={`px-3 py-1 rounded-full text-xs border transition-colors ${oemFilter === o ? th.pillActive : th.pill}`}
            >
              {o === 'All' ? 'All OEMs' : o.replace(/_/g, ' ')}
            </button>
          ))}
        </div>

        {/* Grid */}
        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {[...Array(10)].map((_, i) => (
              <div key={i} className={`rounded-xl border p-4 h-28 animate-pulse ${th.card}`} />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className={`rounded-xl border p-12 text-center text-sm ${th.card} ${th.muted}`}>
            No ATMs match the selected filters.
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {filtered.map(atm => (
              <ATMCard key={atm.atm_id} atm={atm} isDark={isDark} />
            ))}
          </div>
        )}

        {/* OEM legend */}
        <div className={`rounded-xl border p-4 ${th.card}`}>
          <p className={`text-xs font-medium uppercase tracking-wide mb-3 ${th.muted}`}>OEM Legend</p>
          <div className="flex flex-wrap gap-4">
            {Object.entries(OEM_COLORS).map(([oem, bg]) => (
              <span key={oem} className="flex items-center gap-1.5 text-xs">
                <span className={`w-2.5 h-2.5 rounded-full ${bg}`} />
                <span className={th.muted}>{oem.replace(/_/g, ' ')}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </EJShell>
  )
}
