/**
 * Alert Routing: who is told about an alert, on which channels, and when it escalates, for the whole bank and (optionally) for a processing unit or a sub-member bank.
 * Changes are proposed here and must be approved by a different person (maker-checker). The simulator answers "who would be told for an incident like this" without sending
 * anything. Addresses are masked everywhere on this screen.
 */
import { useState, useMemo } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api, query } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, SeverityBadge, StateBadge, useTh, when } from '../ui'

const LEVELS = [['BANK', 'UI_ALERTING_RT_LEVEL_BANK'], ['PU', 'UI_ALERTING_RT_LEVEL_PU'], ['SMB', 'UI_ALERTING_RT_LEVEL_SMB']]
const SEVERITIES = ['P0', 'P1', 'P2', 'P3']
const CHANNELS = ['email', 'whatsapp', 'bell', 'sms']
const KINDS = [['role', 'UI_ALERTING_RT_KIND_ROLE'], ['user', 'UI_ALERTING_RT_KIND_USER'], ['external', 'UI_ALERTING_RT_KIND_EXTERNAL'], ['oncall', 'UI_ALERTING_RT_KIND_ONCALL'], ['group', 'UI_ALERTING_RT_KIND_GROUP']]
const HOURS = [['always', 'UI_ALERTING_RT_HOURS_ALWAYS'], ['business', 'UI_ALERTING_RT_HOURS_BUSINESS'], ['off_hours', 'UI_ALERTING_RT_HOURS_OFF']]
const CODE_KEY = {
  p0_not_covered: 'UI_ALERTING_RT_CODE_P0_NOT_COVERED', p0_needs_a_target: 'UI_ALERTING_RT_CODE_P0_TARGET', p0_needs_two_channels: 'UI_ALERTING_RT_CODE_P0_CHANNELS',
  duplicate_rule_id: 'UI_ALERTING_RT_CODE_DUPLICATE', unknown_channel: 'UI_ALERTING_RT_CODE_CHANNEL', escalation_not_increasing: 'UI_ALERTING_RT_CODE_ESCALATION_ORDER',
  negative_minutes: 'UI_ALERTING_RT_CODE_NEGATIVE', quiet_hold_not_allowed: 'UI_ALERTING_RT_CODE_HOLD', escalation_must_end_with_a_person: 'UI_ALERTING_RT_CODE_ESCALATION_PERSON',
  scope_required: 'UI_ALERTING_RT_CODE_SCOPE_REQUIRED', scope_mismatch: 'UI_ALERTING_RT_CODE_SCOPE_MISMATCH', unknown_level: 'UI_ALERTING_RT_CODE_LEVEL',
}
const WARNING_KEY = { no_rule_matched: 'UI_ALERTING_RT_WARN_NO_RULE', bank_rule_missing: 'UI_ALERTING_RT_WARN_NO_BANK_RULE', policy_store_unavailable: 'UI_ALERTING_RT_WARN_STORE', oncall_unavailable: 'UI_ALERTING_RT_WARN_ONCALL' }
const csv = (text) => text.split(',').map(s => s.trim()).filter(Boolean)

function codeText(c) { return CODE_KEY[c] ? msg(CODE_KEY[c]) : c }
function warningText(w) {
  if (w.startsWith('oncall_unfilled:')) return msg('UI_ALERTING_RT_WARN_UNFILLED', { rota: w.split(':')[1] })
  return WARNING_KEY[w] ? msg(WARNING_KEY[w]) : w
}
const kindText = (kind) => msg((KINDS.find(([k]) => k === kind) ?? KINDS[0])[1])

// ------------------------------------------------------------------ read-only view of a policy

function Targets({ targets, isDark }) {
  const th = useTh(isDark)
  return (
    <ul className="space-y-0.5">
      {(targets ?? []).map((t, i) => <li key={i} className={`text-xs ${th.body}`}>{kindText(t.kind)}: <span className={th.heading}>{t.ref}</span> <span className={th.muted}>[{(t.channels ?? []).join(', ')}]</span></li>)}
    </ul>
  )
}

function PolicyRules({ policy, isDark }) {
  const th = useTh(isDark)
  return (
    <div className="space-y-3">
      {(policy?.rules ?? []).map(r => (
        <div key={r.id} className={`rounded-lg border p-3 ${th.divider}`}>
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className={`text-xs font-semibold ${th.heading}`}>{r.id}</span>
            {(r.severities ?? []).length ? r.severities.map(s => <SeverityBadge key={s} severity={s} isDark={isDark} />) : <span className={`text-[11px] ${th.muted}`}>{msg('UI_ALERTING_RT_ANY_SEVERITY')}</span>}
            {(r.components ?? []).length > 0 && <span className={`text-[11px] ${th.muted}`}>{msg('UI_ALERTING_RT_COMPONENTS')}: {r.components.join(', ')}</span>}
            {(r.teams ?? []).length > 0 && <span className={`text-[11px] ${th.muted}`}>{msg('UI_ALERTING_RT_TEAMS')}: {r.teams.join(', ')}</span>}
            {r.hours !== 'always' && <span className={`text-[11px] ${th.muted}`}>{msg((HOURS.find(([h]) => h === r.hours) ?? HOURS[0])[1])}</span>}
            {r.quiet_hold && <span className={`text-[11px] ${th.muted}`}>{msg('UI_ALERTING_RT_QUIET_HOLD')}</span>}
            {r.repeat_minutes != null && <span className={`text-[11px] ${th.muted}`}>{msg('UI_ALERTING_RT_REPEAT', { minutes: r.repeat_minutes })}</span>}
          </div>
          <Targets targets={r.targets} isDark={isDark} />
          {(r.escalation ?? []).map(step => (
            <div key={step.level} className={`mt-2 pl-3 border-l-2 ${th.divider}`}>
              <p className={`text-[11px] font-semibold ${th.muted}`}>{msg('UI_ALERTING_RT_AFTER', { minutes: step.after_minutes })}</p>
              <Targets targets={step.targets} isDark={isDark} />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ editor

const blankTarget = () => ({ kind: 'role', ref: '', channels: ['email'] })
const blankRule = () => ({ id: '', severities: [], componentsText: '', teamsText: '', hours: 'always', quiet_hold: false, repeatText: '', targets: [blankTarget()], escalation: [] })
const toDraft = (policy) => (policy?.rules?.length ? policy.rules : [{}]).map(r => ({
  id: r.id ?? '', severities: r.severities ?? [], componentsText: (r.components ?? []).join(', '), teamsText: (r.teams ?? []).join(', '), hours: r.hours ?? 'always', quiet_hold: !!r.quiet_hold,
  repeatText: r.repeat_minutes != null ? String(r.repeat_minutes) : '', targets: (r.targets ?? [blankTarget()]).map(t => ({ ...t, channels: [...(t.channels ?? [])] })),
  escalation: (r.escalation ?? []).map(s => ({ after_minutes: s.after_minutes, targets: (s.targets ?? []).map(t => ({ ...t, channels: [...(t.channels ?? [])] })) })),
}))
const fromDraft = (draft, scope) => ({
  scope_id: scope || null,
  rules: draft.map(r => ({
    id: r.id.trim(), severities: r.severities, components: csv(r.componentsText), teams: csv(r.teamsText), hours: r.hours, quiet_hold: r.quiet_hold,
    repeat_minutes: r.repeatText.trim() === '' ? null : Number(r.repeatText), targets: r.targets.filter(t => t.ref.trim()).map(t => ({ ...t, ref: t.ref.trim() })),
    escalation: r.escalation.map((s, i) => ({ level: i + 1, after_minutes: Number(s.after_minutes), targets: s.targets.filter(t => t.ref.trim()).map(t => ({ ...t, ref: t.ref.trim() })) })),
  })),
})

function TargetRows({ targets, onChange, isDark }) {
  const th = useTh(isDark)
  const set = (i, patch) => onChange(targets.map((t, k) => (k === i ? { ...t, ...patch } : t)))
  const toggle = (i, ch) => set(i, { channels: targets[i].channels.includes(ch) ? targets[i].channels.filter(c => c !== ch) : [...targets[i].channels, ch] })
  return (
    <div className="space-y-1">
      {targets.map((t, i) => (
        <div key={i} className="flex flex-wrap items-center gap-2">
          <select aria-label={msg('UI_ALERTING_RT_KIND')} value={t.kind} onChange={e => set(i, { kind: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`}>{KINDS.map(([k, key]) => <option key={k} value={k}>{msg(key)}</option>)}</select>
          <input aria-label={msg('UI_ALERTING_RT_REF')} placeholder={msg('UI_ALERTING_RT_REF')} value={t.ref} onChange={e => set(i, { ref: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-52 ${th.input}`} />
          {CHANNELS.map(ch => <label key={ch} className={`flex items-center gap-1 text-[11px] ${th.body}`}><input type="checkbox" checked={t.channels.includes(ch)} onChange={() => toggle(i, ch)} />{ch}</label>)}
          <Button isDark={isDark} kind="danger" onClick={() => onChange(targets.filter((_, k) => k !== i))}>{msg('UI_ALERTING_RT_REMOVE')}</Button>
        </div>
      ))}
      <Button isDark={isDark} onClick={() => onChange([...targets, blankTarget()])}>{msg('UI_ALERTING_RT_ADD_TARGET')}</Button>
    </div>
  )
}

function Editor({ isDark, level, scope, initial, onDone, onCancel }) {
  const th = useTh(isDark)
  const [rules, setRules] = useState(() => toDraft(initial))
  const [note, setNote] = useState('')
  const [problems, setProblems] = useState([])
  const [busy, setBusy] = useState(false)
  const setRule = (i, patch) => setRules(prev => prev.map((r, k) => (k === i ? { ...r, ...patch } : r)))
  const toggleSeverity = (i, s) => setRule(i, { severities: rules[i].severities.includes(s) ? rules[i].severities.filter(x => x !== s) : [...rules[i].severities, s] })

  const submit = async () => {
    setBusy(true); setProblems([])
    try {
      await api('/v1/admin/alert-routing/policies', { method: 'POST', body: { level, scope_id: scope || null, policy: fromDraft(rules, scope), note: note || null } })
      onDone()
    } catch (e) {
      setProblems(e.codes?.length ? e.codes.map(codeText) : [e.message])
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card isDark={isDark} className="p-4 mt-4">
      {rules.map((r, i) => (
        <div key={i} className={`border-b pb-4 mb-4 ${th.divider}`}>
          <div className="flex flex-wrap gap-3 items-end">
            <Field isDark={isDark} label={msg('UI_ALERTING_RT_RULE_ID')}><input value={r.id} onChange={e => setRule(i, { id: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-36 ${th.input}`} /></Field>
            <div><span className={`block mb-1 text-[11px] font-medium ${th.muted}`}>{msg('UI_ALERTING_RT_SEVERITIES')}</span>
              <div className="flex gap-2">{SEVERITIES.map(s => <label key={s} className={`flex items-center gap-1 text-[11px] ${th.body}`}><input type="checkbox" checked={r.severities.includes(s)} onChange={() => toggleSeverity(i, s)} />{s}</label>)}</div></div>
            <Field isDark={isDark} label={msg('UI_ALERTING_RT_COMPONENTS_CSV')}><input value={r.componentsText} onChange={e => setRule(i, { componentsText: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-44 ${th.input}`} /></Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_RT_TEAMS_CSV')}><input value={r.teamsText} onChange={e => setRule(i, { teamsText: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-32 ${th.input}`} /></Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_RT_HOURS')}><select value={r.hours} onChange={e => setRule(i, { hours: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`}>{HOURS.map(([h, key]) => <option key={h} value={h}>{msg(key)}</option>)}</select></Field>
            <Field isDark={isDark} label={msg('UI_ALERTING_RT_REPEAT_LABEL')}><input type="number" min="0" value={r.repeatText} onChange={e => setRule(i, { repeatText: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-24 ${th.input}`} /></Field>
            <label className={`flex items-center gap-1 text-[11px] ${th.body}`}><input type="checkbox" checked={r.quiet_hold} onChange={e => setRule(i, { quiet_hold: e.target.checked })} />{msg('UI_ALERTING_RT_QUIET_HOLD')}</label>
            <Button isDark={isDark} kind="danger" onClick={() => setRules(prev => prev.filter((_, k) => k !== i))}>{msg('UI_ALERTING_RT_REMOVE_RULE')}</Button>
          </div>
          <p className={`mt-3 mb-1 text-[11px] font-semibold uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_RT_TOLD_FIRST')}</p>
          <TargetRows targets={r.targets} onChange={t => setRule(i, { targets: t })} isDark={isDark} />
          {r.escalation.map((s, si) => (
            <div key={si} className={`mt-3 pl-3 border-l-2 ${th.divider}`}>
              <div className="flex items-end gap-3 mb-1">
                <Field isDark={isDark} label={msg('UI_ALERTING_RT_STEP_AFTER', { level: si + 1 })}><input type="number" min="0" value={s.after_minutes} onChange={e => setRule(i, { escalation: r.escalation.map((x, k) => (k === si ? { ...x, after_minutes: e.target.value } : x)) })} className={`text-xs rounded-lg border px-2 py-1 w-24 ${th.input}`} /></Field>
                <Button isDark={isDark} kind="danger" onClick={() => setRule(i, { escalation: r.escalation.filter((_, k) => k !== si) })}>{msg('UI_ALERTING_RT_REMOVE_STEP')}</Button>
              </div>
              <TargetRows targets={s.targets} onChange={t => setRule(i, { escalation: r.escalation.map((x, k) => (k === si ? { ...x, targets: t } : x)) })} isDark={isDark} />
            </div>
          ))}
          <div className="mt-3"><Button isDark={isDark} onClick={() => setRule(i, { escalation: [...r.escalation, { after_minutes: (r.escalation.at(-1)?.after_minutes ?? 0) + 10, targets: [blankTarget()] }] })}>{msg('UI_ALERTING_RT_ADD_STEP')}</Button></div>
        </div>
      ))}
      <Button isDark={isDark} onClick={() => setRules(prev => [...prev, blankRule()])}>{msg('UI_ALERTING_RT_ADD_RULE')}</Button>
      <div className="mt-4"><Field isDark={isDark} label={msg('UI_ALERTING_RT_NOTE')}><input value={note} onChange={e => setNote(e.target.value)} className={`text-xs rounded-lg border px-2 py-1 w-96 ${th.input}`} /></Field></div>
      {problems.length > 0 && <ul role="alert" className="mt-3 text-xs text-red-500 list-disc pl-5">{problems.map(p => <li key={p}>{p}</li>)}</ul>}
      <div className="mt-3 flex gap-2">
        <Button isDark={isDark} kind="primary" disabled={busy} onClick={submit}>{msg('UI_ALERTING_RT_SUBMIT')}</Button>
        <Button isDark={isDark} onClick={onCancel}>{msg('UI_ALERTING_CANCEL')}</Button>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------ approval queue

function Pending({ isDark, items, reload, onDecided }) {
  const th = useTh(isDark)
  const [opened, setOpened] = useState({})
  const [notes, setNotes] = useState({})
  const read = async (id) => {
    if (opened[id]) { setOpened(o => ({ ...o, [id]: null })); return }
    try {
      const found = await api(`/v1/admin/alert-routing/policies/${id}`)
      setOpened(o => ({ ...o, [id]: found.policy }))
    } catch (e) { setNotes(n => ({ ...n, [id]: e.message })) }
  }
  const decide = async (id, action) => {
    setNotes(n => ({ ...n, [id]: null }))
    try { await api(`/v1/admin/alert-routing/policies/${id}/${action}`, { method: 'POST', body: action === 'reject' ? {} : undefined }); reload(); onDecided() } catch (e) { setNotes(n => ({ ...n, [id]: e.message })) }
  }
  if (!items.length) return <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_RT_NO_PENDING')}</p>
  return (
    <div className="space-y-3">
      {items.map(p => (
        <div key={p.policy_id} className={`rounded-lg border p-3 ${th.divider}`}>
          <div className="flex flex-wrap items-center gap-3">
            <StateBadge state="PENDING" isDark={isDark} />
            <span className={`text-xs ${th.heading}`}>{msg('UI_ALERTING_RT_PENDING_LINE', { level: p.scope_level, scope: p.scope_id ?? '', version: p.version, who: p.created_by, when: when(p.created_at) })}</span>
            {p.note && <span className={`text-xs ${th.muted}`}>"{p.note}"</span>}
            <span className="flex gap-2 ml-auto">
              <Button isDark={isDark} onClick={() => read(p.policy_id)}>{msg('UI_ALERTING_RT_READ')}</Button>
              <Button isDark={isDark} kind="primary" onClick={() => decide(p.policy_id, 'approve')}>{msg('UI_ALERTING_RT_APPROVE')}</Button>
              <Button isDark={isDark} kind="danger" onClick={() => decide(p.policy_id, 'reject')}>{msg('UI_ALERTING_RT_REJECT')}</Button>
            </span>
          </div>
          {notes[p.policy_id] && <p role="alert" className="mt-2 text-xs text-red-500">{notes[p.policy_id]}</p>}
          {opened[p.policy_id] && <div className="mt-3"><PolicyRules policy={opened[p.policy_id]} isDark={isDark} /></div>}
        </div>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ simulator

function Simulator({ isDark }) {
  const th = useTh(isDark)
  const [form, setForm] = useState({ severity: 'P0', component: '', pu_id: '', smb_id: '', at: '' })
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const set = (patch) => setForm(f => ({ ...f, ...patch }))
  const run = async () => {
    setError(null)
    try {
      setResult(await api('/v1/admin/alert-routing/simulate', { method: 'POST', body: { severity: form.severity, component: form.component, pu_id: form.pu_id || null, smb_id: form.smb_id || null, at: form.at ? new Date(form.at).toISOString() : null } }))
    } catch (e) { setError(e.message); setResult(null) }
  }
  return (
    <div>
      <div className="flex flex-wrap gap-3 items-end">
        <Field isDark={isDark} label={msg('UI_ALERTING_FILTER_SEVERITY')}><select value={form.severity} onChange={e => set({ severity: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`}>{SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}</select></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_COL_COMPONENT')}><input value={form.component} onChange={e => set({ component: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-40 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_RT_PU_ID')}><input value={form.pu_id} onChange={e => set({ pu_id: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-28 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_RT_SMB_ID')}><input value={form.smb_id} onChange={e => set({ smb_id: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 w-28 ${th.input}`} /></Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_RT_AT')}><input type="datetime-local" value={form.at} onChange={e => set({ at: e.target.value })} className={`text-xs rounded-lg border px-2 py-1 ${th.input}`} /></Field>
        <Button isDark={isDark} kind="primary" onClick={run}>{msg('UI_ALERTING_RT_SIMULATE')}</Button>
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-red-500">{error}</p>}
      {result && (
        <div className="mt-4 space-y-2">
          <p className={`text-xs ${th.muted}`}>{(result.matched ?? []).map(m => msg('UI_ALERTING_RT_MATCHED', { level: m.level, rule: m.rule_id })).join('  ')}{result.used_default ? `  ${msg('UI_ALERTING_RT_USED_DEFAULT')}` : ''}{result.held ? `  ${msg('UI_ALERTING_RT_HELD')}` : ''}</p>
          {(result.warnings ?? []).map(w => <p key={w} role="alert" className="text-xs text-amber-500">{warningText(w)}</p>)}
          {(result.steps ?? []).map(s => (
            <div key={s.level} className={`rounded-lg border p-3 ${th.divider}`}>
              <p className={`text-[11px] font-semibold ${th.muted}`}>{s.level === 0 ? msg('UI_ALERTING_RT_NOW') : msg('UI_ALERTING_RT_AFTER', { minutes: s.after_minutes })}</p>
              <Targets targets={s.targets} isDark={isDark} />
              <ul className="mt-1">{(s.deliveries ?? []).map((d, i) => <li key={i} className={`text-xs ${th.body}`}>{d.channel}: <span className={th.heading}>{d.recipient_ref}</span></li>)}</ul>
            </div>
          ))}
          {result.repeat_minutes != null && <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_RT_REPEAT', { minutes: result.repeat_minutes })}</p>}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ page

export default function AlertRouting() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const [level, setLevel] = useState('BANK')
  const [scopeInput, setScopeInput] = useState('')
  const [scope, setScope] = useState('')
  const [editing, setEditing] = useState(false)
  const [done, setDone] = useState(false)
  const path = `/v1/admin/alert-routing/policies${query({ level, scope_id: level === 'BANK' ? '' : scope })}`
  const policy = useLoad(path)
  const pending = useLoad('/v1/admin/alert-routing/pending')
  const view = policy.data
  const needsScope = level !== 'BANK' && !scope
  const shown = view?.active?.policy ?? view?.default_policy ?? null
  const initialForEdit = useMemo(() => shown ?? { rules: [] }, [shown])

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_RT_TITLE')} subtitle={msg('UI_ALERTING_RT_SUBTITLE')} />
        <ErrorNote isDark={isDark} error={policy.error} onRetry={policy.reload} />
        <div role="tablist" className="flex gap-2 mb-3">
          {LEVELS.map(([l, key]) => (
            <button key={l} role="tab" aria-selected={level === l} type="button" onClick={() => { setLevel(l); setEditing(false); setDone(false) }}
              className={`text-xs font-medium px-3 py-1.5 rounded-lg border ${level === l ? th.primary : th.button}`}>{msg(key)}</button>
          ))}
        </div>
        {level !== 'BANK' && (
          <div className="flex items-end gap-2 mb-3">
            <Field isDark={isDark} label={level === 'PU' ? msg('UI_ALERTING_RT_PU_ID_FULL') : msg('UI_ALERTING_RT_SMB_ID_FULL')}>
              <input value={scopeInput} onChange={e => setScopeInput(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 ${th.input}`} />
            </Field>
            <Button isDark={isDark} onClick={() => { setScope(scopeInput.trim()); setEditing(false) }}>{msg('UI_ALERTING_RT_LOAD')}</Button>
          </div>
        )}
        {!needsScope && (
          <Card isDark={isDark} className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                {view?.used_default
                  ? <p className={`text-sm font-semibold ${th.heading}`}>{level === 'BANK' ? msg('UI_ALERTING_RT_NO_POLICY') : msg('UI_ALERTING_RT_NO_SCOPE_POLICY')}</p>
                  : view?.active && <p className={`text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_RT_VERSION', { version: view.active.record.version })}</p>}
                {view?.active && <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_RT_APPROVED_BY', { who: view.active.record.approved_by ?? '', when: when(view.active.record.approved_at) })}</p>}
              </div>
              <Button isDark={isDark} kind="primary" onClick={() => { setEditing(true); setDone(false) }}>{msg('UI_ALERTING_RT_PROPOSE')}</Button>
            </div>
            {done && <p role="status" className={`mb-3 text-xs ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{msg('UI_ALERTING_RT_SUBMITTED')}</p>}
            {shown ? <PolicyRules policy={shown} isDark={isDark} /> : <Empty isDark={isDark} text={msg('UI_ALERTING_RT_NO_RULES')} />}
          </Card>
        )}
        {editing && !needsScope && <Editor key={`${level}-${scope}-${view?.active?.record?.version ?? 0}`} isDark={isDark} level={level} scope={scope} initial={initialForEdit}
          onDone={() => { setEditing(false); setDone(true); pending.reload(); policy.reload() }} onCancel={() => setEditing(false)} />}

        <h2 className={`mt-6 mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_RT_PENDING')}</h2>
        <Card isDark={isDark} className="p-4"><Pending isDark={isDark} items={pending.data?.pending ?? []} reload={pending.reload} onDecided={policy.reload} /></Card>

        <h2 className={`mt-6 mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_RT_HISTORY')}</h2>
        <Card isDark={isDark} className="overflow-hidden">
          <table className="w-full text-xs"><tbody>
            {(view?.history ?? []).map(h => (
              <tr key={h.policy_id} className={`border-b ${th.row}`}>
                <td className={`px-3 py-2 ${th.heading}`}>{msg('UI_ALERTING_RT_VERSION', { version: h.version })}</td>
                <td className="px-3 py-2"><StateBadge state={h.status} isDark={isDark} /></td>
                <td className={`px-3 py-2 ${th.body}`}>{msg('UI_ALERTING_RT_PROPOSED_BY', { who: h.created_by })}</td>
                <td className={`px-3 py-2 ${th.muted}`}>{when(h.created_at)}</td>
              </tr>
            ))}
          </tbody></table>
          {(view?.history ?? []).length === 0 && <Empty isDark={isDark} text={msg('UI_ALERTING_RT_NO_HISTORY')} />}
        </Card>

        <h2 className={`mt-6 mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_RT_SIM_TITLE')}</h2>
        <Card isDark={isDark} className="p-4"><Simulator isDark={isDark} /></Card>
      </div>
    </AppShell>
  )
}
