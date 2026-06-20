import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

const VAULT_DATA = [
  { label: 'Signature Vault',  keys: 18_432, hitRate: 99.2, lastSync: '2026-06-19 06:00', status: 'HEALTHY',  redis: 'redis-cts', missAction: 'HUMAN_REVIEW' },
  { label: 'PPS Vault',        keys: 12_817, hitRate: 98.7, lastSync: '2026-06-19 06:00', status: 'HEALTHY',  redis: 'redis-cts', missAction: 'HUMAN_REVIEW' },
]

const RECENT_MISSES = [
  { time: '10:42:31', instrument: 'CHQ-2026-001892', vault: 'Signature', account: '****7821', reason: 'New account — no specimen', routed: 'HUMAN_REVIEW' },
  { time: '09:17:04', instrument: 'CHQ-2026-001744', vault: 'PPS',       account: '****3310', reason: 'PPS not registered',        routed: 'HUMAN_REVIEW' },
  { time: '08:55:12', instrument: 'CHQ-2026-001701', vault: 'Signature', account: '****9902', reason: 'Specimen expired',           routed: 'HUMAN_REVIEW' },
]

const SYNC_LOG = [
  { time: '06:00:03', event: 'VaultSyncWorkflow completed', signatures: 18_432, pps: 12_817, duration: '4m 12s', status: 'OK' },
  { time: 'Yesterday 06:00', event: 'VaultSyncWorkflow completed', signatures: 18_401, pps: 12_790, duration: '4m 08s', status: 'OK' },
]

const STATUS_COLOR = { HEALTHY: 'text-emerald-500', DEGRADED: 'text-amber-500', DOWN: 'text-red-500' }

export default function CTSVaultStatus() {
  const { isDark } = useTheme()

  const th = {
    page:      isDark ? 'bg-transparent' : 'bg-slate-50',
    card:      isDark ? 'bg-white/4 border-white/8' : 'bg-white border-slate-200',
    cardFaint: isDark ? 'bg-navy-900/40 border-white/5' : 'bg-slate-50 border-slate-100',
    heading:   isDark ? 'text-white' : 'text-slate-900',
    body:      isDark ? 'text-slate-300' : 'text-slate-700',
    muted:     isDark ? 'text-slate-400' : 'text-slate-500',
    faint:     isDark ? 'text-slate-600' : 'text-slate-400',
    divider:   isDark ? 'border-white/8' : 'border-slate-200',
    dividerSm: isDark ? 'border-white/5' : 'border-slate-100',
    row:       isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    thCell:    isDark ? 'text-slate-600' : 'text-slate-400',
    redis:     isDark ? 'text-slate-600' : 'text-slate-400',
  }

  usePageHeader({ subtitle: 'Signature Vault · PPS Vault · VaultSyncWorkflow' })

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Vault cards */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {VAULT_DATA.map(v => (
            <div key={v.label} className={`border rounded-xl p-5 ${th.card}`}>
              <div className="flex items-center justify-between mb-4">
                <span className={`text-sm font-medium ${th.heading}`}>{v.label}</span>
                <span className={`text-xs font-semibold ${STATUS_COLOR[v.status]}`}>{v.status}</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Keys loaded" value={v.keys.toLocaleString()} isDark={isDark} />
                <Stat label="Hit rate" value={`${v.hitRate}%`} highlight isDark={isDark} />
                <Stat label="Last sync" value={v.lastSync} isDark={isDark} />
                <Stat label="Miss action" value={v.missAction} warn isDark={isDark} />
              </div>
              <div className={`mt-3 text-[10px] ${th.redis}`}>Redis cluster: {v.redis}</div>
            </div>
          ))}
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
                  <td className={`px-4 py-2.5 ${th.muted}`}>{m.vault}</td>
                  <td className={`px-4 py-2.5 ${th.muted} font-mono`}>{m.account}</td>
                  <td className={`px-4 py-2.5 ${th.faint}`}>{m.reason}</td>
                  <td className="px-4 py-2.5 text-amber-500 font-medium">{m.routed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Sync log */}
        <div className={`border rounded-xl ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider}`}>
            <span className={`text-sm font-medium ${th.heading}`}>VaultSyncWorkflow Log</span>
          </div>
          <div className={`divide-y ${th.dividerSm}`}>
            {SYNC_LOG.map((s, i) => (
              <div key={i} className="px-4 py-3 flex items-center gap-6 text-xs">
                <span className={`${th.faint} font-mono w-36 shrink-0`}>{s.time}</span>
                <span className={`${th.body} flex-1`}>{s.event}</span>
                <span className={th.muted}>Sig: {s.signatures.toLocaleString()}</span>
                <span className={th.muted}>PPS: {s.pps.toLocaleString()}</span>
                <span className={th.muted}>{s.duration}</span>
                <span className="text-emerald-500 font-medium">{s.status}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

function Stat({ label, value, highlight, warn, isDark }) {
  const labelCls = isDark ? 'text-slate-600' : 'text-slate-400'
  return (
    <div>
      <div className={`text-[10px] ${labelCls} mb-0.5`}>{label}</div>
      <div className={`text-sm font-semibold ${highlight ? 'text-emerald-500' : warn ? 'text-amber-500' : isDark ? 'text-slate-200' : 'text-slate-800'}`}>
        {value}
      </div>
    </div>
  )
}
