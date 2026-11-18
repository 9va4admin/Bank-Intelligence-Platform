/**
 * Silences: planned quiet periods so maintenance does not page people. Alerts are still recorded while a silence is in force; only the notifications are held back.
 * Shows what is in force, what is coming up and what ended recently, and lets a person create or cancel one.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, useTh, when } from '../ui'

const PRIORITY_KEY = { P0: 'UI_ALERTING_SL_P0', P1: 'UI_ALERTING_SL_P1', P2: 'UI_ALERTING_SL_P2', P3: 'UI_ALERTING_SL_P3' }
const PRIORITIES = ['P0', 'P1', 'P2', 'P3']

function CreateForm({ isDark, onCreated }) {
  const th = useTh(isDark)
  const [component, setComponent] = useState('')
  const [chosen, setChosen] = useState(['P1', 'P2'])
  const [hours, setHours] = useState('2')
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const toggle = (p) => setChosen(c => (c.includes(p) ? c.filter(x => x !== p) : [...c, p]))
  const submit = async () => {
    setBusy(true); setProblem(null)
    try {
      const ends_at = new Date(Date.now() + Number(hours || 0) * 3600 * 1000).toISOString()
      await api('/v1/admin/alert-silences', { method: 'POST', body: { component: component.trim(), priorities: chosen, ends_at, reason: reason.trim() } })
      setReason('')
      onCreated(msg('UI_ALERTING_SL_CREATED'))
    } catch (e) {
      setProblem(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card isDark={isDark} className="p-4 mb-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field isDark={isDark} label={msg('UI_ALERTING_SL_COMPONENT')}><input value={component} onChange={e => setComponent(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 w-44 ${th.input}`} /></Field>
        <fieldset className="flex items-center gap-3 pb-1">
          {PRIORITIES.map(p => (
            <label key={p} className={`flex items-center gap-1 text-xs ${th.body}`}>
              <input type="checkbox" checked={chosen.includes(p)} onChange={() => toggle(p)} />{msg(PRIORITY_KEY[p])}
            </label>
          ))}
        </fieldset>
        <Field isDark={isDark} label={msg('UI_ALERTING_SL_HOURS')}><input value={hours} onChange={e => setHours(e.target.value)} inputMode="numeric" className={`text-xs rounded-lg border px-2 py-1.5 w-20 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_SL_REASON')}><input value={reason} onChange={e => setReason(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 w-72 ${th.input}`} /></Field>
        <Button isDark={isDark} kind="primary" disabled={busy} onClick={submit}>{msg('UI_ALERTING_SL_CREATE')}</Button>
      </div>
      {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
    </Card>
  )
}

function Table({ isDark, title, items, cancellable, onCancel }) {
  const th = useTh(isDark)
  if (!items.length) return null
  return (
    <div className="mb-5">
      <h2 className={`mb-2 text-sm font-semibold ${th.heading}`}>{title}</h2>
      <Card isDark={isDark} className="overflow-hidden">
        <table className="w-full text-xs">
          <tbody>
            {items.map(s => (
              <tr key={s.silence_id} className={`border-b ${th.row}`}>
                <td className={`px-3 py-2 font-semibold ${th.heading}`}>{s.component || msg('UI_ALERTING_SL_ALL')}</td>
                <td className={`px-3 py-2 ${th.body}`}>{s.priorities.map(p => msg(PRIORITY_KEY[p] ?? PRIORITY_KEY.P3)).join(', ')}</td>
                <td className={`px-3 py-2 ${th.body}`}>{s.reason}</td>
                <td className={`px-3 py-2 ${th.muted}`}>{when(s.starts_at)} - {when(s.ends_at)}</td>
                <td className={`px-3 py-2 ${th.muted}`}>{msg('UI_ALERTING_SL_BY', { who: s.created_by })}</td>
                <td className="px-3 py-2 text-right">{cancellable && <Button isDark={isDark} kind="danger" onClick={() => onCancel(s.silence_id)}>{msg('UI_ALERTING_SL_CANCEL')}</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

export default function Silences() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const { data, error, loading, reload } = useLoad('/v1/admin/alert-silences')
  const [notice, setNotice] = useState(null)
  const [problem, setProblem] = useState(null)
  const cancel = async (id) => {
    setProblem(null)
    try { await api(`/v1/admin/alert-silences/${id}`, { method: 'DELETE' }); reload() } catch (e) { setProblem(e.message) }
  }
  const inForce = data?.in_force ?? []
  const upcoming = data?.upcoming ?? []
  const recent = data?.recent ?? []
  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_SL_TITLE')} subtitle={msg('UI_ALERTING_SL_SUBTITLE')} />
        <CreateForm isDark={isDark} onCreated={(text) => { setNotice(text); reload() }} />
        {notice && <p role="status" className={`mb-2 text-xs ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{notice}</p>}
        {problem && <p role="alert" className="mb-2 text-xs text-red-500">{problem}</p>}
        <ErrorNote isDark={isDark} error={error} onRetry={reload} />
        <Table isDark={isDark} title={msg('UI_ALERTING_SL_IN_FORCE')} items={inForce} cancellable onCancel={cancel} />
        <Table isDark={isDark} title={msg('UI_ALERTING_SL_UPCOMING')} items={upcoming} cancellable onCancel={cancel} />
        <Table isDark={isDark} title={msg('UI_ALERTING_SL_RECENT')} items={recent} />
        {!loading && !error && !inForce.length && !upcoming.length && !recent.length && <Empty isDark={isDark} text={msg('UI_ALERTING_SL_EMPTY')} />}
      </div>
    </AppShell>
  )
}
