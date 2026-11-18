/**
 * Delivery Log: every notification attempt (email, WhatsApp, the bell): to whom (masked), on which channel, what happened, and a Retry now button for the ones that
 * failed or are waiting to retry. This is the one delivery log for alerts and for other platform notifications.
 */
import { useState, useCallback, useEffect } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api, query } from '../api'
import { ALERTING_PAGE_SIZE, ALERTING_REFRESH_SECONDS } from '../config'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, useTh, when } from '../ui'

const STATUS_KEY = { QUEUED: 'UI_ALERTING_DL_STATUS_QUEUED', SENT: 'UI_ALERTING_STATE_SENT', DELIVERED: 'UI_ALERTING_STATE_SENT', RETRYING: 'UI_ALERTING_DL_STATUS_RETRYING', FAILED: 'UI_ALERTING_STATE_UNDELIVERED' }
const STATUSES = ['QUEUED', 'SENT', 'RETRYING', 'FAILED']
const CHANNELS = ['email', 'whatsapp', 'bell']
const RETRYABLE = new Set(['FAILED', 'RETRYING'])

function StatusText({ status, isDark }) {
  const muted = useTh(isDark).muted
  const tone = status === 'SENT' || status === 'DELIVERED' ? (isDark ? 'text-emerald-300' : 'text-emerald-700') : status === 'FAILED' ? (isDark ? 'text-red-300' : 'text-red-700')
    : status === 'RETRYING' ? (isDark ? 'text-amber-300' : 'text-amber-700') : muted
  return <span className={`font-semibold ${tone}`}>{msg(STATUS_KEY[status] ?? STATUS_KEY.QUEUED)}</span>
}

export default function DeliveryLog() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const [rows, setRows] = useState([])
  const [cursor, setCursor] = useState(null)
  const [error, setError] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [notes, setNotes] = useState({})

  const base = `/v1/notifications${query({ limit: ALERTING_PAGE_SIZE, delivery_status: status, channel })}`
  const load = useCallback(async () => {
    try {
      const page = await api(base)
      setRows(page.notifications ?? [])
      setCursor(page.next_cursor ?? null)
      setError(null)
    } catch (e) {
      setError(e)
    } finally {
      setLoaded(true)
    }
  }, [base])

  useEffect(() => {
    load()
    const timer = ALERTING_REFRESH_SECONDS > 0 ? setInterval(load, ALERTING_REFRESH_SECONDS * 1000) : null
    return () => { if (timer) clearInterval(timer) }
  }, [load])

  const more = async () => {
    try {
      const page = await api(`${base}${base.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(cursor)}`)
      setRows(prev => [...prev, ...(page.notifications ?? [])])
      setCursor(page.next_cursor ?? null)
    } catch (e) {
      setError(e)
    }
  }

  const retry = async (id) => {
    setNotes(n => ({ ...n, [id]: null }))
    try {
      await api(`/v1/notifications/${id}/retry`, { method: 'POST' })
      setNotes(n => ({ ...n, [id]: { ok: msg('UI_ALERTING_DL_RETRY_QUEUED') } }))
      load()
    } catch (e) {
      setNotes(n => ({ ...n, [id]: { error: e.message } }))
    }
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_DL_TITLE')} subtitle={msg('UI_ALERTING_DL_SUBTITLE')}>
          <Button isDark={isDark} onClick={load}>{msg('UI_ALERTING_REFRESH')}</Button>
        </PageTitle>
        <ErrorNote isDark={isDark} error={error} onRetry={load} />
        <div className="flex gap-3 mb-3">
          <Field isDark={isDark} label={msg('UI_ALERTING_DL_FILTER_STATUS')}>
            <select value={status} onChange={e => setStatus(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 ${th.input}`}>
              <option value="">{msg('UI_ALERTING_ALL')}</option>
              {STATUSES.map(s => <option key={s} value={s}>{msg(STATUS_KEY[s])}</option>)}
            </select>
          </Field>
          <Field isDark={isDark} label={msg('UI_ALERTING_DL_FILTER_CHANNEL')}>
            <select value={channel} onChange={e => setChannel(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 ${th.input}`}>
              <option value="">{msg('UI_ALERTING_ALL')}</option>
              {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </Field>
        </div>
        <Card isDark={isDark} className="overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className={`text-left border-b ${th.divider} ${th.muted}`}>
                <th className="px-3 py-2">{msg('UI_ALERTING_DL_COL_WHEN')}</th><th className="px-3 py-2">{msg('UI_ALERTING_DL_COL_CHANNEL')}</th><th className="px-3 py-2">{msg('UI_ALERTING_DL_COL_TO')}</th>
                <th className="px-3 py-2">{msg('UI_ALERTING_DL_COL_WHAT')}</th><th className="px-3 py-2">{msg('UI_ALERTING_DL_COL_STATUS')}</th><th className="px-3 py-2">{msg('UI_ALERTING_DL_COL_ATTEMPTS')}</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.notification_id} className={`border-b ${th.row}`}>
                  <td className={`px-3 py-2 ${th.muted}`}>{when(r.created_at)}</td>
                  <td className={`px-3 py-2 ${th.body}`}>{r.channel}</td>
                  <td className={`px-3 py-2 ${th.heading}`}>{r.recipient_ref}</td>
                  <td className={`px-3 py-2 ${th.muted}`}>{r.template_id}</td>
                  <td className="px-3 py-2"><StatusText status={r.delivery_status} isDark={isDark} /></td>
                  <td className={`px-3 py-2 ${th.muted}`}>{r.attempt_count}</td>
                  <td className="px-3 py-2 text-right">
                    {RETRYABLE.has(r.delivery_status) && <Button isDark={isDark} onClick={() => retry(r.notification_id)}>{msg('UI_ALERTING_DL_RETRY')}</Button>}
                    {notes[r.notification_id]?.ok && <span className={`ml-2 ${th.muted}`}>{notes[r.notification_id].ok}</span>}
                    {notes[r.notification_id]?.error && <span role="alert" className="ml-2 text-red-500">{notes[r.notification_id].error}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {loaded && rows.length === 0 && !error && <Empty isDark={isDark} text={msg('UI_ALERTING_DL_EMPTY')} />}
          {cursor && <div className="p-3 text-center"><Button isDark={isDark} onClick={more}>{msg('UI_INBOX_LOAD_MORE')}</Button></div>}
        </Card>
      </div>
    </AppShell>
  )
}
