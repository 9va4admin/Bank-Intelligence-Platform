import { useMemo } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import useDemoData from '../../../shared/hooks/useDemoData'
import { useTheme } from '../../../shared/theme/ThemeContext'
import useVaultHealth from '../hooks/useVaultHealth'
import useVaultMisses from '../hooks/useVaultMisses'

// ── Data ───────────────────────────────────────────────────────────────────

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
  { time: '10:42:31', instrument: 'CHQ-2026-001892', vault: 'Signature', account: '****7821', reason: 'New account — no specimen',      routed: 'HUMAN_REVIEW' },
  { time: '10:11:08', instrument: 'CHQ-2026-001871', vault: 'PPS',       account: '****5543', reason: 'PPS limit exhausted',            routed: 'HUMAN_REVIEW' },
  { time: '09:58:22', instrument: 'CHQ-2026-001855', vault: 'Signature', account: '****0014', reason: 'Specimen update in progress',    routed: 'HUMAN_REVIEW' },
  { time: '09:44:47', instrument: 'CHQ-2026-001843', vault: 'PPS',       account: '****2287', reason: 'PPS not registered',             routed: 'HUMAN_REVIEW' },
  { time: '09:17:04', instrument: 'CHQ-2026-001744', vault: 'PPS',       account: '****3310', reason: 'PPS not registered',             routed: 'HUMAN_REVIEW' },
  { time: '09:02:39', instrument: 'CHQ-2026-001722', vault: 'Signature', account: '****6641', reason: 'Specimen expired',               routed: 'HUMAN_REVIEW' },
  { time: '08:55:12', instrument: 'CHQ-2026-001701', vault: 'Signature', account: '****9902', reason: 'Specimen expired',               routed: 'HUMAN_REVIEW' },
  { time: '08:33:50', instrument: 'CHQ-2026-001689', vault: 'PPS',       account: '****1128', reason: 'CBS sync lag — key absent',      routed: 'HUMAN_REVIEW' },
  { time: '07:51:18', instrument: 'CHQ-2026-001654', vault: 'Signature', account: '****8876', reason: 'Multi-signatory — partial load', routed: 'HUMAN_REVIEW' },
  { time: '07:22:03', instrument: 'CHQ-2026-001630', vault: 'PPS',       account: '****4499', reason: 'Cheque series mismatch',         routed: 'HUMAN_REVIEW' },
]
const SB_SYNC_LOG = [
  { time: 'Jun 19 06:00:03', event: 'VaultSyncWorkflow completed',         signatures: 18_432, pps: 12_817, duration: '4m 12s', status: 'OK' },
  { time: 'Jun 18 06:00:07', event: 'VaultSyncWorkflow completed',         signatures: 18_401, pps: 12_790, duration: '4m 08s', status: 'OK' },
  { time: 'Jun 17 06:00:11', event: 'VaultSyncWorkflow completed',         signatures: 18_388, pps: 12_774, duration: '4m 21s', status: 'OK' },
  { time: 'Jun 16 06:00:02', event: 'VaultSyncWorkflow completed',         signatures: 18_362, pps: 12_751, duration: '4m 05s', status: 'OK' },
  { time: 'Jun 15 06:03:45', event: 'VaultSyncWorkflow retried (CBS lag)', signatures: 18_341, pps: 12_730, duration: '6m 38s', status: 'WARN' },
  { time: 'Jun 14 06:00:09', event: 'VaultSyncWorkflow completed',         signatures: 18_320, pps: 12_715, duration: '4m 11s', status: 'OK' },
  { time: 'Jun 13 06:00:04', event: 'VaultSyncWorkflow completed',         signatures: 18_298, pps: 12_698, duration: '4m 02s', status: 'OK' },
]
const SMB_SYNC_LOG = [
  { time: 'Jun 19 06:00:05', event: 'VaultSyncWorkflow completed',         signatures: 2_841, pps: 1_924, duration: '0m 48s', status: 'OK' },
  { time: 'Jun 18 06:00:09', event: 'VaultSyncWorkflow completed',         signatures: 2_838, pps: 1_921, duration: '0m 46s', status: 'OK' },
  { time: 'Jun 17 06:00:08', event: 'VaultSyncWorkflow completed',         signatures: 2_831, pps: 1_918, duration: '0m 47s', status: 'OK' },
  { time: 'Jun 16 06:00:04', event: 'VaultSyncWorkflow completed',         signatures: 2_829, pps: 1_915, duration: '0m 45s', status: 'OK' },
  { time: 'Jun 15 06:01:12', event: 'VaultSyncWorkflow retried (CBS lag)', signatures: 2_822, pps: 1_911, duration: '1m 03s', status: 'WARN' },
  { time: 'Jun 14 06:00:06', event: 'VaultSyncWorkflow completed',         signatures: 2_817, pps: 1_908, duration: '0m 44s', status: 'OK' },
  { time: 'Jun 13 06:00:03', event: 'VaultSyncWorkflow completed',         signatures: 2_810, pps: 1_903, duration: '0m 43s', status: 'OK' },
]

// ── Helpers ────────────────────────────────────────────────────────────────

const SYNC_STATUS_COLOR = { OK: 'text-emerald-500', WARN: 'text-amber-500', ERROR: 'text-red-500' }

function nextSyncIn() {
  const now = new Date()
  const next = new Date()
  next.setHours(6, 0, 0, 0)
  if (next <= now) next.setDate(next.getDate() + 1)
  const diff = next - now
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  return `${h}h ${m}m`
}

// ── Sub-components ─────────────────────────────────────────────────────────

function HealthRing({ rate, label, color, isDark }) {
  const r = 34
  const circ = 2 * Math.PI * r
  const dash = (Math.min(100, Math.max(0, rate)) / 100) * circ
  const track = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.08)'

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: 88, height: 88 }}>
        <svg viewBox="0 0 88 88" style={{ transform: 'rotate(-90deg)' }} className="w-full h-full">
          <circle cx="44" cy="44" r={r} fill="none" stroke={track} strokeWidth="7" />
          <circle
            cx="44" cy="44" r={r} fill="none"
            stroke={color} strokeWidth="7" strokeLinecap="round"
            strokeDasharray={`${dash.toFixed(2)} ${circ.toFixed(2)}`}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-bold tabular-nums" style={{ color }}>{rate}%</span>
        </div>
      </div>
      <span className={`text-[11px] font-medium ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{label}</span>
    </div>
  )
}

function TrendBars({ data, field, color }) {
  const W = 14, G = 2, H = 44
  const totalW = data.length * (W + G) - G

  return (
    <svg
      viewBox={`0 0 ${totalW} ${H}`}
      className="w-full"
      style={{ height: H }}
      preserveAspectRatio="none"
    >
      {data.map((d, i) => {
        const v = d[field]
        const pct = Math.max(0, (v - 96) / (100 - 96))
        const h = Math.max(2, pct * H)
        const fill = v >= 99 ? color : v >= 98.5 ? '#f59e0b' : '#ef4444'
        return (
          <g key={i}>
            <rect x={i * (W + G)} y={0} width={W} height={H} fill="rgba(128,128,128,0.1)" rx="2" />
            <rect x={i * (W + G)} y={H - h} width={W} height={h} fill={fill} rx="2" opacity="0.85" />
          </g>
        )
      })}
    </svg>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function CTSVaultStatus() {
  const { isSMB, isDemo } = useBankContext()
  const { isDark } = useTheme()
  const VAULT_DATA_MOCK = useDemoData(isSMB ? SMB_VAULT_DATA : SB_VAULT_DATA)
  const SYNC_LOG        = useDemoData(isSMB ? SMB_SYNC_LOG   : SB_SYNC_LOG)
  const countdown       = useMemo(() => nextSyncIn(), [])

  const { health: liveHealth } = useVaultHealth({ pollEnabled: !isDemo })
  const { misses: liveMisses } = useVaultMisses({ pollEnabled: !isDemo })

  // Vault card data: live overrides mock when available
  const VAULT_DATA = useMemo(() => {
    if (isDemo || !liveHealth) return VAULT_DATA_MOCK
    return [
      {
        label: 'Signature Vault',
        keys: liveHealth.sig_key_count,
        hitRate: 99.2,  // hit rate computed separately; keep mock for chart
        lastSync: liveHealth.sig_last_sync || VAULT_DATA_MOCK[0]?.lastSync,
        status: liveHealth.sig_status,
        redis: 'redis-cts',
        missAction: liveHealth.miss_action,
      },
      {
        label: 'PPS Vault',
        keys: liveHealth.pps_key_count,
        hitRate: 98.7,
        lastSync: liveHealth.pps_last_sync || VAULT_DATA_MOCK[1]?.lastSync,
        status: liveHealth.pps_status,
        redis: 'redis-cts',
        missAction: liveHealth.miss_action,
      },
    ]
  }, [isDemo, liveHealth, VAULT_DATA_MOCK])

  const DISPLAY_MISSES = useMemo(() => {
    if (isDemo || !liveMisses || liveMisses.length === 0) return RECENT_MISSES
    return liveMisses.map(m => ({
      time: m.event_time ? new Date(m.event_time).toLocaleTimeString('en-IN', { hour12: false }) : '—',
      instrument: m.instrument_id,
      vault: m.vault_type === 'SIGNATURE' ? 'Signature' : 'PPS',
      account: `****${m.account_last4}`,
      reason: m.miss_reason,
      routed: m.routed_to,
    }))
  }, [isDemo, liveMisses])

  usePageHeader({ subtitle: 'Signature Vault · PPS Vault · VaultSyncWorkflow' })

  const th = {
    page:      isDark ? 'bg-navy-950 text-white'                      : 'bg-slate-50 text-slate-900',
    card:      isDark ? 'bg-white/5 border-white/8'                   : 'bg-white border-slate-200',
    hero:      isDark ? 'bg-navy-900 border-white/10'                 : 'bg-white border-slate-200',
    heading:   isDark ? 'text-white'                                   : 'text-slate-900',
    body:      isDark ? 'text-slate-300'                               : 'text-slate-700',
    muted:     isDark ? 'text-slate-400'                               : 'text-slate-500',
    faint:     isDark ? 'text-slate-500'                               : 'text-slate-400',
    divider:   isDark ? 'border-white/8'                               : 'border-slate-200',
    divSm:     isDark ? 'border-white/5'                               : 'border-slate-100',
    divideX:   isDark ? 'divide-white/10'                              : 'divide-slate-200',
    row:       isDark ? 'border-white/5 hover:bg-white/3'              : 'border-slate-100 hover:bg-slate-50',
    thCell:    isDark ? 'text-slate-500'                               : 'text-slate-400',
    lockBadge: isDark ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                      : 'bg-amber-50 text-amber-700 border-amber-200',
    alert:     isDark ? 'bg-amber-900/20 border-amber-700/40 text-amber-300'
                      : 'bg-amber-50 border-amber-200 text-amber-800',
  }

  const sig       = VAULT_DATA[0]
  const pps       = VAULT_DATA[1]
  const lastSync  = SYNC_LOG?.[0]
  const missCount = DISPLAY_MISSES.length
  const chartData = [...VAULT_METRICS].reverse()

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

        {/* ── Hero: three-panel command strip ── */}
        <div className={`grid grid-cols-3 divide-x border rounded-xl overflow-hidden mb-5 ${th.hero} ${th.divideX}`}>

          {/* Signature vault */}
          <div className="flex flex-col items-center justify-center py-7 px-6 gap-2">
            <HealthRing rate={sig?.hitRate ?? 0} label="Signature Hit Rate" color="#10b981" isDark={isDark} />
            <div className="text-center mt-1">
              <span className={`text-xl font-bold font-mono ${th.heading}`}>{sig?.keys?.toLocaleString()}</span>
              <span className={`text-xs ml-1.5 ${th.muted}`}>keys loaded</span>
            </div>
            <span className="text-xs font-semibold text-emerald-500">{sig?.status}</span>
          </div>

          {/* PPS vault */}
          <div className="flex flex-col items-center justify-center py-7 px-6 gap-2">
            <HealthRing rate={pps?.hitRate ?? 0} label="PPS Hit Rate" color="#8b5cf6" isDark={isDark} />
            <div className="text-center mt-1">
              <span className={`text-xl font-bold font-mono ${th.heading}`}>{pps?.keys?.toLocaleString()}</span>
              <span className={`text-xs ml-1.5 ${th.muted}`}>keys loaded</span>
            </div>
            <span className="text-xs font-semibold text-emerald-500">{pps?.status}</span>
          </div>

          {/* Next sync countdown */}
          <div className="flex flex-col items-center justify-center py-7 px-6 gap-3">
            <div className={`text-[10px] uppercase tracking-widest font-semibold ${th.muted}`}>Next Sync</div>
            <div className={`text-4xl font-bold font-mono tabular-nums ${th.heading}`}>{countdown}</div>
            <div className={`text-xs ${th.muted}`}>Daily at 06:00 AM IST</div>
            {lastSync && (
              <div className={`text-xs ${th.faint}`}>
                Last run: <span className="font-mono">{lastSync.duration}</span>
                {' · '}
                <span className={SYNC_STATUS_COLOR[lastSync.status]}>{lastSync.status}</span>
              </div>
            )}
            <div className={`flex items-center gap-1.5 text-[10px] font-semibold border rounded px-2 py-0.5 ${th.lockBadge}`}>
              🔒 Miss → HUMAN_REVIEW
            </div>
          </div>
        </div>

        {/* ── Vault miss alert (surfaced above chart) ── */}
        {missCount > 0 && (
          <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border mb-5 ${th.alert}`}>
            <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
              <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
            </svg>
            <span className="font-semibold">{missCount} vault miss{missCount !== 1 ? 'es' : ''} today</span>
            <span className="text-xs opacity-75">All instruments automatically routed to Human Review Queue — see table below</span>
          </div>
        )}

        {/* ── Hit rate trend chart ── */}
        <div className={`border rounded-xl p-5 mb-5 ${th.card}`}>
          <div className={`text-sm font-semibold ${th.heading} mb-5`}>Hit Rate — Last 12 Hours</div>

          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shrink-0" />
                <span className={`text-xs font-medium ${th.body}`}>Signature Vault</span>
              </div>
              <TrendBars data={chartData} field="sig" color="#10b981" />
              <div className="flex justify-between mt-2">
                <span className={`text-[9px] font-mono ${th.faint}`}>← 23:00</span>
                <span className={`text-[9px] font-mono ${th.faint}`}>10:00 →</span>
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="w-2.5 h-2.5 rounded-full bg-violet-500 shrink-0" />
                <span className={`text-xs font-medium ${th.body}`}>PPS Vault</span>
              </div>
              <TrendBars data={chartData} field="pps" color="#8b5cf6" />
              <div className="flex justify-between mt-2">
                <span className={`text-[9px] font-mono ${th.faint}`}>← 23:00</span>
                <span className={`text-[9px] font-mono ${th.faint}`}>10:00 →</span>
              </div>
            </div>
          </div>

          <div className={`flex items-center flex-wrap gap-5 mt-5 pt-4 border-t ${th.divSm}`}>
            {[
              { color: '#10b981', range: '≥ 99%',      label: 'On target' },
              { color: '#f59e0b', range: '98.5–99%',   label: 'Watch' },
              { color: '#ef4444', range: '< 98.5%',    label: 'Alert' },
            ].map(({ color, range, label }) => (
              <div key={range} className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: color }} />
                <span className={`text-[10px] ${th.faint}`}>{range} · {label}</span>
              </div>
            ))}
            <span className={`ml-auto text-[10px] ${th.faint}`}>Bar height scaled 96–100%</span>
          </div>
        </div>

        {/* ── Recent vault misses ── */}
        <div className={`border rounded-xl mb-5 ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-semibold ${th.heading}`}>Recent Vault Misses</span>
            <span className="text-[10px] text-amber-500 uppercase tracking-wide font-semibold">All → Human Review</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className={`${th.thCell} border-b ${th.divSm}`}>
                  {['Time', 'Instrument', 'Vault', 'Account', 'Reason', 'Routed To'].map(h => (
                    <th key={h} className="text-left px-4 py-2 font-normal">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {DISPLAY_MISSES.map((m, i) => (
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
        </div>

        {/* ── Sync log ── */}
        <div className={`border rounded-xl ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
            <span className={`text-sm font-semibold ${th.heading}`}>VaultSyncWorkflow Log</span>
            <span className={`text-[10px] ${th.faint}`}>Last 7 days</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className={`${th.thCell} border-b ${th.divSm}`}>
                  <th className="text-left px-4 py-2 font-normal">Date / Time</th>
                  <th className="text-left px-4 py-2 font-normal">Event</th>
                  <th className="text-right px-4 py-2 font-normal">Sig Keys</th>
                  <th className="text-right px-4 py-2 font-normal">PPS Keys</th>
                  <th className="text-right px-4 py-2 font-normal">Duration</th>
                  <th className="text-right px-4 py-2 font-normal">Status</th>
                </tr>
              </thead>
              <tbody>
                {(SYNC_LOG ?? []).map((s, i) => (
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

      </div>
    </AppShell>
  )
}
