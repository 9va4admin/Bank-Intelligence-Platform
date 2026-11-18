/**
 * Post-incident reviews and actions. A review falls due when a critical or major incident resolves; it is written up (root cause, what happened, the detection gap, the impact),
 * then it produces actions. An action is finished with evidence and verified by a DIFFERENT person. After an action is done the screen says, in words, whether the same failure
 * came back: that is a hint for a person, nothing is closed or reopened by itself.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, SeverityBadge, useTh, when } from '../ui'

const CAUSES = ['capacity', 'configuration', 'software_defect', 'dependency', 'process', 'hardware', 'security', 'unknown']
const CAUSE_KEY = { capacity: 'UI_ALERTING_RV_CAUSE_CAPACITY', configuration: 'UI_ALERTING_RV_CAUSE_CONFIGURATION', software_defect: 'UI_ALERTING_RV_CAUSE_SOFTWARE', dependency: 'UI_ALERTING_RV_CAUSE_DEPENDENCY',
  process: 'UI_ALERTING_RV_CAUSE_PROCESS', hardware: 'UI_ALERTING_RV_CAUSE_HARDWARE', security: 'UI_ALERTING_RV_CAUSE_SECURITY', unknown: 'UI_ALERTING_RV_CAUSE_UNKNOWN' }
const STATUS_KEY = { OPEN: 'UI_ALERTING_RV_ST_OPEN', IN_PROGRESS: 'UI_ALERTING_RV_ST_PROGRESS', DONE: 'UI_ALERTING_RV_ST_DONE', VERIFIED: 'UI_ALERTING_RV_ST_VERIFIED', WONT_FIX: 'UI_ALERTING_RV_ST_WONT_FIX' }
const EFFECT_KEY = { TOO_EARLY: 'UI_ALERTING_RV_EFF_EARLY', EFFECTIVE_SUGGESTED: 'UI_ALERTING_RV_EFF_GOOD', RECURRED: 'UI_ALERTING_RV_EFF_RECURRED' }

function ReviewRow({ review, isDark, onChanged }) {
  const th = useTh(isDark)
  const [mode, setMode] = useState(null)
  const [f, setF] = useState({ category: 'capacity', narrative: '', contributing: '', gap: '', impact: '', kind: 'preventive', description: '', owner: '', due: '' })
  const [problem, setProblem] = useState(null)
  const set = (k) => (e) => setF(x => ({ ...x, [k]: e.target.value }))
  const run = async (fn) => {
    setProblem(null)
    try { await fn(); setMode(null); onChanged() } catch (e) { setProblem(e.message) }
  }
  const submit = () => run(() => api(`/v1/ops/alert-reviews/reviews/${review.review_id}/submit`, { method: 'POST',
    body: { category: f.category, narrative: f.narrative, contributing_factors: f.contributing, detection_gap: f.gap, impact: f.impact } }))
  const addAction = () => run(() => api(`/v1/ops/alert-reviews/reviews/${review.review_id}/actions`, { method: 'POST', body: { kind: f.kind, description: f.description, owner: f.owner, due_on: f.due } }))
  const input = `text-xs rounded-lg border px-2 py-1.5 ${th.input}`
  return (
    <>
      <tr className={`border-b ${th.row}`}>
        <td className="px-3 py-2"><SeverityBadge severity={review.severity} isDark={isDark} /></td>
        <td className={`px-3 py-2 font-semibold ${th.heading}`}>{review.component}</td>
        <td className={`px-3 py-2 ${th.muted}`}>{when(review.resolved_at)}</td>
        <td className={`px-3 py-2 ${th.body}`}>{review.status === 'DUE' ? (review.overdue ? <span className={isDark ? 'text-red-300 font-semibold' : 'text-red-700 font-semibold'}>{msg('UI_ALERTING_RV_OVERDUE')}</span> : msg('UI_ALERTING_RV_DUE_BY', { when: when(review.due_at) }))
          : `${msg(CAUSE_KEY[review.root_cause_category] ?? CAUSE_KEY.unknown)} - ${review.narrative}`}</td>
        <td className="px-3 py-2 text-right whitespace-nowrap">
          {review.status === 'DUE' ? <Button isDark={isDark} kind="primary" onClick={() => setMode(m => (m === 'write' ? null : 'write'))}>{msg('UI_ALERTING_RV_WRITE')}</Button>
            : <Button isDark={isDark} onClick={() => setMode(m => (m === 'action' ? null : 'action'))}>{msg('UI_ALERTING_RV_ADD_ACTION')}</Button>}
        </td>
      </tr>
      {(mode || problem) && (
        <tr className={`border-b ${th.divider}`}>
          <td colSpan={5} className="px-3 py-3">
            {mode === 'write' && (
              <div className="flex flex-wrap items-end gap-3">
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_CAUSE')}><select value={f.category} onChange={set('category')} className={input}>{CAUSES.map(c => <option key={c} value={c}>{msg(CAUSE_KEY[c])}</option>)}</select></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_NARRATIVE')}><input value={f.narrative} onChange={set('narrative')} className={`${input} w-96`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_FACTORS')}><input value={f.contributing} onChange={set('contributing')} className={`${input} w-56`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_GAP')}><input value={f.gap} onChange={set('gap')} className={`${input} w-56`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_IMPACT')}><input value={f.impact} onChange={set('impact')} className={`${input} w-56`} /></Field>
                <Button isDark={isDark} kind="primary" onClick={submit}>{msg('UI_ALERTING_RV_SUBMIT')}</Button>
              </div>
            )}
            {mode === 'action' && (
              <div className="flex flex-wrap items-end gap-3">
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_KIND')}><select value={f.kind} onChange={set('kind')} className={input}><option value="preventive">{msg('UI_ALERTING_RV_KIND_PREVENTIVE')}</option><option value="corrective">{msg('UI_ALERTING_RV_KIND_CORRECTIVE')}</option></select></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_WHAT')}><input value={f.description} onChange={set('description')} className={`${input} w-80`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_OWNER')}><input value={f.owner} onChange={set('owner')} className={`${input} w-40`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RV_DUE_DATE')}><input type="date" value={f.due} onChange={set('due')} className={input} /></Field>
                <Button isDark={isDark} kind="primary" onClick={addAction}>{msg('UI_ALERTING_RV_SAVE_ACTION')}</Button>
              </div>
            )}
            {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

function ActionRow({ action, isDark, onChanged }) {
  const th = useTh(isDark)
  const [mode, setMode] = useState(null)
  const [text, setText] = useState('')
  const [problem, setProblem] = useState(null)
  const move = async (status, evidence = '', note = '') => {
    setProblem(null)
    try { await api(`/v1/ops/alert-reviews/actions/${action.action_id}/status`, { method: 'POST', body: { status, evidence, note } }); setMode(null); setText(''); onChanged() } catch (e) { setProblem(e.message) }
  }
  const tone = action.status === 'VERIFIED' ? (isDark ? 'text-emerald-300' : 'text-emerald-700') : action.overdue ? (isDark ? 'text-red-300' : 'text-red-700') : th.body
  const input = `text-xs rounded-lg border px-2 py-1.5 w-72 ${th.input}`
  return (
    <>
      <tr className={`border-b align-top ${th.row}`}>
        <td className={`px-3 py-2 ${th.heading}`}>{action.description}</td>
        <td className={`px-3 py-2 ${th.body}`}>{action.owner}</td>
        <td className={`px-3 py-2 ${th.muted}`}>{action.due_on}{action.overdue ? ` (${msg('UI_ALERTING_RV_OVERDUE')})` : ''}</td>
        <td className={`px-3 py-2 font-semibold ${tone}`}>{msg(STATUS_KEY[action.status])}{EFFECT_KEY[action.effectiveness] && <span className={`block font-normal ${action.effectiveness === 'RECURRED' ? (isDark ? 'text-red-300' : 'text-red-700') : th.muted}`}>{msg(EFFECT_KEY[action.effectiveness])}</span>}</td>
        <td className="px-3 py-2 text-right whitespace-nowrap space-x-2">
          {(action.status === 'OPEN') && <Button isDark={isDark} onClick={() => move('IN_PROGRESS')}>{msg('UI_ALERTING_RV_START')}</Button>}
          {(action.status === 'OPEN' || action.status === 'IN_PROGRESS') && <Button isDark={isDark} onClick={() => setMode(m => (m === 'done' ? null : 'done'))}>{msg('UI_ALERTING_RV_MARK_DONE')}</Button>}
          {action.status === 'DONE' && <Button isDark={isDark} kind="primary" onClick={() => move('VERIFIED')}>{msg('UI_ALERTING_RV_VERIFY')}</Button>}
          {action.status === 'DONE' && <Button isDark={isDark} onClick={() => setMode(m => (m === 'back' ? null : 'back'))}>{msg('UI_ALERTING_RV_SEND_BACK')}</Button>}
        </td>
      </tr>
      {(mode || problem) && (
        <tr className={`border-b ${th.divider}`}>
          <td colSpan={5} className="px-3 py-3">
            {mode === 'done' && <div className="flex items-end gap-3"><Field isDark={isDark} label={msg('UI_ALERTING_RV_EVIDENCE')}><input value={text} onChange={e => setText(e.target.value)} className={input} /></Field><Button isDark={isDark} kind="primary" onClick={() => move('DONE', text)}>{msg('UI_ALERTING_RV_SAVE')}</Button></div>}
            {mode === 'back' && <div className="flex items-end gap-3"><Field isDark={isDark} label={msg('UI_ALERTING_RV_REASON')}><input value={text} onChange={e => setText(e.target.value)} className={input} /></Field><Button isDark={isDark} kind="primary" onClick={() => move('IN_PROGRESS', '', text)}>{msg('UI_ALERTING_RV_SAVE')}</Button></div>}
            {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

export default function Reviews() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const reviews = useLoad('/v1/ops/alert-reviews/reviews')
  const actions = useLoad('/v1/ops/alert-reviews/actions')
  const list = reviews.data?.reviews ?? []
  const due = list.filter(r => r.status === 'DUE')
  const submitted = list.filter(r => r.status === 'SUBMITTED')
  const acts = actions.data?.actions ?? []
  const refresh = () => { reviews.reload(); actions.reload() }
  const Section = ({ title, items }) => items.length === 0 ? null : (
    <div className="mb-5">
      <h2 className={`mb-2 text-sm font-semibold ${th.heading}`}>{title}</h2>
      <Card isDark={isDark} className="overflow-hidden"><table className="w-full text-xs"><tbody>{items.map(r => <ReviewRow key={r.review_id} review={r} isDark={isDark} onChanged={refresh} />)}</tbody></table></Card>
    </div>
  )
  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_RV_TITLE')} subtitle={msg('UI_ALERTING_RV_SUBTITLE')} />
        <ErrorNote isDark={isDark} error={reviews.error} onRetry={reviews.reload} />
        <Section title={msg('UI_ALERTING_RV_DUE')} items={due} />
        <Section title={msg('UI_ALERTING_RV_SUBMITTED')} items={submitted} />
        {!reviews.loading && !reviews.error && list.length === 0 && <Empty isDark={isDark} text={msg('UI_ALERTING_RV_EMPTY')} />}
        {acts.length > 0 && (
          <div className="mb-5">
            <h2 className={`mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_RV_ACTIONS')}</h2>
            <Card isDark={isDark} className="overflow-hidden"><table className="w-full text-xs"><tbody>{acts.map(a => <ActionRow key={a.action_id} action={a} isDark={isDark} onChanged={refresh} />)}</tbody></table></Card>
          </div>
        )}
      </div>
    </AppShell>
  )
}
