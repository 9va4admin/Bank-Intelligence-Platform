// Critical alerts nobody has acknowledged yet, pinned above every page. Not dismissible except by acknowledging (the server decides whether the
// person's role also acknowledges the incident). Announced to assistive technology as an alert.
import { useState } from 'react'
import { msg } from '../messages'
import { severityLabel, timeAgo } from './NotificationDrawer'

export default function PinnedAlerts({ items, isDark, onAcknowledge, onOpen }) {
  const [failed, setFailed] = useState({})
  const [busy, setBusy] = useState({})
  if (!items || items.length === 0) return null
  const th = {
    bar: isDark ? 'bg-red-950/70 border-red-800/60' : 'bg-red-50 border-red-200',
    heading: isDark ? 'text-red-200' : 'text-red-800',
    title: isDark ? 'text-white' : 'text-slate-900',
    body: isDark ? 'text-slate-300' : 'text-slate-600',
    faint: isDark ? 'text-red-300/70' : 'text-red-700/70',
    button: isDark ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-red-600 hover:bg-red-700 text-white',
    error: isDark ? 'text-amber-300' : 'text-amber-700',
  }
  const acknowledge = async (id) => {
    setBusy(b => ({ ...b, [id]: true }))
    const ok = await onAcknowledge(id)
    setBusy(b => ({ ...b, [id]: false }))
    setFailed(f => ({ ...f, [id]: !ok }))
  }
  return (
    <div role="alert" className={`border-b px-6 py-2 ${th.bar}`}>
      <p className={`text-[11px] font-semibold uppercase tracking-wide ${th.heading}`}>{msg('UI_INBOX_PINNED_TITLE', { count: items.length })}</p>
      <ul className="mt-1 space-y-1.5">
        {items.map((n) => (
          <li key={n.notification_id} className="flex items-start gap-3">
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border border-red-500/50 ${th.heading}`}>{severityLabel(n.severity)}</span>
            <div className="flex-1 min-w-0">
              <button type="button" onClick={() => onOpen(n)} className={`text-xs font-semibold text-left hover:underline ${th.title}`}>{n.title}</button>
              <p className={`text-[11px] ${th.body}`}>{n.body}</p>
              <p className={`text-[10px] ${th.faint}`}>{timeAgo(n.created_at)}</p>
              {failed[n.notification_id] && <p className={`text-[11px] ${th.error}`}>{msg('UI_INBOX_ACK_FAILED')}</p>}
            </div>
            <button type="button" disabled={busy[n.notification_id]} onClick={() => acknowledge(n.notification_id)}
              className={`text-[11px] font-medium px-3 py-1 rounded-lg shrink-0 disabled:opacity-60 ${th.button}`}>{msg('UI_INBOX_ACK')}</button>
          </li>
        ))}
      </ul>
    </div>
  )
}
