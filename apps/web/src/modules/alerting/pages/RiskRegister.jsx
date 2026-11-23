/**
 * Risk Register: the risks to alerting itself. Each has an owner, a rating (likelihood x impact), a mitigation and a review date. A person declares a risk mitigated and
 * a DIFFERENT person verifies it; the system never closes a risk by itself. Status is written in words.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api, download } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, useTh } from '../ui'

const STATUS_KEY = { OPEN: 'UI_ALERTING_RK_STATUS_OPEN', MITIGATED: 'UI_ALERTING_RK_STATUS_MITIGATED', VERIFIED: 'UI_ALERTING_RK_STATUS_VERIFIED' }

function Row({ risk, isDark, onChanged }) {
  const th = useTh(isDark)
  const [editing, setEditing] = useState(false)
  const [owner, setOwner] = useState(risk.owner ?? '')
  const [mitigation, setMitigation] = useState(risk.mitigation ?? '')
  const [likelihood, setLikelihood] = useState(String(risk.likelihood))
  const [impact, setImpact] = useState(String(risk.impact))
  const [problem, setProblem] = useState(null)
  const act = async (fn) => {
    setProblem(null)
    try { await fn(); onChanged() } catch (e) { setProblem(e.message) }
  }
  const post = (action) => act(() => api(`/v1/admin/alert-risks/${risk.risk_id}/${action}`, { method: 'POST' }))
  const save = () => act(async () => {
    await api(`/v1/admin/alert-risks/${risk.risk_id}`, { method: 'PATCH', body: { owner, mitigation, likelihood: Number(likelihood), impact: Number(impact) } })
    setEditing(false)
  })
  const tone = risk.status === 'VERIFIED' ? (isDark ? 'text-emerald-300' : 'text-emerald-700') : risk.status === 'MITIGATED' ? (isDark ? 'text-amber-300' : 'text-amber-700') : th.body
  return (
    <>
      <tr className={`border-b align-top ${th.row}`}>
        <td className={`px-3 py-2 ${th.muted}`}>{msg('UI_ALERTING_RK_RATING', { rating: risk.rating, likelihood: risk.likelihood, impact: risk.impact })}</td>
        <td className="px-3 py-2"><p className={`font-semibold ${th.heading}`}>{risk.title}</p><p className={th.muted}>{risk.description}</p></td>
        <td className={`px-3 py-2 ${risk.owner ? th.body : (isDark ? 'text-red-300' : 'text-red-700')}`}>{risk.owner ?? msg('UI_ALERTING_RK_NO_OWNER')}</td>
        <td className={`px-3 py-2 font-semibold ${tone}`}>{msg(STATUS_KEY[risk.status])}</td>
        <td className={`px-3 py-2 ${th.muted}`}>{risk.next_review_on ?? ''}</td>
        <td className="px-3 py-2 text-right space-x-2 whitespace-nowrap">
          <Button isDark={isDark} onClick={() => setEditing(e => !e)}>{msg('UI_ALERTING_RK_EDIT')}</Button>
          {risk.status === 'OPEN' && risk.owner && risk.mitigation && <Button isDark={isDark} onClick={() => post('declare-mitigated')}>{msg('UI_ALERTING_RK_DECLARE')}</Button>}
          {risk.status === 'MITIGATED' && <Button isDark={isDark} kind="primary" onClick={() => post('verify')}>{msg('UI_ALERTING_RK_VERIFY')}</Button>}
          {risk.status !== 'OPEN' && <Button isDark={isDark} kind="danger" onClick={() => post('reopen')}>{msg('UI_ALERTING_RK_REOPEN')}</Button>}
        </td>
      </tr>
      {(editing || problem) && (
        <tr className={`border-b ${th.divider}`}>
          <td colSpan={6} className="px-3 py-3">
            {editing && (
              <div className="flex flex-wrap items-end gap-3">
                <Field isDark={isDark} label={msg('UI_ALERTING_RK_OWNER')}><input value={owner} onChange={e => setOwner(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 w-48 ${th.input}`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RK_MITIGATION')}><input value={mitigation} onChange={e => setMitigation(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 w-96 ${th.input}`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RK_LIKELIHOOD')}><input value={likelihood} onChange={e => setLikelihood(e.target.value)} inputMode="numeric" className={`text-xs rounded-lg border px-2 py-1.5 w-16 ${th.input}`} /></Field>
                <Field isDark={isDark} label={msg('UI_ALERTING_RK_IMPACT')}><input value={impact} onChange={e => setImpact(e.target.value)} inputMode="numeric" className={`text-xs rounded-lg border px-2 py-1.5 w-16 ${th.input}`} /></Field>
                <Button isDark={isDark} kind="primary" onClick={save}>{msg('UI_ALERTING_RK_SAVE')}</Button>
              </div>
            )}
            {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

export default function RiskRegister() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const { data, error, loading, reload } = useLoad('/v1/admin/alert-risks')
  const [problem, setProblem] = useState(null)
  const risks = data?.risks ?? []
  const s = data?.summary
  const report = async () => {
    setProblem(null)
    try { await download('/v1/admin/alert-risks/export', 'alert-risk-register.csv') } catch (e) { setProblem(e.message) }
  }
  const seed = async () => {
    setProblem(null)
    try { await api('/v1/admin/alert-risks/seed', { method: 'POST' }); reload() } catch (e) { setProblem(e.message) }
  }
  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_RK_TITLE')} subtitle={msg('UI_ALERTING_RK_SUBTITLE')}>
          {data && risks.length === 0 && <Button isDark={isDark} kind="primary" onClick={seed}>{msg('UI_ALERTING_RK_SEED')}</Button>}
          {data && risks.length > 0 && <Button isDark={isDark} onClick={report}>{msg('UI_ALERTING_RK_DOWNLOAD')}</Button>}
        </PageTitle>
        <ErrorNote isDark={isDark} error={error} onRetry={reload} />
        {problem && <p role="alert" className="mb-2 text-xs text-red-500">{problem}</p>}
        {s && risks.length > 0 && <p className={`mb-3 text-xs ${th.body}`}>{msg('UI_ALERTING_RK_SUMMARY', { total: s.total, without: s.without_owner, overdue: s.review_overdue, verified: s.verified })}</p>}
        {risks.length > 0 && (
          <Card isDark={isDark} className="overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className={`text-left border-b ${th.divider} ${th.muted}`}>
                  <th className="px-3 py-2">{msg('UI_ALERTING_RK_COL_RATING')}</th><th className="px-3 py-2">{msg('UI_ALERTING_RK_COL_RISK')}</th><th className="px-3 py-2">{msg('UI_ALERTING_RK_COL_OWNER')}</th>
                  <th className="px-3 py-2">{msg('UI_ALERTING_RK_COL_STATUS')}</th><th className="px-3 py-2">{msg('UI_ALERTING_RK_COL_REVIEW')}</th><th />
                </tr>
              </thead>
              <tbody>{risks.map(r => <Row key={r.risk_id} risk={r} isDark={isDark} onChanged={reload} />)}</tbody>
            </table>
          </Card>
        )}
        {!loading && !error && risks.length === 0 && <Empty isDark={isDark} text={msg('UI_ALERTING_RK_EMPTY')} />}
      </div>
    </AppShell>
  )
}
