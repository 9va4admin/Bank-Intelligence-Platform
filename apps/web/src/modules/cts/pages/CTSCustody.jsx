/**
 * CTSCustody — custody of original instruments.
 *
 * Originals stay at the branch for a while (late ones are flagged), are handed over in a batch with a courier reference,
 * are received at central storage by a different person (anything missing is flagged), are kept until the retention
 * period ends, and are then disposed of. Hold days and retention years are bank configuration, not screen constants.
 *
 * Tabs: At branch · In transit · Stored · Due for disposal. Branch staff see their own branches; managers see all.
 */
import { useState, useEffect, useCallback } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { csrfHeader } from '../../../shared/api/csrf'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const BASE = `${API_BASE}/v1/cts/custody`

async function call(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.method && options.method !== 'GET' ? csrfHeader() : {}) },
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
  return body
}

const TABS = [
  ['pending', 'At branch'],
  ['transit', 'In transit'],
  ['due', 'Due for disposal'],
]

function Table({ th, head, children }) {
  return (
    <table className="w-full text-sm">
      <thead><tr className={`text-left text-xs uppercase ${th.muted} border-b ${th.divider}`}>
        {head.map(h => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
      <tbody>{children}</tbody>
    </table>
  )
}
function Empty({ th, text }) {
  return <p className={`px-3 py-8 text-sm text-center ${th.muted}`}>{text}</p>
}


export default function CTSCustody() {
  const { isDark } = useTheme()
  const th = {
    page: isDark ? 'bg-navy-950' : 'bg-slate-50',
    card: isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body: isDark ? 'text-slate-300' : 'text-slate-700',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row: isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    input: isDark ? 'bg-navy-950 border-white/10 text-slate-200' : 'bg-white border-slate-300 text-slate-800',
    btn: isDark ? 'bg-sky-600 hover:bg-sky-500 text-white' : 'bg-sky-600 hover:bg-sky-700 text-white',
    warn: isDark ? 'text-amber-300' : 'text-amber-700',
  }

  const [tab, setTab] = useState('pending')
  const [pending, setPending] = useState({ items: [], hold_days: 7 })
  const [transit, setTransit] = useState([])
  const [due, setDue] = useState([])
  const [picked, setPicked] = useState({})
  const [courier, setCourier] = useState('')
  const [location, setLocation] = useState('')
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const [p, t, d] = await Promise.allSettled([
      call('/pending'), call('/handovers?status=IN_TRANSIT'), call('/due-for-disposal'),
    ])
    if (p.status === 'fulfilled') setPending(p.value)
    if (t.status === 'fulfilled') setTransit(t.value.handovers ?? [])
    if (d.status === 'fulfilled') setDue(d.value.items ?? [])
  }, [])
  useEffect(() => { load() }, [load])

  const act = async (fn, okText) => {
    setBusy(true); setMsg(null)
    try { await fn(); setMsg({ ok: true, text: okText }); await load() }
    catch (e) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy(false) }
  }

  const chosen = pending.items.filter(i => picked[i.instrument_id])
  const handOver = () => {
    // One batch is one branch: a handover from several branches would be several parcels.
    const branches = [...new Set(chosen.map(i => i.branch_id))]
    if (branches.length !== 1) { setMsg({ ok: false, text: 'Pick items from one branch for each batch' }); return }
    act(async () => {
      await call('/handovers', { method: 'POST', body: JSON.stringify({
        branch_id: branches[0], instrument_ids: chosen.map(i => i.instrument_id), courier_ref: courier || null }) })
      setPicked({}); setCourier('')
    }, `Handed over ${chosen.length} original${chosen.length === 1 ? '' : 's'}`)
  }
  const receive = (h) => act(async () => {
    const r = await call(`/handovers/${encodeURIComponent(h.handover_id)}/receive`, {
      method: 'POST', body: JSON.stringify({ location }) })
    if (r.missing.length) throw new Error(`Received with ${r.missing.length} missing — flagged`)
  }, `Batch ${h.handover_id} received`)
  const dispose = (i) => act(() => call(`/instruments/${encodeURIComponent(i.instrument_id)}/dispose`, {
    method: 'POST', body: JSON.stringify({ reason: 'Retention period ended' }) }), `Disposed ${i.instrument_id}`)

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <h1 className={`text-lg font-semibold ${th.heading}`}>Original instruments — custody</h1>
        <p className={`text-sm mt-1 mb-4 ${th.muted}`}>
          Kept at the branch up to {pending.hold_days} days, then handed over to central storage, received by someone else, and kept until retention ends.
        </p>

        <div className="flex gap-2 mb-4">
          {TABS.map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)}
              className={`px-3 py-1.5 text-sm rounded-md border ${tab === k ? th.btn : `${th.card} ${th.body}`}`}>
              {label}{k === 'pending' ? ` (${pending.items.length})` : k === 'transit' ? ` (${transit.length})` : ` (${due.length})`}
            </button>
          ))}
        </div>

        {msg && <p role="status" className={`mb-3 text-sm ${msg.ok ? 'text-emerald-500' : 'text-red-500'}`}>{msg.text}</p>}

        <div className={`rounded-lg border ${th.card}`}>
          {tab === 'pending' && (
            <>
              <div className={`flex items-center gap-3 p-3 border-b ${th.divider}`}>
                <input value={courier} onChange={e => setCourier(e.target.value)} placeholder="Courier / docket reference"
                  className={`px-2 py-1.5 text-sm rounded border ${th.input}`} />
                <button disabled={busy || chosen.length === 0} onClick={handOver}
                  className={`px-3 py-1.5 text-sm rounded-md disabled:opacity-40 ${th.btn}`}>
                  Hand over {chosen.length || ''} selected
                </button>
              </div>
              {pending.items.length === 0 ? <Empty th={th} text="No originals waiting at a branch" /> : (
                <Table th={th} head={['', 'Instrument', 'Branch', 'Payee', 'Amount', 'Held']}>
                  {pending.items.map(i => (
                    <tr key={i.instrument_id} className={`border-b ${th.row} ${th.body}`}>
                      <td className="px-3 py-2"><input type="checkbox" aria-label={`Select ${i.instrument_id}`}
                        checked={!!picked[i.instrument_id]}
                        onChange={e => setPicked(p => ({ ...p, [i.instrument_id]: e.target.checked }))} /></td>
                      <td className="px-3 py-2 font-mono text-xs">{i.cheque_number ?? i.instrument_id}</td>
                      <td className="px-3 py-2">{i.branch_id}</td>
                      <td className="px-3 py-2">{i.payee_display}</td>
                      <td className="px-3 py-2">{i.amount_range}</td>
                      <td className={`px-3 py-2 ${i.overdue ? th.warn : ''}`}>
                        {i.age_days.toFixed(1)} d{i.overdue ? ' — overdue' : ''}</td>
                    </tr>
                  ))}
                </Table>
              )}
            </>
          )}

          {tab === 'transit' && (
            <>
              <div className={`flex items-center gap-3 p-3 border-b ${th.divider}`}>
                <input value={location} onChange={e => setLocation(e.target.value)} placeholder="Storage location (box / shelf)"
                  className={`px-2 py-1.5 text-sm rounded border ${th.input}`} />
                <span className={`text-xs ${th.muted}`}>The person who sent a batch cannot receive it.</span>
              </div>
              {transit.length === 0 ? <Empty th={th} text="Nothing in transit" /> : (
                <Table th={th} head={['Batch', 'Branch', 'Items', 'Courier', 'Sent by', '']}>
                  {transit.map(h => (
                    <tr key={h.handover_id} className={`border-b ${th.row} ${th.body}`}>
                      <td className="px-3 py-2 font-mono text-xs">{h.handover_id}</td>
                      <td className="px-3 py-2">{h.branch_id}</td>
                      <td className="px-3 py-2">{h.item_count}</td>
                      <td className="px-3 py-2">{h.courier_ref ?? '—'}</td>
                      <td className="px-3 py-2">{h.created_by}</td>
                      <td className="px-3 py-2 text-right">
                        <button disabled={busy || !location} onClick={() => receive(h)}
                          className={`px-3 py-1 text-xs rounded-md disabled:opacity-40 ${th.btn}`}>Receive</button>
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </>
          )}

          {tab === 'due' && (
            due.length === 0 ? <Empty th={th} text="Nothing is due for disposal" /> : (
              <Table th={th} head={['Instrument', 'Branch', 'Location', 'Retention ended', '']}>
                {due.map(i => (
                  <tr key={i.instrument_id} className={`border-b ${th.row} ${th.body}`}>
                    <td className="px-3 py-2 font-mono text-xs">{i.instrument_id}</td>
                    <td className="px-3 py-2">{i.branch_id}</td>
                    <td className="px-3 py-2">{i.location ?? '—'}</td>
                    <td className="px-3 py-2">{i.retention_until}</td>
                    <td className="px-3 py-2 text-right">
                      <button disabled={busy} onClick={() => dispose(i)}
                        className={`px-3 py-1 text-xs rounded-md disabled:opacity-40 ${th.btn}`}>Dispose</button>
                    </td>
                  </tr>
                ))}
              </Table>
            )
          )}
        </div>
      </div>
    </AppShell>
  )
}
