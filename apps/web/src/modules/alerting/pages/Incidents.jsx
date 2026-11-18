/**
 * Incidents: every alert incident, current and past, with its timeline (what was sent, to whom, how it went, who acknowledged, whether it escalated) and an
 * Acknowledge button. Recipients are shown masked. A notification's link from the bell opens the incident here (/ops/incidents/:incidentId).
 */
import { useState, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api, query } from '../api'
import { useLoad } from '../hooks'
import { ALERTING_PAGE_SIZE } from '../config'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, SeverityBadge, StateBadge, ago, useTh, when } from '../ui'

const STATES = ['OPEN', 'ACKED', 'RESOLVED']
const SEVERITIES = ['P0', 'P1', 'P2', 'P3']

function timeline(detail) {
  const inc = detail?.incident
  if (!inc) return []
  const events = [{ at: inc.opened_at, key: 'opened', text: msg('UI_ALERTING_INC_TL_OPENED') }]
  for (const d of detail.deliveries ?? []) {
    events.push({ at: d.created_at, key: `d-${d.delivery_id}`, delivery: d })
  }
  if (inc.acked_at) events.push({ at: inc.acked_at, key: 'acked', text: msg('UI_ALERTING_INC_TL_ACKED', { who: inc.acked_by ?? '' }) })
  if (inc.resolved_at) events.push({ at: inc.resolved_at, key: 'resolved', text: msg('UI_ALERTING_INC_TL_RESOLVED') })
  return events.sort((a, b) => String(a.at).localeCompare(String(b.at)))
}

function Detail({ id, isDark, onChanged }) {
  const th = useTh(isDark)
  const { data, error, reload } = useLoad(`/v1/ops/alerts/incidents/${id}`)
  const [busy, setBusy] = useState(false)
  const [ackError, setAckError] = useState(null)
  const inc = data?.incident
  const events = useMemo(() => timeline(data), [data])

  const acknowledge = async () => {
    setBusy(true); setAckError(null)
    try {
      await api(`/v1/ops/alerts/incidents/${id}/acknowledge`, { method: 'POST' })
      await reload()
      onChanged()
    } catch (e) {
      setAckError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !data) return <ErrorNote isDark={isDark} error={error} onRetry={reload} />
  if (!inc) return null
  return (
    <Card isDark={isDark} className="p-4">
      <div className="flex items-center gap-2 mb-2">
        <SeverityBadge severity={inc.severity} isDark={isDark} />
        <StateBadge state={inc.state} isDark={isDark} />
        <span className={`text-xs ${th.muted}`}>{inc.component}</span>
      </div>
      <h2 className={`text-sm font-semibold ${th.heading}`}>{inc.summary}</h2>
      {inc.impact && <p className={`text-xs mt-2 ${th.body}`}><span className={th.muted}>{msg('UI_ALERTING_INC_IMPACT')}: </span>{inc.impact}</p>}
      <p className={`text-xs mt-1 ${th.muted}`}>{msg('UI_ALERTING_INC_ESCALATION_LEVEL', { level: inc.escalation_level ?? 0 })}</p>
      {inc.state === 'OPEN' && (
        <div className="mt-3">
          <Button isDark={isDark} kind="primary" disabled={busy} onClick={acknowledge}>{msg('UI_INBOX_ACK')}</Button>
        </div>
      )}
      {ackError && <p role="alert" className="mt-2 text-xs text-red-500">{ackError}</p>}
      <h3 className={`mt-4 mb-1 text-[11px] font-semibold uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_INC_TIMELINE')}</h3>
      <ol className="space-y-2">
        {events.map(e => (
          <li key={e.key} className={`text-xs border-l-2 pl-3 ${th.divider} ${th.body}`}>
            <span className={`mr-2 ${th.faint}`}>{when(e.at)}</span>
            {e.delivery ? (
              <span>
                {msg('UI_ALERTING_INC_TL_SENT', { channel: e.delivery.channel, to: e.delivery.recipient_ref })} <StateBadge state={e.delivery.status} isDark={isDark} />
                {e.delivery.attempt > 1 && <span className={`ml-1 ${th.muted}`}>{msg('UI_ALERTING_ATTEMPT', { attempt: e.delivery.attempt })}</span>}
                {e.delivery.provider_class && e.delivery.status !== 'SENT' && <span className={`ml-1 ${th.muted}`}>({e.delivery.provider_class})</span>}
              </span>
            ) : <span>{e.text}</span>}
          </li>
        ))}
      </ol>
    </Card>
  )
}

export default function Incidents() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const navigate = useNavigate()
  const { incidentId } = useParams()
  const [state, setState] = useState('')
  const [severity, setSeverity] = useState('')
  const { data, error, loading, reload } = useLoad(`/v1/ops/alerts/incidents${query({ limit: ALERTING_PAGE_SIZE, state, severity })}`)
  const rows = data?.incidents ?? []

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_INC_TITLE')} subtitle={msg('UI_ALERTING_INC_SUBTITLE')}>
          <Button isDark={isDark} onClick={reload}>{msg('UI_ALERTING_REFRESH')}</Button>
        </PageTitle>
        <ErrorNote isDark={isDark} error={error} onRetry={reload} />
        <div className="flex gap-3 mb-3">
          <Field isDark={isDark} label={msg('UI_ALERTING_FILTER_STATE')}>
            <select value={state} onChange={e => setState(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 ${th.input}`}>
              <option value="">{msg('UI_ALERTING_ALL')}</option>
              {STATES.map(s => <option key={s} value={s}>{s === 'OPEN' ? msg('UI_ALERTING_STATE_OPEN') : s === 'ACKED' ? msg('UI_ALERTING_STATE_ACKED') : msg('UI_ALERTING_STATE_RESOLVED')}</option>)}
            </select>
          </Field>
          <Field isDark={isDark} label={msg('UI_ALERTING_FILTER_SEVERITY')}>
            <select value={severity} onChange={e => setSeverity(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 ${th.input}`}>
              <option value="">{msg('UI_ALERTING_ALL')}</option>
              {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
        </div>
        <div className="flex gap-4 items-start">
          <Card isDark={isDark} className="flex-1 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className={`text-left border-b ${th.divider} ${th.muted}`}>
                  <th className="px-3 py-2">{msg('UI_ALERTING_COL_SEVERITY')}</th><th className="px-3 py-2">{msg('UI_ALERTING_COL_COMPONENT')}</th><th className="px-3 py-2">{msg('UI_ALERTING_COL_SUMMARY')}</th>
                  <th className="px-3 py-2">{msg('UI_ALERTING_COL_STATE')}</th><th className="px-3 py-2">{msg('UI_ALERTING_COL_OPENED')}</th><th className="px-3 py-2">{msg('UI_ALERTING_COL_NOTIFIED')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.incident_id} onClick={() => navigate(`/ops/incidents/${r.incident_id}`)}
                    className={`border-b cursor-pointer ${th.row} ${incidentId === r.incident_id ? th.rowActive : ''}`}>
                    <td className="px-3 py-2"><SeverityBadge severity={r.severity} isDark={isDark} /></td>
                    <td className={`px-3 py-2 ${th.body}`}>{r.component}</td>
                    <td className={`px-3 py-2 ${th.heading}`}>{r.summary}</td>
                    <td className="px-3 py-2"><StateBadge state={r.state} isDark={isDark} /></td>
                    <td className={`px-3 py-2 ${th.muted}`}>{ago(r.opened_at)}</td>
                    <td className={`px-3 py-2 ${th.muted}`}>{r.notification_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && rows.length === 0 && !error && <Empty isDark={isDark} text={msg('UI_ALERTING_INC_EMPTY')} />}
          </Card>
          {incidentId && <div style={{ width: 420 }} className="shrink-0"><Detail key={incidentId} id={incidentId} isDark={isDark} onChanged={reload} /></div>}
        </div>
      </div>
    </AppShell>
  )
}
