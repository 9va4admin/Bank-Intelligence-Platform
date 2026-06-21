import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ── Mock RPC data ─────────────────────────────────────────────────────────────
const RPCS = [
  {
    id: 'RPC-MUM', name: 'Mumbai RPC',    zone: 'MUMBAI',  ifsc_prefix: 'SVCB0001',
    status: 'ACTIVE',  inward: 4821, outward: 3912, pending: 14,  iet_risk: 2,
    stp_rate: 94.2, avg_decision_ms: 412, last_sync: '10:58:43',
    batches: 12, lots: 28,
  },
  {
    id: 'RPC-DEL', name: 'Delhi RPC',     zone: 'DELHI',   ifsc_prefix: 'SVCB0002',
    status: 'ACTIVE',  inward: 2103, outward: 1874, pending: 7,   iet_risk: 0,
    stp_rate: 96.1, avg_decision_ms: 388, last_sync: '10:59:01',
    batches: 8,  lots: 18,
  },
  {
    id: 'RPC-CHN', name: 'Chennai RPC',   zone: 'CHENNAI', ifsc_prefix: 'SVCB0003',
    status: 'ACTIVE',  inward: 1547, outward: 1302, pending: 4,   iet_risk: 0,
    stp_rate: 97.3, avg_decision_ms: 351, last_sync: '10:58:55',
    batches: 6,  lots: 14,
  },
  {
    id: 'RPC-KOL', name: 'Kolkata RPC',   zone: 'KOLKATA', ifsc_prefix: 'SVCB0004',
    status: 'ACTIVE',  inward: 988,  outward: 841,  pending: 3,   iet_risk: 0,
    stp_rate: 95.8, avg_decision_ms: 423, last_sync: '10:58:48',
    batches: 5,  lots: 11,
  },
  {
    id: 'RPC-HYD', name: 'Hyderabad RPC', zone: 'HYDERABAD', ifsc_prefix: 'SVCB0005',
    status: 'DEGRADED', inward: 622, outward: 489,  pending: 21,  iet_risk: 5,
    stp_rate: 81.4, avg_decision_ms: 587, last_sync: '10:52:10',
    batches: 4,  lots: 9,
  },
]

const SESSION_DATE = '2026-06-19'
const CLEARING_SESSION = 'AM-CLEARING-001'

// Cross-centre fraud signals
const CROSS_CENTRE_ALERTS = [
  { id: 'XALERT-001', type: 'DUPLICATE_SIGNATURE', severity: 'HIGH',
    description: 'Same signature fingerprint seen in MUMBAI and DELHI within 2h',
    zones: ['MUMBAI', 'DELHI'], ts: '10:44:12' },
  { id: 'XALERT-002', type: 'VELOCITY_ANOMALY', severity: 'MEDIUM',
    description: 'Account ****3347 presented in 3 zones — possible round-tripping',
    zones: ['CHENNAI', 'KOLKATA', 'MUMBAI'], ts: '10:51:38' },
  { id: 'XALERT-003', type: 'IET_RISK_CLUSTER', severity: 'HIGH',
    description: 'Hyderabad RPC: 5 cheques within 30s of IET deadline',
    zones: ['HYDERABAD'], ts: '10:57:02' },
]

const sev = {
  HIGH:   'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/40 dark:text-red-300 dark:border-red-700/40',
  MEDIUM: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-700/40'
}


const rpcS = {
  ACTIVE:   'text-emerald-600 dark:text-emerald-400',
  DEGRADED: 'text-red-600 dark:text-red-400'
}


export default function CTSRPCConsolidation() {
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)

  const th = {
    page:    'bg-slate-50 dark:bg-transparent',
    card:    'bg-white border-slate-200 dark:bg-white/4 dark:border-white/8',
    heading: 'text-slate-900 dark:text-white',
    body:    'text-slate-700 dark:text-slate-300',
    muted:   'text-slate-500 dark:text-slate-400',
    faint:   'text-slate-400 dark:text-slate-600',
    divider: 'border-slate-200 dark:border-white/8',
    row:     'border-slate-100 hover:bg-slate-50 dark:border-white/4 dark:hover:bg-white/2',
    mono:    'text-slate-600 font-mono text-xs dark:text-slate-300 dark:font-mono dark:text-xs',
  }

  // Consolidated totals
  const total_inward  = RPCS.reduce((a, r) => a + r.inward,  0)
  const total_outward = RPCS.reduce((a, r) => a + r.outward, 0)
  const total_pending = RPCS.reduce((a, r) => a + r.pending, 0)
  const total_iet     = RPCS.reduce((a, r) => a + r.iet_risk, 0)
  const avg_stp       = (RPCS.reduce((a, r) => a + r.stp_rate, 0) / RPCS.length).toFixed(1)

  usePageHeader({
    subtitle: `Multi-centre clearing view · ${SESSION_DATE} · ${CLEARING_SESSION}`,
    actions: (
      <div className={`text-xs px-3 py-1.5 rounded-lg border ${'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-700/40 dark:bg-emerald-900/20 dark:text-emerald-300'}`}>
        <span className="w-1.5 h-1.5 inline-block rounded-full bg-emerald-400 mr-1.5 animate-pulse" />
        {RPCS.filter(r => r.status === 'ACTIVE').length}/{RPCS.length} RPCs Active
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* Consolidated KPI strip */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {[
            { label: 'Total Inward',    value: total_inward.toLocaleString(),  color: th.heading },
            { label: 'Total Outward',   value: total_outward.toLocaleString(), color: th.heading },
            { label: 'Pending Review',  value: total_pending, color: total_pending > 0 ? ('text-amber-600 dark:text-amber-400') : ('text-emerald-600 dark:text-emerald-400') },
            { label: 'IET Risk',        value: total_iet,     color: total_iet > 0 ? ('text-red-600 dark:text-red-400') : ('text-emerald-600 dark:text-emerald-400') },
            { label: 'Avg STP Rate',    value: `${avg_stp}%`, color: 'text-violet-600 dark:text-violet-400' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* RPC cards grid */}
        <div className="grid grid-cols-5 gap-3 mb-5">
          {RPCS.map(rpc => (
            <button
              key={rpc.id}
              onClick={() => setSelected(selected?.id === rpc.id ? null : rpc)}
              className={`text-left border rounded-xl p-3 transition-all ${th.card} ${
                selected?.id === rpc.id
                  ? 'ring-2 ring-violet-400 dark:ring-2 dark:ring-violet-500'
                  : ''
              }`}
            >
              <div className="flex items-start justify-between mb-2">
                <span className={`text-[10px] font-medium ${th.faint}`}>{rpc.zone}</span>
                <span className={`w-2 h-2 rounded-full mt-0.5 ${rpc.status === 'ACTIVE' ? 'bg-emerald-500' : 'bg-red-500'}`} />
              </div>
              <div className={`text-xs font-semibold ${th.heading} mb-0.5`}>{rpc.name}</div>
              <div className={`text-[10px] ${rpc.status === 'ACTIVE' ? (isDark ? rpcS.ACTIVE : rpcS.ACTIVE) : (isDark ? rpcS.DEGRADED : rpcS.DEGRADED)} font-medium mb-2`}>{rpc.status}</div>
              <div className="space-y-0.5">
                <div className="flex justify-between">
                  <span className={`text-[10px] ${th.faint}`}>Inward</span>
                  <span className={`text-[10px] font-medium ${th.body}`}>{rpc.inward.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className={`text-[10px] ${th.faint}`}>STP</span>
                  <span className={`text-[10px] font-medium ${rpc.stp_rate >= 90 ? ('text-emerald-600 dark:text-emerald-400') : ('text-amber-600 dark:text-amber-400')}`}>{rpc.stp_rate}%</span>
                </div>
                {rpc.iet_risk > 0 && (
                  <div className="flex justify-between">
                    <span className={`text-[10px] ${th.faint}`}>IET Risk</span>
                    <span className="text-[10px] font-medium text-red-400">⚠ {rpc.iet_risk}</span>
                  </div>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* Selected RPC detail panel */}
        {selected && (
          <div className={`border rounded-xl p-4 mb-5 ${th.card}`}>
            <div className="flex items-center justify-between mb-3">
              <span className={`text-sm font-semibold ${th.heading}`}>{selected.name} — Detail</span>
              <button onClick={() => setSelected(null)} className={`text-xs ${th.muted}`}>✕</button>
            </div>
            <div className="grid grid-cols-4 gap-4 text-xs">
              {[
                { label: 'Inward Cheques', value: selected.inward.toLocaleString() },
                { label: 'Outward Cheques', value: selected.outward.toLocaleString() },
                { label: 'Pending Review', value: selected.pending },
                { label: 'Avg Decision', value: `${selected.avg_decision_ms}ms` },
                { label: 'Batches', value: selected.batches },
                { label: 'Lots', value: selected.lots },
                { label: 'IFSC Prefix', value: selected.ifsc_prefix },
                { label: 'Last Sync', value: selected.last_sync },
              ].map(f => (
                <div key={f.label}>
                  <div className={`text-[10px] ${th.faint} mb-0.5`}>{f.label}</div>
                  <div className={`font-medium ${th.body}`}>{f.value}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Cross-centre alerts */}
        <div className={`border rounded-xl overflow-hidden ${th.card} mb-5`}>
          <div className={`px-4 py-2.5 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-medium ${th.heading}`}>Cross-Centre Intelligence</span>
            <span className={`text-[10px] ${th.muted}`}>{CROSS_CENTRE_ALERTS.length} signals</span>
          </div>
          {CROSS_CENTRE_ALERTS.map(alert => (
            <div key={alert.id} className={`flex items-start gap-3 px-4 py-3 border-b ${th.row}`}>
              <span className={`text-[10px] px-2 py-0.5 rounded border font-medium shrink-0 ${sev[alert.severity]}`}>{alert.severity}</span>
              <div className="flex-1 min-w-0">
                <div className={`text-xs font-medium ${th.body}`}>{alert.description}</div>
                <div className={`text-[10px] ${th.faint} mt-0.5`}>
                  Zones: {alert.zones.join(' · ')} · {alert.ts}
                </div>
              </div>
              <span className={`text-[10px] ${th.faint} shrink-0`}>{alert.type.replace(/_/g, ' ')}</span>
            </div>
          ))}
        </div>

        {/* Consolidated summary table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          <div className={`px-4 py-2.5 border-b ${th.divider}`}>
            <span className={`text-sm font-medium ${th.heading}`}>Settlement Position — All Zones</span>
          </div>

          {/* Table header */}
          <div className={`grid grid-cols-12 gap-2 px-4 py-2 border-b ${th.divider} text-[10px] ${th.faint} font-medium uppercase tracking-wider`}>
            <div className="col-span-2">RPC</div>
            <div className="col-span-1">Zone</div>
            <div className="col-span-1 text-right">Inward</div>
            <div className="col-span-1 text-right">Outward</div>
            <div className="col-span-1 text-right">Pending</div>
            <div className="col-span-1 text-right">IET Risk</div>
            <div className="col-span-1 text-right">STP %</div>
            <div className="col-span-1 text-right">Avg ms</div>
            <div className="col-span-1 text-right">Batches</div>
            <div className="col-span-1 text-right">Lots</div>
            <div className="col-span-1 text-right">Sync</div>
          </div>

          {RPCS.map(rpc => (
            <div key={rpc.id} className={`grid grid-cols-12 gap-2 px-4 py-2.5 border-b ${th.row} text-xs`}>
              <div className={`col-span-2 font-medium ${th.heading}`}>{rpc.name}</div>
              <div className={`col-span-1 ${th.muted}`}>{rpc.zone.slice(0, 3)}</div>
              <div className={`col-span-1 text-right ${th.body}`}>{rpc.inward.toLocaleString()}</div>
              <div className={`col-span-1 text-right ${th.body}`}>{rpc.outward.toLocaleString()}</div>
              <div className={`col-span-1 text-right ${rpc.pending > 0 ? ('text-amber-600 dark:text-amber-400') : th.faint}`}>{rpc.pending}</div>
              <div className={`col-span-1 text-right ${rpc.iet_risk > 0 ? ('text-red-600 dark:text-red-400') : th.faint}`}>{rpc.iet_risk > 0 ? `⚠ ${rpc.iet_risk}` : '—'}</div>
              <div className={`col-span-1 text-right ${rpc.stp_rate >= 90 ? ('text-emerald-600 dark:text-emerald-400') : ('text-amber-600 dark:text-amber-400')}`}>{rpc.stp_rate}</div>
              <div className={`col-span-1 text-right ${rpc.avg_decision_ms > 500 ? ('text-amber-600 dark:text-amber-400') : th.body}`}>{rpc.avg_decision_ms}</div>
              <div className={`col-span-1 text-right ${th.faint}`}>{rpc.batches}</div>
              <div className={`col-span-1 text-right ${th.faint}`}>{rpc.lots}</div>
              <div className={`col-span-1 text-right ${th.faint} font-mono text-[10px]`}>{rpc.last_sync}</div>
            </div>
          ))}

          {/* Totals row */}
          <div className={`grid grid-cols-12 gap-2 px-4 py-2.5 text-xs font-medium ${'bg-slate-50 dark:bg-white/3'}`}>
            <div className={`col-span-2 ${th.heading}`}>All Zones</div>
            <div className="col-span-1" />
            <div className={`col-span-1 text-right ${th.heading}`}>{total_inward.toLocaleString()}</div>
            <div className={`col-span-1 text-right ${th.heading}`}>{total_outward.toLocaleString()}</div>
            <div className={`col-span-1 text-right ${total_pending > 0 ? ('text-amber-600 dark:text-amber-400') : th.heading}`}>{total_pending}</div>
            <div className={`col-span-1 text-right ${total_iet > 0 ? ('text-red-600 dark:text-red-400') : th.heading}`}>{total_iet > 0 ? `⚠ ${total_iet}` : '—'}</div>
            <div className={`col-span-1 text-right ${'text-violet-600 dark:text-violet-400'}`}>{avg_stp}%</div>
            <div className="col-span-4" />
          </div>
        </div>

      </div>
    </AppShell>
  )
}
