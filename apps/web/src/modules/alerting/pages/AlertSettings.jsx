/**
 * Alert Settings: what can carry an alert on this deployment (email, WhatsApp, the in-app bell), and the alert settings a bank controls: recipients, priority floors, working hours,
 * delivery retries, reminder and retention limits. A change is submitted with a reason and must be approved by a different person (the same maker-checker as the other settings).
 * Connection details (mail server, WhatsApp account) are deployment settings and secrets; they are shown here, never edited and never revealed.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, StateBadge, useTh, when } from '../ui'

const MIN_REASON = 10
const isAlertKey = (key) => key.startsWith('alerts.') || key.startsWith('alerting.')

function Channels({ isDark }) {
  const th = useTh(isDark)
  const { data, error, reload } = useLoad('/v1/admin/alert-routing/channels')
  const tone = (ok) => (ok ? (isDark ? 'text-emerald-300' : 'text-emerald-700') : (isDark ? 'text-amber-300' : 'text-amber-700'))
  const email = data?.email
  return (
    <Card isDark={isDark} className="p-4">
      <ErrorNote isDark={isDark} error={error} onRetry={reload} />
      {data && (
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className={`text-[11px] uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_ST_EMAIL')}</p>
            <p className={`text-sm font-semibold ${tone(email?.configured)}`}>{email?.configured ? msg('UI_ALERTING_ST_CONFIGURED') : msg('UI_ALERTING_ST_NOT_CONFIGURED')}</p>
            {email?.configured
              ? <p className={`text-xs ${th.body}`}>{email.host}{email.port ? `:${email.port}` : ''} {email.security ? `(${email.security})` : ''}{email.from_address ? ` - ${email.from_address}` : ''}</p>
              : <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_ST_EMAIL_HOWTO')}</p>}
            <p className={`text-xs mt-1 ${th.muted}`}>{msg('UI_ALERTING_ST_RECIPIENTS', { count: data.email_recipients ?? 0 })}</p>
          </div>
          <div>
            <p className={`text-[11px] uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_ST_WHATSAPP')}</p>
            <p className={`text-sm font-semibold ${tone(data.whatsapp?.configured)}`}>{data.whatsapp?.configured ? msg('UI_ALERTING_ST_CONFIGURED') : msg('UI_ALERTING_ST_NOT_CONFIGURED')}</p>
            <p className={`text-xs mt-1 ${th.muted}`}>{msg('UI_ALERTING_ST_RECIPIENTS', { count: data.whatsapp_recipients ?? 0 })}</p>
          </div>
          <div>
            <p className={`text-[11px] uppercase tracking-wide ${th.muted}`}>{msg('UI_ALERTING_ST_BELL')}</p>
            <p className={`text-sm font-semibold ${tone(data.bell?.configured)}`}>{data.bell?.configured ? msg('UI_ALERTING_ST_CONFIGURED') : msg('UI_ALERTING_ST_NOT_CONFIGURED')}</p>
          </div>
        </div>
      )}
      {email?.configured && email.public_provider && (
        <p role="note" className={`mt-3 rounded-lg border px-3 py-2 text-xs ${isDark ? 'border-amber-700/40 bg-amber-900/20 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>{msg('UI_ALERTING_ST_PUBLIC_PROVIDER')}</p>
      )}
    </Card>
  )
}

// the reason a proof failed, in words (literal keys so the message bundle includes them)
const PROOF_REASON = {
  not_connected: 'UI_GOLIVE_ALERT_AUDIT_REASON_NOT_CONNECTED', write_failed: 'UI_GOLIVE_ALERT_AUDIT_REASON_WRITE_FAILED', verify_failed: 'UI_GOLIVE_ALERT_AUDIT_REASON_VERIFY_FAILED',
  missing_records: 'UI_ALERTING_PF_DNS_REASON_MISSING', lookup_failed: 'UI_ALERTING_PF_DNS_REASON_LOOKUP',
}

function ProofLine({ isDark, last, loaded, onRun, text }) {
  const th = useTh(isDark)
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true); setProblem(null)
    try { await onRun() } catch (e) { setProblem(e.message) } finally { setBusy(false) }
  }
  const reason = last && !last.ok ? (PROOF_REASON[last.reason] ? msg(PROOF_REASON[last.reason]) : (last.reason ?? '')) : ''
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className={`text-sm font-semibold ${th.heading}`}>{text.title}</p>
          <p className={`text-xs ${th.muted}`}>{text.help}</p>
          {loaded && !last && <p className={`text-xs mt-1 ${th.body}`}>{text.never}</p>}
          {last && last.ok && <p className={`text-xs mt-1 ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{text.passed({ when: when(last.ran_at), who: last.ran_by })}</p>}
          {last && !last.ok && <p className={`text-xs mt-1 ${isDark ? 'text-red-300' : 'text-red-700'}`}>{text.failed({ when: when(last.ran_at), reason, who: last.ran_by })}</p>}
        </div>
        <Button isDark={isDark} kind="primary" disabled={busy} onClick={run}>{text.run}</Button>
      </div>
      {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
    </div>
  )
}

function DrillLine({ isDark, last, onStarted }) {
  const th = useTh(isDark)
  const [problem, setProblem] = useState(null)
  const [started, setStarted] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true); setProblem(null)
    try {
      const r = await api('/v1/platform/alert-proofs/fire-drill', { method: 'POST' })
      setStarted(msg('UI_ALERTING_PF_DRILL_STARTED', { minutes: r.ack_within_minutes }))
      onStarted()
    } catch (e) { setProblem(e.message) } finally { setBusy(false) }
  }
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className={`text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_PF_DRILL_TITLE')}</p>
          <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_PF_DRILL_HELP')}</p>
          {last && <p className={`text-xs mt-1 ${th.body}`}>{msg('UI_ALERTING_PF_DRILL_LAST', { when: when(last.ran_at), who: last.ran_by })}</p>}
          {started && <p role="status" className={`text-xs mt-1 ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{started}</p>}
        </div>
        <Button isDark={isDark} kind="primary" disabled={busy} onClick={run}>{msg('UI_ALERTING_PF_DRILL_RUN')}</Button>
      </div>
      {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
    </div>
  )
}

function Proofs({ isDark }) {
  const th = useTh(isDark)
  const { data, error, reload } = useLoad('/v1/platform/alert-proofs')
  const post = (path) => async () => { await api(path, { method: 'POST' }); reload() }
  return (
    <Card isDark={isDark} className="p-4 space-y-4">
      <ErrorNote isDark={isDark} error={error} onRetry={reload} />
      <ProofLine isDark={isDark} loaded={!!data} last={data?.audit_path} onRun={post('/v1/platform/alert-proofs/audit-path')}
        text={{ title: msg('UI_ALERTING_PF_AUDIT_TITLE'), help: msg('UI_ALERTING_PF_AUDIT_HELP'), never: msg('UI_ALERTING_PF_AUDIT_NEVER'), run: msg('UI_ALERTING_PF_AUDIT_RUN'),
          passed: (v) => msg('UI_ALERTING_PF_AUDIT_PASSED', v), failed: (v) => msg('UI_ALERTING_PF_AUDIT_FAILED', v) }} />
      <div className={`border-t ${th.divider}`} />
      <ProofLine isDark={isDark} loaded={!!data} last={data?.mail_dns} onRun={post('/v1/platform/alert-proofs/mail-dns')}
        text={{ title: msg('UI_ALERTING_PF_DNS_TITLE'), help: msg('UI_ALERTING_PF_DNS_HELP'), never: msg('UI_ALERTING_PF_DNS_NEVER'), run: msg('UI_ALERTING_PF_DNS_RUN'),
          passed: (v) => msg('UI_ALERTING_PF_DNS_PASSED', v), failed: (v) => msg('UI_ALERTING_PF_DNS_FAILED', v) }} />
      <div className={`border-t ${th.divider}`} />
      <DrillLine isDark={isDark} last={data?.fire_drill} onStarted={reload} />
    </Card>
  )
}

function Row({ entry, isDark, onSubmitted }) {
  const th = useTh(isDark)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(entry.current_value)
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (reason.trim().length < MIN_REASON) { setProblem(msg('UI_ALERTING_ST_REASON_SHORT', { min: MIN_REASON })); return }
    setBusy(true); setProblem(null)
    try {
      await api('/v1/admin/config/thresholds', { method: 'POST', body: { config_key: entry.config_key, new_value: value, reason: reason.trim() } })
      setEditing(false); setReason('')
      onSubmitted(msg('UI_ALERTING_ST_SUBMITTED', { key: entry.config_key }))
    } catch (e) {
      setProblem(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <tr className={`border-b ${th.row}`}>
        <td className={`px-3 py-2 font-mono ${th.heading}`}>{entry.config_key}</td>
        <td className={`px-3 py-2 ${th.muted}`}>{entry.description}</td>
        <td className={`px-3 py-2 ${th.body}`}>{entry.current_value === '' ? msg('UI_ALERTING_ST_EMPTY_VALUE') : entry.current_value}</td>
        <td className="px-3 py-2 text-right"><Button isDark={isDark} onClick={() => setEditing(e => !e)}>{msg('UI_ALERTING_ST_CHANGE')}</Button></td>
      </tr>
      {editing && (
        <tr className={`border-b ${th.divider}`}>
          <td colSpan={4} className="px-3 py-3">
            <div className="flex flex-wrap items-end gap-3">
              <Field isDark={isDark} label={msg('UI_ALERTING_ST_NEW_VALUE')}><input value={value} onChange={e => setValue(e.target.value)} className={`text-xs rounded-lg border px-2 py-1 w-72 ${th.input}`} /></Field>
              <Field isDark={isDark} label={msg('UI_ALERTING_ST_REASON', { min: MIN_REASON })}><input value={reason} onChange={e => setReason(e.target.value)} className={`text-xs rounded-lg border px-2 py-1 w-80 ${th.input}`} /></Field>
              <Button isDark={isDark} kind="primary" disabled={busy} onClick={submit}>{msg('UI_ALERTING_ST_SUBMIT')}</Button>
            </div>
            {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

function Pending({ isDark, changes, reload }) {
  const th = useTh(isDark)
  const [notes, setNotes] = useState({})
  const act = async (id, action) => {
    setNotes(n => ({ ...n, [id]: null }))
    try { await api(`/v1/admin/config/thresholds/${id}/${action}`, { method: 'POST', body: action === 'reject' ? { reason: msg('UI_ALERTING_ST_REJECT_REASON') } : undefined }); reload() } catch (e) { setNotes(n => ({ ...n, [id]: e.message })) }
  }
  if (!changes.length) return <p className={`text-xs ${th.muted}`}>{msg('UI_ALERTING_ST_NO_PENDING')}</p>
  return (
    <div className="space-y-2">
      {changes.map(c => (
        <div key={c.change_id} className={`rounded-lg border p-3 ${th.divider}`}>
          <div className="flex flex-wrap items-center gap-3">
            <StateBadge state="PENDING" isDark={isDark} />
            <span className={`text-xs font-mono ${th.heading}`}>{c.config_key}</span>
            <span className={`text-xs ${th.body}`}>{msg('UI_ALERTING_ST_TO', { value: c.new_value })}</span>
            <span className={`text-xs ${th.muted}`}>{c.reason} - {msg('UI_ALERTING_RT_PROPOSED_BY', { who: c.submitted_by })}, {when(c.submitted_at)}</span>
            <span className="flex gap-2 ml-auto">
              <Button isDark={isDark} kind="primary" onClick={() => act(c.change_id, 'approve')}>{msg('UI_ALERTING_RT_APPROVE')}</Button>
              <Button isDark={isDark} kind="danger" onClick={() => act(c.change_id, 'reject')}>{msg('UI_ALERTING_RT_REJECT')}</Button>
            </span>
          </div>
          {notes[c.change_id] && <p role="alert" className="mt-2 text-xs text-red-500">{notes[c.change_id]}</p>}
        </div>
      ))}
    </div>
  )
}

export default function AlertSettings() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const settings = useLoad('/v1/admin/config/thresholds')
  const changes = useLoad('/v1/admin/config/thresholds/changes?limit=100')
  const [notice, setNotice] = useState(null)
  const rows = (settings.data?.thresholds ?? []).filter(t => isAlertKey(t.config_key))
  const pending = (changes.data?.changes ?? []).filter(c => c.status === 'PENDING_APPROVAL' && isAlertKey(c.config_key))
  const refresh = () => { settings.reload(); changes.reload() }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_ST_TITLE')} subtitle={msg('UI_ALERTING_ST_SUBTITLE')} />
        <Channels isDark={isDark} />
        <h2 className={`mt-6 mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_PF_TITLE')}</h2>
        <Proofs isDark={isDark} />
        <h2 className={`mt-6 mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_ST_SETTINGS')}</h2>
        <ErrorNote isDark={isDark} error={settings.error} onRetry={settings.reload} />
        {notice && <p role="status" className={`mb-2 text-xs ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{notice}</p>}
        <Card isDark={isDark} className="overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className={`text-left border-b ${th.divider} ${th.muted}`}>
              <th className="px-3 py-2">{msg('UI_ALERTING_ST_COL_SETTING')}</th><th className="px-3 py-2">{msg('UI_ALERTING_ST_COL_MEANING')}</th><th className="px-3 py-2">{msg('UI_ALERTING_ST_COL_VALUE')}</th><th />
            </tr></thead>
            <tbody>{rows.map(r => <Row key={r.config_key} entry={r} isDark={isDark} onSubmitted={(text) => { setNotice(text); refresh() }} />)}</tbody>
          </table>
          {!settings.loading && rows.length === 0 && !settings.error && <Empty isDark={isDark} text={msg('UI_ALERTING_ST_EMPTY')} />}
        </Card>
        <h2 className={`mt-6 mb-2 text-sm font-semibold ${th.heading}`}>{msg('UI_ALERTING_RT_PENDING')}</h2>
        <Card isDark={isDark} className="p-4"><Pending isDark={isDark} changes={pending} reload={refresh} /></Card>
      </div>
    </AppShell>
  )
}
