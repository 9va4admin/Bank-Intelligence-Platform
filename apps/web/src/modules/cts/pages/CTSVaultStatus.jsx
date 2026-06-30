import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { useTheme } from '../../../shared/theme/ThemeContext'

const SB_VAULT_DATA = [
  { label: 'Signature Vault', keys: 18_432, hitRate: 99.2, lastSync: '2026-06-19 06:00', status: 'HEALTHY', redis: 'redis-cts', missAction: 'HUMAN_REVIEW' },
  { label: 'PPS Vault',       keys: 12_817, hitRate: 98.7, lastSync: '2026-06-19 06:00', status: 'HEALTHY', redis: 'redis-cts', missAction: 'HUMAN_REVIEW' },
]

const SMB_VAULT_DATA = [
  { label: 'Signature Vault', keys: 2_841, hitRate: 99.1, lastSync: '2026-06-19 06:00', status: 'HEALTHY', redis: 'redis-cts', missAction: 'HUMAN_REVIEW' },
  { label: 'PPS Vault',       keys: 1_924, hitRate: 98.5, lastSync: '2026-06-19 06:00', status: 'HEALTHY', redis: 'redis-cts', missAction: 'HUMAN_REVIEW' },
]

const VAULT_METRICS = [
  { hour: '10:00', sig: 99.4, pps: 98.9 },
  { hour: '09:00', sig: 99.1, pps: 98.7 },
  { hour: '08:00', sig: 99.3, pps: 99.0 },
  { hour: '07:00', sig: 98.8, pps: 98.5 },
  { hour: '06:00', sig: 97.2, pps: 96.8 },
  { hour: '05:00', sig: 99.5, pps: 99.1 },
  { hour: '04:00', sig: 99.6, pps: 99.3 },
  { hour: '03:00', sig: 99.7, pps: 99.4 },
  { hour: '02:00', sig: 99.5, pps: 99.2 },
  { hour: '01:00', sig: 99.3, pps: 99.0 },
  { hour: '00:00', sig: 99.1, pps: 98.8 },
  { hour: '23:00', sig: 98.9, pps: 98.6 },
]

const RECENT_MISSES = [
  { time: '10:42:31', instrument: 'CHQ-2026-001892', vault: 'Signature', account: '****7821', reason: 'New account — no specimen',       routed: 'HUMAN_REVIEW' },
  { time: '10:11:08', instrument: 'CHQ-2026-001871', vault: 'PPS',       account: '****5543', reason: 'PPS limit exhausted',             routed: 'HUMAN_REVIEW' },
  { time: '09:58:22', instrument: 'CHQ-2026-001855', vault: 'Signature', account: '****0014', reason: 'Specimen update in progress',     routed: 'HUMAN_REVIEW' },
  { time: '09:44:47', instrument: 'CHQ-2026-001843', vault: 'PPS',       account: '****2287', reason: 'PPS not registered',              routed: 'HUMAN_REVIEW' },
  { time: '09:17:04', instrument: 'CHQ-2026-001744', vault: 'PPS',       account: '****3310', reason: 'PPS not registered',              routed: 'HUMAN_REVIEW' },
  { time: '09:02:39', instrument: 'CHQ-2026-001722', vault: 'Signature', account: '****6641', reason: 'Specimen expired',                routed: 'HUMAN_REVIEW' },
  { time: '08:55:12', instrument: 'CHQ-2026-001701', vault: 'Signature', account: '****9902', reason: 'Specimen expired',                routed: 'HUMAN_REVIEW' },
  { time: '08:33:50', instrument: 'CHQ-2026-001689', vault: 'PPS',       account: '****1128', reason: 'CBS sync lag — key absent',       routed: 'HUMAN_REVIEW' },
  { time: '07:51:18', instrument: 'CHQ-2026-001654', vault: 'Signature', account: '****8876', reason: 'Multi-signatory — partial load',  routed: 'HUMAN_REVIEW' },
  { time: '07:22:03', instrument: 'CHQ-2026-001630', vault: 'PPS',       account: '****4499', reason: 'Cheque series mismatch',          routed: 'HUMAN_REVIEW' },
]

const SB_SYNC_LOG = [
  { time: 'Jun 19 06:00:03', event: 'VaultSyncWorkflow completed',        signatures: 18_432, pps: 12_817, duration: '4m 12s', status: 'OK' },
  { time: 'Jun 18 06:00:07', event: 'VaultSyncWorkflow completed',        signatures: 18_401, pps: 12_790, duration: '4m 08s', status: 'OK' },
  { time: 'Jun 17 06:00:11', event: 'VaultSyncWorkflow completed',        signatures: 18_388, pps: 12_774, duration: '4m 21s', status: 'OK' },
  { time: 'Jun 16 06:00:02', event: 'VaultSyncWorkflow completed',        signatures: 18_362, pps: 12_751, duration: '4m 05s', status: 'OK' },
  { time: 'Jun 15 06:03:45', event: 'VaultSyncWorkflow retried (CBS lag)',signatures: 18_341, pps: 12_730, duration: '6m 38s', status: 'WARN' },
  { time: 'Jun 14 06:00:09', event: 'VaultSyncWorkflow completed',        signatures: 18_320, pps: 12_715, duration: '4m 11s', status: 'OK' },
  { time: 'Jun 13 06:00:04', event: 'VaultSyncWorkflow completed',        signatures: 18_298, pps: 12_698, duration: '4m 02s', status: 'OK' },
]

const SMB_SYNC_LOG = [
  { time: 'Jun 19 06:00:05', event: 'VaultSyncWorkflow completed',        signatures: 2_841,  pps: 1_924,  duration: '0m 48s', status: 'OK' },
  { time: 'Jun 18 06:00:09', event: 'VaultSyncWorkflow completed',        signatures: 2_838,  pps: 1_921,  duration: '0m 46s', status: 'OK' },
  { time: 'Jun 17 06:00:08', event: 'VaultSyncWorkflow completed',        signatures: 2_831,  pps: 1_918,  duration: '0m 47s', status: 'OK' },
  { time: 'Jun 16 06:00:04', event: 'VaultSyncWorkflow completed',        signatures: 2_829,  pps: 1_915,  duration: '0m 45s', status: 'OK' },
  { time: 'Jun 15 06:01:12', event: 'VaultSyncWorkflow retried (CBS lag)',signatures: 2_822,  pps: 1_911,  duration: '1m 03s', status: 'WARN' },
  { time: 'Jun 14 06:00:06', event: 'VaultSyncWorkflow completed',        signatures: 2_817,  pps: 1_908,  duration: '0m 44s', status: 'OK' },
  { time: 'Jun 13 06:00:03', event: 'VaultSyncWorkflow completed',        signatures: 2_810,  pps: 1_903,  duration: '0m 43s', status: 'OK' },
]

const STATUS_COLOR = { HEALTHY: 'text-emerald-500', DEGRADED: 'text-amber-500', DOWN: 'text-red-500' }
const SYNC_STATUS_COLOR = { OK: 'text-emerald-500', WARN: 'text-amber-500', ERROR: 'text-red-500' }

const MIN_HIT = 96
const MAX_HIT = 100

function hitPct(val) {
  return ((val - MIN_HIT) / (MAX_HIT - MIN_HIT)) * 100
}

export default function CTSVaultStatus() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()

  const VAULT_DATA = isSMB ? SMB_VAULT_DATA : SB_VAULT_DATA
  const SYNC_LOG   = isSMB ? SMB_SYNC_LOG   : SB_SYNC_LOG

  const th = {
    page:      isDark ? 'bg-navy-950 text-white'                      : 'bg-slate-50 text-slate-900',
    card:      isDark ? 'bg-white/5 border-white/8'                   : 'bg-white border-slate-200',
    heading:   isDark ? 'text-white'                                   : 'text-slate-900',
    body:      isDark ? 'text-slate-300'                               : 'text-slate-700',
    muted:     isDark ? 'text-slate-400'                               : 'text-slate-500',
    faint:     isDark ? 'text-slate-500'                               : 'text-slate-400',
    divider:   isDark ? 'border-white/8'                               : 'border-slate-200',
    dividerSm: isDark ? 'border-white/5'                               : 'border-slate-100',
    row:       isDark ? 'border-white/5 hover:bg-white/3'              : 'border-slate-100 hover:bg-slate-50',
    redis:     isDark ? 'text-slate-500'                               : 'text-slate-400',
    statVal:   isDark ? 'text-slate-200'                               : 'text-slate-800',
    thCell:    isDark ? 'text-slate-500'                               : 'text-slate-400',
    bar:       isDark ? 'bg-white/8'                                   : 'bg-slate-100',
    kpi:       isDark ? 'bg-navy-900 border-white/8'                   : 'bg-white border-slate-200',
    lockBadge: isDark ? 'bg-amber-500/10 text-amber-400 border-amber-500/20' : 'bg-amber-50 text-amber-700 border-amber-200',
  }

  usePageHeader({ subtitle: 'Signature Vault · PPS Vault · VaultSyncWorkflow' })

  const totalKeys  = VAULT_DATA.reduce((s, v) => s + v.keys, 0)
  const avgSigHit  = VAULT_DATA[0].hitRate
  const avgPpsHit  = VAULT_DATA[1].hitRate
  const lastSync   = '4m ago'

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          {[
            { label: 'Total Vault Keys',  value: totalKeys.toLocaleString(), color: th.heading },
            { label: 'Sig Hit Rate',      value: `${avgSigHit}%`,            color: 'text-emerald-500' },
            { label: 'PPS Hit Rate',      value: `${avgPpsHit}%`,            color: 'text-emerald-500' },
            { label: 'Last Sync',         value: lastSync,                   color: th.statVal },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.kpi}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Vault health cards */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {VAULT_DATA.map(v => (
            <div key={v.label} className={`border rounded-xl p-5 ${th.card}`}>
              <div className="flex items-center justify-between mb-4">
                <span className={`text-sm font-semibold ${th.heading}`}>{v.label}</span>
                <span className={`text-xs font-semibold ${STATUS_COLOR[v.status]}`}>{v.status}</span>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-4">
                <Stat label="Keys loaded"  value={v.keys.toLocaleString()} statVal={th.statVal} muted={th.muted} />
                <Stat label="Hit rate"     value={`${v.hitRate}%`}         statVal="text-emerald-500" muted={th.muted} />
                <Stat label="Last sync"    value={v.lastSync}              statVal={th.statVal} muted={th.muted} />
                <Stat label="Redis cluster" value={v.redis}                statVal={th.redis}   muted={th.muted} />
              </div>

              {/* Hit rate progress bar */}
              <div className="mb-3">
                <div className="flex justify-between mb-1">
                  <span className={`text-[10px] ${th.muted}`}>Hit rate</span>
                  <span className={`text-[10px] text-emerald-500`}>{v.hitRate}%</span>
                </div>
                <div className={`w-full h-1.5 rounded-full ${th.bar}`}>
                  <div
                    className="h-1.5 rounded-full bg-emerald-500"
                    style={{ width: `${v.hitRate}%` }}
                  />
                </div>
              </div>

              {/* Miss action locked badge */}
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] ${th.muted}`}>Miss action:</span>
                <span className={`inline-flex items-center gap-1 text-[10px] font-semibold border rounded px-1.5 py-0.5 ${th.lockBadge}`}>
                  🔒 {v.missAction}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Hit rate trend — last 12 hours */}
        <div className={`border rounded-xl p-4 mb-6 ${th.card}`}>
          <div className={`text-sm font-medium ${th.heading} mb-4`}>Hit Rate Trend — Last 12 Hours</div>
          <div className="space-y-3">
            {/* Signature vault bars */}
            <div>
              <div className={`text-[10px] ${th.muted} mb-2`}>Signature Vault</div>
              <div className="space-y-1">
                {VAULT_METRICS.map(m => (
                  <div key={`sig-${m.hour}`} className="flex items-center gap-2">
                    <span className={`text-[10px] ${th.faint} font-mono w-12 shrink-0 text-right`}>{m.hour}</span>
                    <div className={`flex-1 ${th.bar} rounded h-3`}>
                      <div
                        className="h-3 rounded bg-emerald-500/70"
                        style={{ width: `${hitPct(m.sig)}%` }}
                      />
                    </div>
                    <span className={`text-[10px] ${m.sig < 98.5 ? 'text-amber-500' : 'text-emerald-500'} w-10 text-right`}>{m.sig}%</span>
                  </div>
                ))}
              </div>
            </div>
            <div className={`border-t ${th.dividerSm} pt-3`}>
              <div className={`text-[10px] ${th.muted} mb-2`}>PPS Vault</div>
              <div className="space-y-1">
                {VAULT_METRICS.map(m => (
                  <div key={`pps-${m.hour}`} className="flex items-center gap-2">
                    <span className={`text-[10px] ${th.faint} font-mono w-12 shrink-0 text-right`}>{m.hour}</span>
                    <div className={`flex-1 ${th.bar} rounded h-3`}>
                      <div
                        className="h-3 rounded bg-violet-500/70"
                        style={{ width: `${hitPct(m.pps)}%` }}
                      />
                    </div>
                    <span className={`text-[10px] ${m.pps < 98.0 ? 'text-amber-500' : 'text-emerald-500'} w-10 text-right`}>{m.pps}%</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className={`text-[9px] ${th.faint} mt-3`}>Bar width scaled between 96% and 100% hit rate for visibility</div>
        </div>

        {/* Recent vault misses */}
        <div className={`border rounded-xl mb-6 ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-medium ${th.heading}`}>Recent Vault Misses</span>
            <span className="text-[10px] text-amber-500 uppercase tracking-wide">All routed → Human Review</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thCell} border-b ${th.dividerSm}`}>
                <th className="text-left px-4 py-2 font-normal">Time</th>
                <th className="text-left px-4 py-2 font-normal">Instrument</th>
                <th className="text-left px-4 py-2 font-normal">Vault</th>
                <th className="text-left px-4 py-2 font-normal">Account</th>
                <th className="text-left px-4 py-2 font-normal">Reason</th>
                <th className="text-left px-4 py-2 font-normal">Routed To</th>
              </tr>
            </thead>
            <tbody>
              {RECENT_MISSES.map((m, i) => (
                <tr key={i} className={`border-b ${th.row} transition-colors`}>
                  <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{m.time}</td>
                  <td className={`px-4 py-2.5 ${th.body}`}>{m.instrument}</td>
                  <td className={`px-4 py-2.5 ${m.vault === 'Signature' ? 'text-emerald-500' : 'text-violet-400'}`}>{m.vault}</td>
                  <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{m.account}</td>
                  <td className={`px-4 py-2.5 ${th.faint}`}>{m.reason}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold border rounded px-1.5 py-0.5 ${th.lockBadge}`}>
                      🔒 {m.routed}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Vault sync log */}
        <div className={`border rounded-xl ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-medium ${th.heading}`}>VaultSyncWorkflow Log</span>
            <span className={`text-[10px] ${th.faint}`}>Last 7 days</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className={`${th.thCell} border-b ${th.dividerSm}`}>
                <th className="text-left px-4 py-2 font-normal">Date / Time</th>
                <th className="text-left px-4 py-2 font-normal">Event</th>
                <th className="text-right px-4 py-2 font-normal">Sig Keys</th>
                <th className="text-right px-4 py-2 font-normal">PPS Keys</th>
                <th className="text-right px-4 py-2 font-normal">Duration</th>
                <th className="text-right px-4 py-2 font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {SYNC_LOG.map((s, i) => (
                <tr key={i} className={`border-b ${th.row} transition-colors`}>
                  <td className={`px-4 py-2.5 ${th.faint} font-mono`}>{s.time}</td>
                  <td className={`px-4 py-2.5 ${th.body}`}>{s.event}</td>
                  <td className={`px-4 py-2.5 ${th.muted} text-right font-mono`}>{s.signatures.toLocaleString()}</td>
                  <td className={`px-4 py-2.5 ${th.muted} text-right font-mono`}>{s.pps.toLocaleString()}</td>
                  <td className={`px-4 py-2.5 ${th.muted} text-right`}>{s.duration}</td>
                  <td className={`px-4 py-2.5 text-right font-semibold ${SYNC_STATUS_COLOR[s.status]}`}>{s.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      </div>
    </AppShell>
  )
}

function Stat({ label, value, statVal, muted }) {
  return (
    <div>
      <div className={`text-[10px] ${muted} mb-0.5`}>{label}</div>
      <div className={`text-sm font-semibold ${statVal}`}>{value}</div>
    </div>
  )
}
