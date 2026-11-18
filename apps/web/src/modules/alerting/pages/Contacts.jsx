/**
 * Alert Contacts: the outside email addresses and phone numbers alerts may go to. A new contact is sent a code; once someone enters it here, the contact is verified,
 * which is what the Go-Live check needs. Addresses are always shown masked. Status is written in words.
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { msg } from '../../../shared/messages'
import { api } from '../api'
import { useLoad } from '../hooks'
import { Button, Card, Empty, ErrorNote, Field, PageTitle, useTh, when } from '../ui'

// why a code was refused, in words (literal keys so the message bundle includes them)
const VERIFY_KEY = {
  wrong_code: 'UI_ALERTING_CT_VERIFY_WRONG', expired: 'UI_ALERTING_CT_VERIFY_EXPIRED', too_many_attempts: 'UI_ALERTING_CT_VERIFY_TOO_MANY', already_verified: 'UI_ALERTING_CT_VERIFY_ALREADY',
}

function AddForm({ isDark, onAdded }) {
  const th = useTh(isDark)
  const [kind, setKind] = useState('email')
  const [address, setAddress] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const submit = async () => {
    setBusy(true); setProblem(null)
    try {
      const r = await api('/v1/admin/alert-contacts', { method: 'POST', body: { kind, address, label } })
      setAddress(''); setLabel('')
      onAdded(r.sent ? msg('UI_ALERTING_CT_ADDED_SENT') : msg('UI_ALERTING_CT_ADDED_NOT_SENT'))
    } catch (e) {
      setProblem(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card isDark={isDark} className="p-4 mb-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field isDark={isDark} label={msg('UI_ALERTING_CT_KIND')}>
          <select value={kind} onChange={e => setKind(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 ${th.input}`}>
            <option value="email">{msg('UI_ALERTING_CT_KIND_EMAIL')}</option>
            <option value="phone">{msg('UI_ALERTING_CT_KIND_PHONE')}</option>
          </select>
        </Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_CT_ADDRESS')}>
          <input value={address} onChange={e => setAddress(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 w-64 ${th.input}`} />
        </Field>
        <Field isDark={isDark} label={msg('UI_ALERTING_CT_LABEL')}>
          <input value={label} onChange={e => setLabel(e.target.value)} className={`text-xs rounded-lg border px-2 py-1.5 w-48 ${th.input}`} />
        </Field>
        <Button isDark={isDark} kind="primary" disabled={busy} onClick={submit}>{msg('UI_ALERTING_CT_ADD')}</Button>
      </div>
      <p className={`text-xs mt-2 ${th.muted}`}>{kind === 'phone' ? msg('UI_ALERTING_CT_PHONE_HELP') : msg('UI_ALERTING_CT_EMAIL_HELP')}</p>
      {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
    </Card>
  )
}

function Row({ contact, isDark, onChanged, onNotice }) {
  const th = useTh(isDark)
  const [entering, setEntering] = useState(false)
  const [code, setCode] = useState('')
  const [problem, setProblem] = useState(null)
  const verified = contact.status === 'VERIFIED'
  const act = async (fn) => {
    setProblem(null)
    try { await fn() } catch (e) { setProblem(e.message) }
  }
  const verify = () => act(async () => {
    const r = await api(`/v1/admin/alert-contacts/${contact.contact_id}/verify`, { method: 'POST', body: { code } })
    if (r.ok) { setEntering(false); setCode(''); onNotice(msg('UI_ALERTING_CT_NOW_VERIFIED', { address: contact.address_masked })); onChanged() } else { setProblem(msg(VERIFY_KEY[r.reason] ?? VERIFY_KEY.wrong_code)) }
  })
  const resend = () => act(async () => {
    const r = await api(`/v1/admin/alert-contacts/${contact.contact_id}/send-code`, { method: 'POST' })
    onNotice(r.sent ? msg('UI_ALERTING_CT_NEW_CODE_SENT') : msg('UI_ALERTING_CT_NEW_CODE_NOT_SENT'))
  })
  const remove = () => act(async () => { await api(`/v1/admin/alert-contacts/${contact.contact_id}`, { method: 'DELETE' }); onChanged() })
  const tone = verified ? (isDark ? 'text-emerald-300' : 'text-emerald-700') : (isDark ? 'text-amber-300' : 'text-amber-700')
  return (
    <>
      <tr className={`border-b ${th.row}`}>
        <td className={`px-3 py-2 font-mono ${th.heading}`}>{contact.address_masked}</td>
        <td className={`px-3 py-2 ${th.body}`}>{contact.kind === 'phone' ? msg('UI_ALERTING_CT_KIND_PHONE') : msg('UI_ALERTING_CT_KIND_EMAIL')}</td>
        <td className={`px-3 py-2 ${th.body}`}>{contact.label}</td>
        <td className={`px-3 py-2 font-semibold ${tone}`}>{verified ? msg('UI_ALERTING_CT_VERIFIED') : msg('UI_ALERTING_CT_NOT_VERIFIED')}</td>
        <td className={`px-3 py-2 ${th.muted}`}>{verified ? `${contact.verified_by}, ${when(contact.verified_at)}` : `${contact.created_by}, ${when(contact.created_at)}`}</td>
        <td className="px-3 py-2 text-right space-x-2 whitespace-nowrap">
          {!verified && <Button isDark={isDark} onClick={() => setEntering(e => !e)}>{msg('UI_ALERTING_CT_ENTER_CODE')}</Button>}
          {!verified && <Button isDark={isDark} onClick={resend}>{msg('UI_ALERTING_CT_SEND_NEW_CODE')}</Button>}
          <Button isDark={isDark} kind="danger" onClick={remove}>{msg('UI_ALERTING_CT_REMOVE')}</Button>
        </td>
      </tr>
      {(entering || problem) && (
        <tr className={`border-b ${th.divider}`}>
          <td colSpan={6} className="px-3 py-3">
            {entering && (
              <div className="flex flex-wrap items-end gap-3">
                <Field isDark={isDark} label={msg('UI_ALERTING_CT_CODE')}><input value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" className={`text-xs rounded-lg border px-2 py-1.5 w-40 ${th.input}`} /></Field>
                <Button isDark={isDark} kind="primary" onClick={verify}>{msg('UI_ALERTING_CT_VERIFY')}</Button>
              </div>
            )}
            {problem && <p role="alert" className="mt-2 text-xs text-red-500">{problem}</p>}
          </td>
        </tr>
      )}
    </>
  )
}

export default function Contacts() {
  const { isDark } = useTheme()
  const th = useTh(isDark)
  const { data, error, loading, reload } = useLoad('/v1/admin/alert-contacts')
  const [notice, setNotice] = useState(null)
  const contacts = data?.contacts ?? []
  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <PageTitle isDark={isDark} title={msg('UI_ALERTING_CT_TITLE')} subtitle={msg('UI_ALERTING_CT_SUBTITLE')} />
        <AddForm isDark={isDark} onAdded={(text) => { setNotice(text); reload() }} />
        {notice && <p role="status" className={`mb-2 text-xs ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{notice}</p>}
        <ErrorNote isDark={isDark} error={error} onRetry={reload} />
        <Card isDark={isDark} className="overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className={`text-left border-b ${th.divider} ${th.muted}`}>
                <th className="px-3 py-2">{msg('UI_ALERTING_CT_COL_ADDRESS')}</th><th className="px-3 py-2">{msg('UI_ALERTING_CT_COL_KIND')}</th><th className="px-3 py-2">{msg('UI_ALERTING_CT_COL_LABEL')}</th>
                <th className="px-3 py-2">{msg('UI_ALERTING_CT_COL_STATUS')}</th><th className="px-3 py-2">{msg('UI_ALERTING_CT_COL_WHO')}</th><th />
              </tr>
            </thead>
            <tbody>{contacts.map(c => <Row key={c.contact_id} contact={c} isDark={isDark} onChanged={reload} onNotice={setNotice} />)}</tbody>
          </table>
          {!loading && contacts.length === 0 && !error && <Empty isDark={isDark} text={msg('UI_ALERTING_CT_EMPTY')} />}
        </Card>
      </div>
    </AppShell>
  )
}
