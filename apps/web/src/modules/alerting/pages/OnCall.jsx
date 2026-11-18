/**
 * On-Call: the rotas, who is on call right now (and whether that comes from a shift, an override or the fallback), shifts, swaps and cover (overrides), coverage gaps
 * in the coming days, and a rota editor. Changes are audited on the server with the person who made them.
 */
import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, useTh, when } from '../ui'

const DAYS = [
  [0, 'UI_ALERTING_DAY_0'], [1, 'UI_ALERTING_DAY_1'], [2, 'UI_ALERTING_DAY_2'], [3, 'UI_ALERTING_DAY_3'], [4, 'UI_ALERTING_DAY_4'], [5, 'UI_ALERTING_DAY_5'], [6, 'UI_ALERTING_DAY_6'],
]
const SOURCE_KEY = { shift: 'UI_ALERTING_OC_SRC_SHIFT', override: 'UI_ALERTING_OC_SRC_OVERRIDE', fallback: 'UI_ALERTING_OC_SRC_FALLBACK', none: 'UI_ALERTING_OC_SRC_NONE' }
const ROTATIONS = [['none', 'UI_ALERTING_OC_ROT_NONE'], ['weekly', 'UI_ALERTING_OC_ROT_WEEKLY'], ['daily', 'UI_ALERTING_OC_ROT_DAILY']]
const HOLIDAYS = [['include', 'UI_ALERTING_OC_HOL_INCLUDE'], ['exclude', 'UI_ALERTING_OC_HOL_EXCLUDE'], ['only', 'UI_ALERTING_OC_HOL_ONLY']]
const CODE_KEY = {
  bad_time: 'UI_ALERTING_OC_CODE_BAD_TIME', bad_day: 'UI_ALERTING_OC_CODE_BAD_DAY', shift_needs_people: 'UI_ALERTING_OC_CODE_NEEDS_PEOPLE', unknown_rotation: 'UI_ALERTING_OC_CODE_ROTATION',
  unknown_holidays: 'UI_ALERTING_OC_CODE_HOLIDAYS', rota_has_no_one: 'UI_ALERTING_OC_CODE_NO_ONE', ends_before_start: 'UI_ALERTING_OC_CODE_ENDS_BEFORE', unknown_rota: 'UI_ALERTING_OC_CODE_UNKNOWN_ROTA',
}
const NEW_SHIFT = { days: [0, 1, 2, 3, 4], start: '09:30', end: '18:00', users: [], rotation: 'none', holidays: 'include' }
const csv = (text) => text.split(',').map(s => s.trim()).filter(Boolean)
const dayNames = (days) => DAYS.filter(([d]) => days.includes(d)).map(([, key]) => msg(key)).join(', ')

function reasons(error) {
  if (!error) return []
  const codes = (error.codes ?? []).map(c => (CODE_KEY[c] ? msg(CODE_KEY[c]) : c))
  return codes.length ? codes : [error.message]
}

function Editor({ isDark, name, initial, onSaved, onCancel }) {
  const th = useTh(isDark)
  const [shifts, setShifts] = useState((initial?.shifts?.length ? initial.shifts : [NEW_SHIFT]).map(s => ({ ...s, usersText: (s.users ?? []).join(', ') })))
  const [fallback, setFallback] = useState((initial?.fallback?.users ?? []).join(', '))
  const [problems, setProblems] = useState([])
  const [saving, setSaving] = useState(false)
  const change = (i, patch) => setShifts(prev => prev.map((s, k) => (k === i ? { ...s, ...patch } : s)))
  const toggleDay = (i, d) => change(i, { days: shifts[i].days.includes(d) ? shifts[i].days.filter(x => x !== d) : [...shifts[i].days, d].sort() })

  const save = async () => {
    setSaving(true); setProblems([])
    const body = { rota: { shifts: shifts.map(({ usersText, ...s }) => ({ ...s, users: csv(usersText) })), fallback: csv(fallback).length ? { users: csv(fallback) } : null } }
    try {
      await api(`/v1/ops/oncall/rotas/${name}`, { method: 'PUT', body })
      onSaved()
    } catch (e) {
      setProblems(reasons(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card isDark={isDark} className="p-4 mt-4">
      {shifts.map((s, i) => (
        <div key={i} className={`border-b pb-3 mb-3 ${th.divider}`}>
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex gap-2">
              {DAYS.map(([d, key]) => (
                <label key={d} className={`flex items-center gap-1 text-[11px] ${th.body}`}>
                  <input type="checkbox" checked={s.days.includes(d)} onChange={() => toggleDay(i, d)} />{msg(key)}
                </label>
              ))}
            </div>
            <Field isDark={isDark} label={msg('UI_ALERTING_OC_START')}><input type="time" value={s.start} onChange={e => change(i, { start: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`} /></Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_OC_END')}><input type="time" value={s.end} onChange={e => change(i, { end: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`} /></Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_OC_PEOPLE')}><input value={s.usersText} onChange={e => change(i, { usersText: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-56 ${th.input}`} /></Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_OC_ROTATION')}>
              <select value={s.rotation} onChange={e => change(i, { rotation: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`}>{ROTATIONS.map(([v, k]) => <option key={v} value={v}>{msg(k)}</option>)}</select>
            </Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_OC_HOLIDAYS')}>
              <select value={s.holidays} onChange={e => change(i, { holidays: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`}>{HOLIDAYS.map(([v, k]) => <option key={v} value={v}>{msg(k)}</option>)}</select>
            </Field>
            <Button isDark={isDark} kind="danger" onClick={() => setShifts(prev => prev.filter((_, k) => k !== i))}>{msg('UI_ALERTING_OC_REMOVE_SHIFT')}</Button>
          </div>
        </div>
      ))}
      <Button isDark={isDark} onClick={() => setShifts(prev => [...prev, { ...NEW_SHIFT, usersText: '' }])}>{msg('UI_ALERTING_OC_ADD_SHIFT')}</Button>
      <div className="mt-3"><Field isDark={isDark} label={msg('UI_ALERTING_OC_FALLBACK_PEOPLE')}><input value={fallback} onChange={e => setFallback(e.target.value)} className={`text-xs rounded-lg border px-2 py-1 w-72 ${th.input}`} /></Field></div>
      {problems.length > 0 && <ul role="alert" className="mt-3 text-xs text-red-500 list-disc pl-5">{problems.map(p => <li key={p}>{p}</li>)}</ul>}
      <div className="mt-3 flex gap-2">
        <Button isDark={isDark} kind="primary" disabled={saving} onClick={save}>{msg('UI_ALERTING_OC_SAVE')}</Button>
        <Button isDark={isDark} onClick={onCancel}>{msg('UI_ALERTING_CANCEL')}</Button>
      </div>
    </Card>
  )
}

function OverrideForm({ isDark, name, onAdded }) {
  const th = useTh(isDark)
  const [form, setForm] = useState({ user_id: '', from: '', until: '', reason: '' })
  const [problems, setProblems] = useState([])
  const set = (patch) => setForm(f => ({ ...f, ...patch }))
  const add = async () => {
    setProblems([])
    try {
      await api(`/v1/ops/oncall/rotas/${name}/overrides`, { method: 'POST', body: { user_id: form.user_id, starts_at: new Date(form.from).toISOString(), ends_at: new Date(form.until).toISOString(), reason: form.reason } })
      setForm({ user_id: '', from: '', until: '', reason: '' })
      onAdded()
    } catch (e) {
      setProblems(e instanceof RangeError ? [msg('UI_ALERTING_OC_CODE_BAD_TIME')] : reasons(e))
    }
  }
  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-3 items-end">
        <Field isDark={isDark} label={msg('UI_ALERTING_OC_PERSON')}><input value={form.user_id} onChange={e => set({ user_id: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_OC_FROM')}><input type="datetime-local" value={form.from} onChange={e => set({ from: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_OC_UNTIL')}><input type="datetime-local" value={form.until} onChange={e => set({ until: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_OC_REASON')}><input value={form.reason} onChange={e => set({ reason: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-48 ${th.input}`} /></Field>
        <Button isDark={isDark} kind="primary" onClick={add}>{msg('UI_ALERTING_OC_ADD_OVERRIDE')}</Button>
      </div>
      {problems.length > 0 && <ul role="alert" className="mt-2 text-xs text-red-500 list-disc pl-5">{problems.map(p => <li key={p}>{p}</li>)}</ul>}
    </div>
  )
}

function Detail({ name, isDark }) {
  const th = useTh(isDark)
  const { data, error, reload } = useLoad(`/v1/ops/oncall/rotas/${name}`)
  const [editing, setEditing] = useState(false)
  const [removeError, setRemoveError] = useState(null)
  useEffect(() => { setEditing(false) }, [name])
  if (error?.status === 404 && !data) return <Editor isDark={isDark} name={name} initial={null} onSaved={reload} onCancel={() => {}} />      // a rota that does not exist yet: create it
  if (error && !data) return <ErrorNote isDark={isDark} error={error} onRetry={reload} />
  if (!data?.rota) return null
  const remove = async (id) => {
    setRemoveError(null)
    try { await api(`/v1/ops/oncall/rotas/${name}/overrides/${id}`, { method: 'DELETE' }); reload() } catch (e) { setRemoveError(e.message) }
  }
  const onCall = data.on_call ?? { users: [], source: 'none' }
  return (
    <div>
      <Card isDark={isDark} className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className={`text-[11px] uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_OC_NOW')}</p>
            <p className={`text-sm font-semibold ${th.heading}`}>{onCall.users.length ? onCall.users.join(', ') : msg('UI_ALERTING_OC_NOBODY')}</p>
            <p className={`text-xs ${th.muted}`}>{msg(SOURCE_KEY[onCall.source] ?? SOURCE_KEY.none)}</p>
          </div>
          <Button isDark={isDark} onClick={() => setEditing(true)}>{msg('UI_ALERTING_OC_EDIT')}</Button>
        </div>
        {(data.gaps ?? []).length > 0 ? (
          <div role="alert" className={`mt-3 rounded-lg border px-3 py-2 text-xs ${isDark ? 'border-amber-700/40 bg-amber-900/20 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
            {msg('UI_ALERTING_OC_GAPS')}
            <ul className="mt-1 list-disc pl-5">{data.gaps.map(g => <li key={g.starts_at}>{when(g.starts_at)} - {when(g.ends_at)}</li>)}</ul>
          </div>
        ) : <p className={`mt-3 text-xs ${th.muted}`}>{msg('UI_ALERTING_OC_NO_GAPS')}</p>}
        <h3 className={`mt-4 mb-1 text-[11px] font-semibold uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_OC_SHIFTS')}</h3>
        <table className="w-full text-xs">
          <tbody>
            {(data.rota.shifts ?? []).map((s, i) => (
              <tr key={i} className={`border-b ${th.row}`}>
                <td className={`py-2 pr-3 ${th.body}`}>{dayNames(s.days)}</td>
                <td className={`py-2 pr-3 ${th.heading}`}>{`${s.start} - ${s.end}`}</td>
                <td className={`py-2 pr-3 ${th.body}`}>{(s.users ?? []).join(', ')}</td>
                <td className={`py-2 ${th.muted}`}>{msg(ROTATIONS.find(([v]) => v === s.rotation)?.[1] ?? 'UI_ALERTING_OC_ROT_NONE')}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(data.rota.fallback?.users ?? []).length > 0 && <p className={`mt-2 text-xs ${th.muted}`}>{msg('UI_ALERTING_OC_FALLBACK')}: {data.rota.fallback.users.join(', ')}</p>}
      </Card>
      {editing && <Editor isDark={isDark} name={name} initial={data.rota} onSaved={() => { setEditing(false); reload() }} onCancel={() => setEditing(false)} />}
      <Card isDark={isDark} className="p-4 mt-4">
        <h3 className={`mb-1 text-[11px] font-semibold uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_OC_OVERRIDES')}</h3>
        {(data.overrides ?? []).length === 0 && <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_OC_NO_OVERRIDES')}</p>}
        <table className="w-full text-xs"><tbody>
          {(data.overrides ?? []).map(o => (
            <tr key={o.override_id} className={`border-b ${th.row}`}>
              <td className={`py-2 pr-3 ${th.heading}`}>{o.user_id}</td>
              <td className={`py-2 pr-3 ${th.body}`}>{when(o.starts_at)} - {when(o.ends_at)}</td>
              <td className={`py-2 pr-3 ${th.muted}`}>{o.reason}</td>
              <td className="py-2 text-right"><Button isDark={isDark} kind="danger" onClick={() => remove(o.override_id)}>{msg('UI_ALERTING_OC_REMOVE')}</Button></td>
            </tr>
          ))}
        </tbody></table>
        {removeError && <p role="alert" className="mt-2 text-xs text-red-500">{removeError}</p>}
        <OverrideForm isDark={isDark} name={name} onAdded={reload} />
      </Card>
    </div>
  )
}

export default function OnCall() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const navigate = useNavigate()
  const { name } = useParams()
  const { data, error, loading, reload } = useLoad('/v1/ops/oncall/rotas')
  const [newName, setNewName] = useState('')
  const rotas = data?.rotas ?? []
  const create = () => { if (newName.trim()) navigate(`/ops/oncall/${newName.trim().toLowerCase()}`) }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_OC_TITLE')} subtitle={msg('UI_ALERTING_OC_SUBTITLE')}>
          <Button isDark={isDark} onClick={reload}>{msg('UI_ALERTING_REFRESH')}</Button>
        </PageTitle>
        <ErrorNote isDark={isDark} error={error} onRetry={reload} />
        <div className="flex gap-4 items-start">
          <Card isDark={isDark} className="w-64 shrink-0 p-2">
            {rotas.map(r => (
              <button key={r.name} type="button" onClick={() => navigate(`/ops/oncall/${r.name}`)}
                className={`w-full text-left px-3 py-2 rounded-lg text-xs ${name === r.name ? th.rowActive : ''} ${th.row}`}>
                <span className={`block font-semibold ${th.heading}`}>{r.name}</span>
                <span className={th.muted}>{(r.on_call?.users ?? []).length ? r.on_call.users.join(', ') : msg('UI_ALERTING_OC_NOBODY')}</span>
              </button>
            ))}
            {!loading && rotas.length === 0 && !error && <Empty isDark={isDark} text={msg('UI_ALERTING_OC_EMPTY')} />}
            <div className="p-2 mt-2 flex gap-2">
              <input aria-label={msg('UI_ALERTING_OC_NEW_NAME')} placeholder={msg('UI_ALERTING_OC_NEW_NAME')} value={newName} onChange={e => setNewName(e.target.value)} className={`flex-1 min-w-0 text-xs rounded-lg border px-2 py-1 ${th.input}`} />
              <Button isDark={isDark} onClick={create}>{msg('UI_ALERTING_OC_NEW')}</Button>
            </div>
          </Card>
          <div className="flex-1 min-w-0">{name && <Detail key={name} name={name} isDark={isDark} />}</div>
        </div>
      </div>
    </AppShell>
  )
}
