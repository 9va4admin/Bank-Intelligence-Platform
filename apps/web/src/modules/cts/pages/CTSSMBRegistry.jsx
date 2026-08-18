import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { BANK_CONFIG } from '../../../shared/config/bank.config'

// ── Mock data ────────────────────────────────────────────────────────────────

const CBS_CYCLE = ['finacle', 'bancs', 'flexcube', 'finacle', 'bancs']
const MICR_PREFIXES = { KL: '680', TN: '600', KA: '560', MH: '400', AP: '520', default: '500' }

function buildMockSmbs(bankConfig) {
  if (!bankConfig.smbs?.length) return []
  return bankConfig.smbs.map((smb, i) => {
    const micrBase = MICR_PREFIXES[smb.state] ?? MICR_PREFIXES.default
    const isInactive = i === 13
    const returnRate = isInactive ? 0 : [0.04, 0.08, 0.11, 0.21, 0.06, 0.09, 0.03, 0.15][i % 8]
    const softHold = [0.25, 0.22, 0.20, 0.25, 0.22][i % 5]
    return {
      sub_member_id: smb.id,
      bank_name: smb.name,
      micr_prefix: `${micrBase}${String(i + 1).padStart(3, '0')}`,
      cbs_connector: CBS_CYCLE[i % CBS_CYCLE.length],
      is_active: !isInactive,
      return_rate_today: returnRate,
      soft_hold_threshold: softHold,
      hard_stop_threshold: softHold + 0.15,
      shield_status: returnRate * 100 >= softHold * 100 ? 'SOFT_HOLD' : 'CLEAR',
      signature_count: isInactive ? 800 : 1000 + (smb.daily_avg ?? 50) * 20 + i * 137,
      pps_entry_count: isInactive ? 200 : 200 + (smb.daily_avg ?? 50) * 5 + i * 31,
      last_vault_sync_at: `2026-08-11T06:${String((i % 10) + 1).padStart(2, '0')}:${String((i * 7) % 60).padStart(2, '0')}Z`,
      last_sync_status: 'SUCCESS',
      cheques_today: isInactive ? 0 : Math.round((smb.daily_avg ?? 50) * 0.85),
      forwarding_today: isInactive ? 0 : Math.round((smb.daily_avg ?? 50) * 0.83),
      iet_headroom_breaches: 0,
    }
  })
}

const MOCK_SMBS = buildMockSmbs(BANK_CONFIG)

const SHIELD_D = {
  CLEAR:     'bg-emerald-900/40 text-emerald-300 border-emerald-700/50',
  SOFT_HOLD: 'bg-amber-900/40 text-amber-300 border-amber-700/50',
  HARD_STOP: 'bg-red-900/40 text-red-300 border-red-700/50',
}
const SHIELD_L = {
  CLEAR:     'bg-emerald-100 text-emerald-700 border-emerald-300',
  SOFT_HOLD: 'bg-amber-100 text-amber-700 border-amber-300',
  HARD_STOP: 'bg-red-100 text-red-700 border-red-300',
}

const SYNC_D = { SUCCESS: 'text-emerald-400', FAILED: 'text-red-400', RUNNING: 'text-amber-400' }
const SYNC_L = { SUCCESS: 'text-emerald-600', FAILED: 'text-red-600', RUNNING: 'text-amber-600' }


// ── Detail Panel ─────────────────────────────────────────────────────────────

function SMBDetailPanel({ smb, isDark, onClose, onVaultSync }) {
  const th = {
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    kv:      isDark ? 'bg-white/2' : 'bg-slate-50',
  }
  const SHIELD = isDark ? SHIELD_D : SHIELD_L
  const SYNC   = isDark ? SYNC_D   : SYNC_L

  const returnPct = (smb.return_rate_today * 100).toFixed(1)
  const shieldOver = smb.return_rate_today * 100 >= smb.soft_hold_threshold * 100

  return (
    <div className={`mt-5 rounded-xl border p-5 ${th.card}`}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className={`font-semibold ${th.heading}`}>{smb.bank_name}</h2>
          <span className={`font-mono text-xs ${th.muted}`}>{smb.sub_member_id}</span>
        </div>
        <button onClick={onClose} className={`text-xs ${th.muted}`}>✕</button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        {[
          { label: 'Cheques Today', value: smb.cheques_today.toLocaleString() },
          { label: 'Forwarded', value: smb.forwarding_today.toLocaleString() },
          { label: 'Return Rate', value: `${returnPct}%`, warn: shieldOver },
          { label: 'Shield Status', value: smb.shield_status, badge: SHIELD[smb.shield_status] },
        ].map(({ label, value, warn, badge }) => (
          <div key={label} className={`rounded-lg p-3 ${th.kv}`}>
            <div className={`text-[11px] ${th.muted}`}>{label}</div>
            {badge
              ? <span className={`inline-block mt-1 px-2 py-0.5 rounded-full border text-[11px] font-semibold ${badge}`}>{value}</span>
              : <div className={`text-sm font-bold mt-0.5 ${warn ? (isDark ? 'text-amber-300' : 'text-amber-600') : th.heading}`}>{value}</div>
            }
          </div>
        ))}
      </div>

      {/* Vault */}
      <div className={`rounded-lg p-3 ${th.kv} mb-4`}>
        <div className={`text-[11px] font-medium mb-2 ${th.muted}`}>Vault Status</div>
        <div className="flex gap-6 text-xs">
          <div>
            <span className={th.muted}>Signatures: </span>
            <span className={`font-semibold ${th.heading}`}>{smb.signature_count.toLocaleString()}</span>
          </div>
          <div>
            <span className={th.muted}>PPS Entries: </span>
            <span className={`font-semibold ${th.heading}`}>{smb.pps_entry_count.toLocaleString()}</span>
          </div>
          <div>
            <span className={th.muted}>Last Sync: </span>
            <span className={`font-semibold ${SYNC[smb.last_sync_status]}`}>{smb.last_sync_status}</span>
            <span className={`ml-1 ${th.muted}`}>{smb.last_vault_sync_at.substring(11, 19)} UTC</span>
          </div>
          <div>
            <span className={th.muted}>CBS: </span>
            <span className={`font-mono font-semibold ${th.body}`}>{smb.cbs_connector}</span>
          </div>
        </div>
      </div>

      {/* Threshold bars */}
      <div className={`rounded-lg p-3 ${th.kv} mb-4`}>
        <div className={`text-[11px] font-medium mb-2 ${th.muted}`}>Return Rate Shield</div>
        <div className="space-y-2">
          {[
            { label: `Soft Hold (${smb.soft_hold_threshold}%)`, threshold: smb.soft_hold_threshold, color: 'bg-amber-500' },
            { label: `Hard Stop (${smb.hard_stop_threshold}%)`, threshold: smb.hard_stop_threshold, color: 'bg-red-500' },
          ].map(({ label, threshold, color }) => (
            <div key={label} className="flex items-center gap-3 text-xs">
              <span className={`w-28 ${th.muted}`}>{label}</span>
              <div className={`flex-1 h-1.5 rounded-full ${isDark ? 'bg-white/10' : 'bg-slate-200'} relative overflow-hidden`}>
                <div
                  className={`absolute inset-y-0 left-0 ${color} rounded-full`}
                  style={{ width: `${Math.min((smb.return_rate_today * 100) / threshold * 100, 100)}%` }}
                />
              </div>
              <span className={`w-10 text-right ${th.muted}`}>{(smb.return_rate_today * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>

      <div className={`flex gap-3 pt-4 border-t ${th.divider}`}>
        <button
          onClick={() => onVaultSync(smb.sub_member_id)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isDark ? 'bg-violet-900/40 text-violet-300 hover:bg-violet-900/60 border border-violet-700/50' : 'bg-violet-100 text-violet-700 hover:bg-violet-200 border border-violet-300'}`}
        >
          ↻ Trigger Vault Sync
        </button>
        <button
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
        >
          View Forwarding Log →
        </button>
        <button
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${smb.is_active ? (isDark ? 'bg-red-900/30 text-red-300 hover:bg-red-900/50' : 'bg-red-50 text-red-600 hover:bg-red-100') : (isDark ? 'bg-emerald-900/30 text-emerald-300 hover:bg-emerald-900/50' : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100')}`}
        >
          {smb.is_active ? 'Suspend' : 'Reactivate'}
        </button>
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function CTSSMBRegistry() {
  const { bankName, bankIfsc, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  const navigate = useNavigate()
  const [selected, setSelected] = useState(null)
  const [syncingId, setSyncingId] = useState(null)

  const th = {
    page:    isDark ? 'bg-transparent' : 'bg-slate-50',
    card:    isDark ? 'bg-white/3 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3 cursor-pointer transition-colors' : 'border-slate-100 hover:bg-slate-50 cursor-pointer transition-colors',
    btn:     'bg-cyan-600 hover:bg-cyan-500 text-white',
  }
  const SHIELD = isDark ? SHIELD_D : SHIELD_L
  const SYNC   = isDark ? SYNC_D   : SYNC_L

  const totalCheques = MOCK_SMBS.reduce((a, s) => a + s.cheques_today, 0)
  const activeCount  = MOCK_SMBS.filter(s => s.is_active).length
  const holdCount    = MOCK_SMBS.filter(s => s.shield_status !== 'CLEAR').length

  const syncMutation = useMutation({
    mutationFn: async (sub_member_id) => {
      const res = await fetch(`/v1/cts/smb/${encodeURIComponent(sub_member_id)}/vault-sync`, {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) throw new Error('Sync trigger failed')
      return res.json()
    },
    onSuccess: () => setSyncingId(null),
    onError: () => setSyncingId(null),
  })

  function handleVaultSync(sub_member_id) {
    setSyncingId(sub_member_id)
    syncMutation.mutate(sub_member_id)
  }

  if (isSMB) {
    return (
      <AppShell>
        <div className={`flex-1 flex items-center justify-center ${th.page}`}>
          <div className="text-center">
            <div className="text-4xl mb-4">🏦</div>
            <div className={`text-lg font-semibold mb-1 ${th.heading}`}>SB-Only Feature</div>
            <div className={`text-sm ${th.muted}`}>The SMB Registry is managed exclusively by Sponsor Banks. Contact your sponsor bank for registry changes.</div>
          </div>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>SMB Vault & CBS</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Sub-Member Banks sponsored for CTS clearing — vault health, return rate shield, forwarding status</p>
          </div>
          <button
            onClick={() => navigate('/admin/sub-member-banks')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${isDark ? 'bg-white/5 text-slate-300 hover:bg-white/10 border border-white/10' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 border border-slate-300'}`}
          >
            Onboard / Manage → Admin
          </button>
        </div>

        {/* KPI strip */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          {[
            { label: 'Sub-Members', value: MOCK_SMBS.length },
            { label: 'Active', value: activeCount },
            { label: 'Cheques Today', value: totalCheques.toLocaleString() },
            { label: 'Shield Alerts', value: holdCount, warn: holdCount > 0 },
          ].map(({ label, value, warn }) => (
            <div key={label} className={`rounded-xl border px-4 py-3 ${th.card}`}>
              <div className={`text-[11px] ${th.muted}`}>{label}</div>
              <div className={`text-xl font-bold mt-0.5 ${warn ? (isDark ? 'text-amber-300' : 'text-amber-600') : th.heading}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          <table className="w-full text-xs">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Bank', 'MICR Prefix', 'CBS', 'Today', 'Return Rate', 'Vault', 'Last Sync', 'Shield', ''].map(h => (
                  <th key={h} className={`px-4 py-3 text-left font-medium ${th.muted}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MOCK_SMBS.map(smb => (
                <tr
                  key={smb.sub_member_id}
                  className={`border-b ${th.row}`}
                  onClick={() => setSelected(s => s?.sub_member_id === smb.sub_member_id ? null : smb)}
                >
                  <td className="px-4 py-3">
                    <div className={`font-medium ${th.heading}`}>{smb.bank_name}</div>
                    <div className={`text-[10px] font-mono ${th.muted}`}>{smb.sub_member_id}</div>
                  </td>
                  <td className={`px-4 py-3 font-mono font-medium ${th.body}`}>{smb.micr_prefix}</td>
                  <td className={`px-4 py-3 ${th.body}`}>{smb.cbs_connector}</td>
                  <td className={`px-4 py-3 font-medium ${th.heading}`}>{smb.cheques_today}</td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold ${smb.return_rate_today * 100 >= smb.soft_hold_threshold ? (isDark ? 'text-amber-300' : 'text-amber-600') : (isDark ? 'text-emerald-400' : 'text-emerald-600')}`}>
                      {(smb.return_rate_today * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className={`text-[11px] ${th.muted}`}>
                      <span className={isDark ? 'text-slate-300' : 'text-slate-700'}>{smb.signature_count.toLocaleString()}</span> sig /&nbsp;
                      <span className={isDark ? 'text-slate-300' : 'text-slate-700'}>{smb.pps_entry_count.toLocaleString()}</span> PPS
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-medium ${SYNC[smb.last_sync_status]}`}>{smb.last_sync_status}</span>
                    <div className={`text-[10px] ${th.muted}`}>{smb.last_vault_sync_at.substring(0, 10)}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${SHIELD[smb.shield_status]}`}>
                      {smb.shield_status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={e => { e.stopPropagation(); handleVaultSync(smb.sub_member_id) }}
                      className={`text-[11px] transition-colors ${syncingId === smb.sub_member_id ? (isDark ? 'text-violet-300' : 'text-violet-600') : (isDark ? 'text-cyan-400 hover:text-cyan-300' : 'text-cyan-600 hover:text-cyan-700')}`}
                    >
                      {syncingId === smb.sub_member_id ? '↻ syncing…' : '↻ Sync'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selected && (
          <SMBDetailPanel
            smb={selected}
            isDark={isDark}
            onClose={() => setSelected(null)}
            onVaultSync={handleVaultSync}
          />
        )}
      </div>
    </AppShell>
  )
}
