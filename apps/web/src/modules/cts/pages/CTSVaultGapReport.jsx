/**
 * CTSVaultGapReport — post-banking-hours report of accounts that presented
 * cheques today with no signature in vault, causing mandatory HRQ routing.
 *
 * Ops manager uses this overnight to trigger enrollment for affected accounts
 * so the next clearing session has vault hits for those accounts.
 */
import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import useVaultGaps from '../hooks/useVaultGaps'
import { msg } from '../../../shared/messages'

function nextClearingCountdown() {
  const now = new Date()
  const next = new Date()
  next.setHours(9, 0, 0, 0)
  if (next <= now) next.setDate(next.getDate() + 1)
  const diff = next - now
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  const urgent = h < 2
  return { h, m, urgent, label: msg('UI_VAULTGAPREPORT_H_M', { h, m }) }
}

function fmt(epoch) {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function fmtDate(epoch) {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export default function CTSVaultGapReport() {
  const { isDark } = useTheme()
  const { isDemo } = useBankContext()
  const navigate = useNavigate()
  const today = new Date().toISOString().split('T')[0]
  const [selectedDate, setSelectedDate] = useState(today)
  const clearing = useMemo(() => nextClearingCountdown(), [])
  const [expanded, setExpanded] = useState(null)

  const { data, loading, error, refetch } = useVaultGaps({ date: selectedDate, enabled: !isDemo })

  const th = {
    page:    isDark ? 'bg-navy-950'                    : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8'     : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                     : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                 : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                 : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'                 : 'text-slate-400',
    divider: isDark ? 'border-white/8'                 : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2': 'border-slate-100 hover:bg-slate-50',
    badge:   isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40'
                    : 'bg-amber-50 text-amber-700 border-amber-300',
    none:    isDark ? 'bg-emerald-900/30 text-emerald-300 border-emerald-700/30'
                    : 'bg-emerald-50 text-emerald-700 border-emerald-200',
    input:   isDark ? 'bg-navy-800 border-white/12 text-white focus:border-violet-500'
                    : 'bg-white border-slate-300 text-slate-900 focus:border-violet-500',
    btn:     isDark ? 'bg-violet-600 hover:bg-violet-500 text-white'
                    : 'bg-violet-600 hover:bg-violet-700 text-white',
    sub:     isDark ? 'bg-navy-800/60 border-white/4'  : 'bg-slate-50 border-slate-100',
  }

  const gaps     = data?.gaps ?? []
  const affected = data?.total_accounts_affected ?? 0
  const total    = data?.total_instruments ?? 0

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>{msg('UI_VAULTGAPREPORT_SIGNATURE_VAULT_GAP_REPORT')}</h1>
            <p className={`text-sm mt-0.5 ${th.muted}`}>
             {msg('UI_VAULTGAPREPORT_ACCOUNTS_THAT_PRESENTED_CHEQUES_WITH')}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="date"
              value={selectedDate}
              onChange={e => setSelectedDate(e.target.value)}
              className={`text-sm rounded border px-3 py-1.5 outline-none ${th.input}`}
            />
            <button
              onClick={refetch}
              className={`text-sm px-3 py-1.5 rounded font-medium ${th.btn}`}
            >
             {msg('UI_VAULTGAPREPORT_REFRESH')}
            </button>
          </div>
        </div>

        {/* Urgency countdown */}
        <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border mb-5 ${
          clearing.urgent
            ? isDark ? 'bg-red-900/25 border-red-700/50 text-red-300' : 'bg-red-50 border-red-200 text-red-800'
            : isDark ? 'bg-navy-900 border-white/10 text-slate-300'   : 'bg-white border-slate-200 text-slate-700'
        }`}>
          <div className={`shrink-0 text-2xl font-bold font-mono tabular-nums ${clearing.urgent ? 'text-red-400' : isDark ? 'text-white' : 'text-slate-900'}`}>
            {clearing.label}
          </div>
          <div>
            <div className={`text-xs font-semibold ${clearing.urgent ? '' : (isDark ? 'text-white' : 'text-slate-900')}`}>
              {msg('UI_VAULTGAPREPORT_UNTIL_NEXT_CLEARING_SESSION_09', { value: clearing.urgent ? 'Urgent — ' : '' })}
            </div>
            <div className={`text-xs mt-0.5 opacity-75`}>
             {msg('UI_VAULTGAPREPORT_ENROLL_ACCOUNTS_BELOW_BEFORE_SESSION')}
            </div>
          </div>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-4 mb-5">
          {[
            { label: msg('UI_VAULTGAPREPORT_ACCOUNTS_WITH_VAULT_GAP'),  value: affected, color: affected > 0 ? 'text-amber-400' : 'text-emerald-400' },
            { label: msg('UI_VAULTGAPREPORT_INSTRUMENTS_ROUTED_TO_HRQ'), value: total,   color: total > 0    ? 'text-amber-400' : 'text-emerald-400' },
            { label: msg('UI_VAULTGAPREPORT_CLEARING_DATE'),             value: selectedDate, color: th.heading },
          ].map(({ label, value, color }) => (
            <div key={label} className={`rounded-lg border p-4 ${th.card}`}>
              <div className={`text-xs font-medium uppercase tracking-wide ${th.muted} mb-1`}>{label}</div>
              <div className={`text-2xl font-semibold font-mono ${color}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* Info banner */}
        <div className={`rounded-lg border px-4 py-3 mb-5 text-sm ${isDark ? 'bg-blue-950/40 border-blue-800/40 text-blue-300' : 'bg-blue-50 border-blue-200 text-blue-800'}`}>
          <span className="font-medium">{msg('UI_VAULTGAPREPORT_WHAT_TO_DO')}</span>{msg('UI_VAULTGAPREPORT_FOR_EACH_ACCOUNT_BELOW_OPEN')}
          <span className="font-mono">{new Date(new Date(selectedDate).getTime() + 86400000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}</span>{msg('UI_VAULTGAPREPORT_CLEARING_SESSION')}
        </div>

        {/* Loading / error */}
        {loading && (
          <div className={`text-center py-16 ${th.muted}`}>{msg('UI_VAULTGAPREPORT_LOADING_VAULT_GAP_REPORT')}</div>
        )}
        {error && !loading && (
          <div className={`text-center py-16 text-red-400`}>{msg('UI_VAULTGAPREPORT_ERROR', { error })}</div>
        )}

        {/* No gaps */}
        {!loading && !error && gaps.length === 0 && (
          <div className={`rounded-lg border p-10 text-center ${th.card}`}>
            <div className={`text-3xl mb-2`}>✓</div>
            <div className={`font-medium ${th.heading}`}>{msg('UI_VAULTGAPREPORT_NO_VAULT_GAPS_FOR', { selectedDate })}</div>
            <div className={`text-sm mt-1 ${th.muted}`}>
             {msg('UI_VAULTGAPREPORT_ALL_ACCOUNTS_THAT_PRESENTED_CHEQUES')}
            </div>
          </div>
        )}

        {/* Gap table */}
        {!loading && gaps.length > 0 && (
          <div className={`rounded-lg border overflow-hidden ${th.card}`}>
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b ${th.divider}`}>
                  {[msg('CTS_WF_BUCKETCFG_COL_ACCOUNT'), msg('UI_VAULTGAPREPORT_CHEQUES_AFFECTED'), msg('UI_VAULTGAPREPORT_FIRST_PRESENTED'), msg('UI_VAULTGAPREPORT_LAST_PRESENTED'), msg('UI_COMMON_ACTION')].map(h => (
                    <th key={h} className={`text-left text-xs font-medium uppercase tracking-wide px-4 py-3 ${th.muted}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {gaps.map((gap, idx) => (
                  <>
                    <tr
                      key={gap.account_display}
                      className={`border-b cursor-pointer ${th.row} ${th.divider}`}
                      onClick={() => setExpanded(expanded === idx ? null : idx)}
                    >
                      <td className={`px-4 py-3 font-mono font-medium ${th.heading}`}>
                        {gap.account_display}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded border ${th.badge}`}>
                          {msg('UI_VAULTGAPREPORT_CHEQUE_HRQ', { instrument_count: gap.instrument_count, value: gap.instrument_count > 1 ? 's' : '' })}
                        </span>
                      </td>
                      <td className={`px-4 py-3 font-mono text-xs ${th.body}`}>
                        {fmt(gap.first_seen_at)}
                      </td>
                      <td className={`px-4 py-3 font-mono text-xs ${th.body}`}>
                        {fmt(gap.last_seen_at)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          className={`text-xs px-2.5 py-1 rounded font-medium ${th.btn}`}
                          onClick={e => {
                            e.stopPropagation()
                            navigate(`/cts/vault/upload?account=${encodeURIComponent(gap.account_display)}`)
                          }}
                        >
                         {msg('UI_VAULTGAPREPORT_ENROLL_SIGNATURE')}
                        </button>
                      </td>
                    </tr>

                    {expanded === idx && (
                      <tr key={`${gap.account_display}-detail`}>
                        <td colSpan={5} className={`px-4 py-3 border-b ${th.divider}`}>
                          <div className={`rounded border p-3 ${th.sub}`}>
                            <div className={`text-xs font-medium uppercase tracking-wide ${th.muted} mb-2`}>
                             {msg('UI_VAULTGAPREPORT_INSTRUMENT_IDS_FOR', { account_display: gap.account_display })}
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {gap.instrument_ids.map((id, i) => (
                                <span key={id} className={`font-mono text-xs px-2 py-0.5 rounded ${isDark ? 'bg-white/6 text-slate-300' : 'bg-slate-100 text-slate-600'}`}>
                                  {id}
                                  {gap.micr_codes[i] && (
                                    <span className={`ml-1.5 ${th.faint}`}>
                                     {msg('UI_VAULTGAPREPORT_MICR', { micr_codes: gap.micr_codes[i] })}
                                    </span>
                                  )}
                                </span>
                              ))}
                            </div>
                            <div className={`mt-2 text-xs ${th.muted}`}>
                             {msg('UI_VAULTGAPREPORT_EACH_INSTRUMENT_WILL_REMAIN_IN')}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>

            <div className={`px-4 py-3 text-xs ${th.muted} border-t ${th.divider}`}>
              {msg('UI_VAULTGAPREPORT_ACCOUNT_INSTRUMENT_IN_HRQ_TODAY', { affected, value: affected !== 1 ? 's' : '', total, value2: total !== 1 ? 's' : '', value3: new Date().toLocaleTimeString('en-IN') })}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
