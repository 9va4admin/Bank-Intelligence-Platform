import AppShell from '../../../shared/layout/AppShell'

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

const STATUS_COLOR = { HEALTHY: 'text-emerald-400', DEGRADED: 'text-amber-400', DOWN: 'text-red-400' }

export default function CTSVaultStatus() {
  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-navy-950 px-6 py-5">
        <h1 className="text-lg font-semibold text-white mb-5">Vault Status</h1>

        {/* Vault cards */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {VAULT_DATA.map(v => (
            <div key={v.label} className="bg-navy-900 border border-white/8 rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <span className="text-sm font-medium text-white">{v.label}</span>
                <span className={`text-xs font-semibold ${STATUS_COLOR[v.status]}`}>{v.status}</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Keys loaded" value={v.keys.toLocaleString()} />
                <Stat label="Hit rate" value={`${v.hitRate}%`} highlight />
                <Stat label="Last sync" value={v.lastSync} />
                <Stat label="Miss action" value={v.missAction} warn />
              </div>
              <div className="mt-3 text-[10px] text-slate-600">Redis cluster: {v.redis}</div>
            </div>
          ))}
        </div>

        {/* Recent vault misses */}
        <div className="bg-navy-900 border border-white/8 rounded-xl mb-6">
          <div className="px-4 py-3 border-b border-white/8 flex items-center justify-between">
            <span className="text-sm font-medium text-white">Recent Vault Misses</span>
            <span className="text-[10px] text-amber-400 uppercase tracking-wide">All routed → Human Review</span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-600 border-b border-white/5">
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
                <tr key={i} className="border-b border-white/4 hover:bg-white/2">
                  <td className="px-4 py-2.5 text-slate-400 font-mono">{m.time}</td>
                  <td className="px-4 py-2.5 text-slate-300">{m.instrument}</td>
                  <td className="px-4 py-2.5 text-slate-400">{m.vault}</td>
                  <td className="px-4 py-2.5 text-slate-400 font-mono">{m.account}</td>
                  <td className="px-4 py-2.5 text-slate-500">{m.reason}</td>
                  <td className="px-4 py-2.5 text-amber-400 font-medium">{m.routed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Sync log */}
        <div className="bg-navy-900 border border-white/8 rounded-xl">
          <div className="px-4 py-3 border-b border-white/8">
            <span className="text-sm font-medium text-white">VaultSyncWorkflow Log</span>
          </div>
          <div className="divide-y divide-white/5">
            {SYNC_LOG.map((s, i) => (
              <div key={i} className="px-4 py-3 flex items-center gap-6 text-xs">
                <span className="text-slate-600 font-mono w-36 shrink-0">{s.time}</span>
                <span className="text-slate-300 flex-1">{s.event}</span>
                <span className="text-slate-500">Sig: {s.signatures.toLocaleString()}</span>
                <span className="text-slate-500">PPS: {s.pps.toLocaleString()}</span>
                <span className="text-slate-500">{s.duration}</span>
                <span className="text-emerald-400 font-medium">{s.status}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  )
}

function Stat({ label, value, highlight, warn }) {
  return (
    <div>
      <div className="text-[10px] text-slate-600 mb-0.5">{label}</div>
      <div className={`text-sm font-semibold ${highlight ? 'text-emerald-400' : warn ? 'text-amber-400' : 'text-slate-200'}`}>
        {value}
      </div>
    </div>
  )
}
