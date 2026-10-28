/**
 * Bucket configuration (Admin · Configuration).
 *
 * Two parts:
 *   Account lists — the bank-maintained lists that put an account in the CA (corporate) or IP (institution)
 *                   review bucket whatever its CBS account type says.
 *                   GET/POST /v1/cts/admin/bucket-accounts/{CA|IP}, DELETE .../{account_hash}.
 *                   Accounts are stored as keyed hashes plus the last four digits; this screen shows only the last four.
 *   Bucket rules  — the current thresholds and switches (read-only here; changed through Operations config, which is
 *                   maker (ops_manager) / checker (bank_it_admin)). GET /v1/admin/config/thresholds.
 * Roles: ops_manager, bank_it_admin.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

const LISTS = [
  { id: 'CA', label: 'Corporate (CA)', hint: 'Corporate accounts. A cheque needing a human on one of these goes to the CA bucket.' },
  { id: 'IP', label: 'Institution (IP)', hint: 'Institutions and government accounts. These go to the IP bucket.' },
]
const MAX_PER_CALL = 5000

// Settings shown on the Rules tab, in reading order.
const RULE_KEYS = [
  'bucket_routing_enabled', 'bucket_priority', 'bucket_hvc_min_amount', 'bucket_lvc_max_amount',
  'bucket_frequent_min_cheques', 'bucket_frequent_window_days', 'bucket_corporate_account_types',
  'bucket_institution_account_types', 'bucket_overflow_after_minutes', 'sip_review_timeout_minutes',
  'sip_iet_guard_minutes', 'maker_checker_enabled', 'checker_review_timeout_minutes',
]

function parseAccounts(text) {
  return [...new Set(text.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean))]
}

export default function CTSBucketConfig() {
  const { isDark } = useTheme()
  const th = {
    page: isDark ? 'bg-navy-950' : 'bg-slate-50',
    card: isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body: isDark ? 'text-slate-300' : 'text-slate-700',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row: isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    th: isDark ? 'text-slate-500 bg-navy-900/80 text-xs font-medium uppercase tracking-wider'
               : 'text-slate-400 bg-slate-50 text-xs font-medium uppercase tracking-wider',
    input: isDark ? 'bg-navy-950 border-white/10 text-slate-200' : 'bg-white border-slate-300 text-slate-800',
    tab: active => active
      ? (isDark ? 'border-sky-400 text-sky-300' : 'border-sky-600 text-sky-700')
      : (isDark ? 'border-transparent text-slate-400 hover:text-slate-200' : 'border-transparent text-slate-500 hover:text-slate-800'),
  }

  const [tab, setTab] = useState('lists')
  const [bucket, setBucket] = useState('CA')
  const [more, setMore] = useState({ bucket: null, items: [], cursor: null })   // pages after the first
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  async function fetchPage(b, after) {
    const res = await fetch(`/v1/cts/admin/bucket-accounts/${b}?limit=50&cursor=${encodeURIComponent(after)}`, { credentials: 'include' })
    if (!res.ok) throw new Error(res.status === 403 ? 'You do not have access to these lists.' : 'Could not load the list.')
    return res.json()
  }

  const { data: first, isLoading: loading, error: loadError, refetch } = useQuery({
    queryKey: ['bucket-accounts', bucket],
    queryFn: () => fetchPage(bucket, ''),
    retry: false,
  })
  const extra = more.bucket === bucket ? more : { items: [], cursor: null }
  const items = [...(first?.items ?? []), ...extra.items]
  const total = first?.total ?? 0
  const cursor = more.bucket === bucket ? more.cursor : (first?.next_cursor ?? null)
  const shownError = error ?? (loadError ? loadError.message : null)

  async function loadMore() {
    setLoadingMore(true)
    try {
      const page = await fetchPage(bucket, cursor ?? '')
      setMore({ bucket, items: [...extra.items, ...page.items], cursor: page.next_cursor })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingMore(false)
    }
  }

  async function reload() {
    setMore({ bucket: null, items: [], cursor: null })
    await refetch()
  }

  const rulesQuery = useQuery({
    queryKey: ['bucket-rules'],
    enabled: tab === 'rules',
    retry: false,
    queryFn: async () => {
      const r = await fetch('/v1/admin/config/thresholds', { credentials: 'include' })
      const b = r.ok ? await r.json() : { thresholds: [] }
      return Object.fromEntries((b.thresholds ?? []).map(t => [t.config_key, t]))
    },
  })
  const ruleValues = rulesQuery.data ?? (rulesQuery.isError ? {} : null)

  async function add() {
    const accounts = parseAccounts(text)
    if (accounts.length === 0) return
    if (accounts.length > MAX_PER_CALL) { setError(`Add at most ${MAX_PER_CALL} accounts at a time.`); return }
    setBusy(true); setError(null); setResult(null)
    try {
      const res = await fetch(`/v1/cts/admin/bucket-accounts/${bucket}`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_numbers: accounts }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Could not add the accounts.')
      }
      setResult(await res.json()); setText('')
      await reload()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(hash) {
    setBusy(true); setError(null)
    try {
      const res = await fetch(`/v1/cts/admin/bucket-accounts/${bucket}/${encodeURIComponent(hash)}`, { method: 'DELETE', credentials: 'include' })
      if (!res.ok) throw new Error('Could not remove the account.')
      await reload()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function onFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setText(prev => (prev ? `${prev}\n` : '') + String(reader.result))
    reader.readAsText(file)
    e.target.value = ''
  }

  const parsedCount = parseAccounts(text).length
  const current = LISTS.find(l => l.id === bucket)

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <h1 className={`text-lg font-semibold ${th.heading}`}>Bucket configuration</h1>
        <p className={`text-sm mt-0.5 mb-4 ${th.muted}`}>
          Which accounts count as corporate or institution, and the rules that sort cheques into review buckets.
        </p>

        <div className={`flex gap-1 mb-5 border-b ${th.divider}`}>
          {[['lists', 'Account lists'], ['rules', 'Bucket rules']].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`text-sm px-3 py-2 border-b-2 -mb-px font-medium ${th.tab(tab === id)}`}>{label}</button>
          ))}
        </div>

        {tab === 'lists' && (
          <>
            <div className="flex gap-2 mb-4">
              {LISTS.map(l => (
                <button key={l.id} onClick={() => { setResult(null); setError(null); setBucket(l.id) }}
                  className={`text-xs px-3 py-1.5 rounded-full border ${bucket === l.id
                    ? (isDark ? 'border-sky-500 text-sky-300 bg-sky-900/30' : 'border-sky-500 text-sky-700 bg-sky-50')
                    : (isDark ? 'border-white/10 text-slate-400' : 'border-slate-200 text-slate-500')}`}>
                  {l.label}
                </button>
              ))}
            </div>
            <p className={`text-xs mb-3 ${th.muted}`}>{current.hint} Accounts are stored as keyed hashes plus the last four digits, never the number.</p>

            <div className={`border rounded-lg p-4 mb-5 ${th.card}`}>
              <label htmlFor="acct-input" className={`text-xs font-semibold uppercase tracking-wider ${th.muted}`}>
                Add accounts
              </label>
              <textarea id="acct-input" value={text} onChange={e => setText(e.target.value)} rows={4}
                placeholder="Paste account numbers, one per line or separated by commas"
                className={`w-full mt-2 text-sm font-mono rounded border p-2 ${th.input}`} />
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                <button onClick={add} disabled={busy || parsedCount === 0}
                  className={`text-sm px-3 py-1.5 rounded border ${busy || parsedCount === 0 ? 'opacity-50 cursor-not-allowed' : ''} ${isDark ? 'border-sky-600 text-sky-300 hover:bg-sky-900/30' : 'border-sky-600 text-sky-700 hover:bg-sky-50'}`}>
                  Add {parsedCount > 0 ? `${parsedCount} ` : ''}to {bucket}
                </button>
                <label className={`text-xs cursor-pointer ${th.muted}`}>
                  or upload a file <input type="file" accept=".csv,.txt" onChange={onFile} className="hidden" aria-label="Upload account numbers" />
                  <span className="underline">choose file</span>
                </label>
                <span className={`text-xs ${th.muted}`}>Up to {MAX_PER_CALL.toLocaleString('en-IN')} at a time.</span>
              </div>
              {result && (
                <p className={`text-sm mt-3 ${th.body}`} role="status">
                  Added {result.added}. Already on the list: {result.already_present}.
                  {result.invalid.length > 0 && ` Not valid (${result.invalid.length}): entries ending ${result.invalid.map(x => `…${x}`).join(', ')}.`}
                </p>
              )}
              {shownError && <p className="text-sm mt-3 text-red-400" role="alert">{shownError}</p>}
            </div>

            <div className={`border rounded-lg overflow-hidden ${th.card}`}>
              <div className={`px-4 py-2.5 border-b ${th.divider} text-xs font-semibold uppercase tracking-wider ${th.muted}`}>
                {current.label}: {total} account{total === 1 ? '' : 's'}
              </div>
              <table className="w-full border-collapse">
                <thead>
                  <tr>{['Account', 'Added by', 'Added', ''].map(h => (
                    <th key={h} className={`px-4 py-2 text-left border-b ${th.divider} ${th.th}`}>{h}</th>))}</tr>
                </thead>
                <tbody>
                  {items.length === 0 && !loading && (
                    <tr><td colSpan={4} className={`px-4 py-6 text-center text-sm ${th.muted}`}>No accounts on this list yet.</td></tr>
                  )}
                  {items.map(it => (
                    <tr key={it.account_hash} className={`border-b ${th.row}`}>
                      <td className={`px-4 py-2 font-mono text-sm ${th.body}`}>{'•'.repeat(6)}{it.account_last4}</td>
                      <td className={`px-4 py-2 text-sm ${th.muted}`}>{it.added_by}</td>
                      <td className={`px-4 py-2 text-xs ${th.muted}`}>{String(it.added_at).slice(0, 16).replace('T', ' ')}</td>
                      <td className="px-4 py-2 text-right">
                        <button onClick={() => remove(it.account_hash)} disabled={busy}
                          aria-label={`Remove account ending ${it.account_last4}`}
                          className={`text-xs px-2 py-1 rounded border ${isDark ? 'border-red-700/50 text-red-400 hover:bg-red-900/30' : 'border-red-300 text-red-600 hover:bg-red-50'}`}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {cursor && (
                <div className="p-3 text-center">
                  <button onClick={loadMore} disabled={loadingMore} className={`text-xs underline ${th.muted}`}>Load more</button>
                </div>
              )}
            </div>
          </>
        )}

        {tab === 'rules' && (
          <div className={`border rounded-lg overflow-hidden ${th.card}`}>
            <div className={`px-4 py-3 border-b ${th.divider} text-sm ${th.body}`}>
              These values are changed in <Link to="/admin/config/operations" className="text-blue-400 hover:underline">Operations config</Link>,
              where a change is proposed by an ops manager and approved by a bank IT admin.
            </div>
            <table className="w-full border-collapse">
              <thead><tr>{['Setting', 'Current value', 'What it does'].map(h => (
                <th key={h} className={`px-4 py-2 text-left border-b ${th.divider} ${th.th}`}>{h}</th>))}</tr></thead>
              <tbody>
                {ruleValues === null && <tr><td colSpan={3} className={`px-4 py-6 text-center text-sm ${th.muted}`}>Loading…</td></tr>}
                {ruleValues && RULE_KEYS.filter(k => ruleValues[k]).map(k => (
                  <tr key={k} className={`border-b ${th.row}`}>
                    <td className={`px-4 py-2 font-mono text-xs ${th.body}`}>{k}</td>
                    <td className={`px-4 py-2 text-sm font-mono ${th.heading}`}>{ruleValues[k].current_value}</td>
                    <td className={`px-4 py-2 text-xs ${th.muted}`}>{ruleValues[k].description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </AppShell>
  )
}
