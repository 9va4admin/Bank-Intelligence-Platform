// The bell's drawer: the signed-in user's real notifications. Severity is shown in words (never colour alone), unread in words for screen readers,
// and a failed load says so with a retry instead of looking like an empty inbox.
import { msg } from '../messages'

const SEV_LABEL = { P0: 'UI_INBOX_SEV_P0', P1: 'UI_INBOX_SEV_P1', P2: 'UI_INBOX_SEV_P2', P3: 'UI_INBOX_SEV_P3' }
const SEV_DARK = {
  P0: { dot: 'bg-red-500', badge: 'bg-red-900/50 text-red-300 border-red-700/50' },
  P1: { dot: 'bg-orange-400', badge: 'bg-orange-900/40 text-orange-300 border-orange-700/40' },
  P2: { dot: 'bg-amber-400', badge: 'bg-amber-900/40 text-amber-300 border-amber-700/40' },
  P3: { dot: 'bg-blue-400', badge: 'bg-blue-900/40 text-blue-300 border-blue-700/40' },
}
const SEV_LIGHT = {
  P0: { dot: 'bg-red-500', badge: 'bg-red-50 text-red-700 border-red-200' },
  P1: { dot: 'bg-orange-400', badge: 'bg-orange-50 text-orange-700 border-orange-200' },
  P2: { dot: 'bg-amber-400', badge: 'bg-amber-50 text-amber-700 border-amber-200' },
  P3: { dot: 'bg-blue-400', badge: 'bg-blue-50 text-blue-700 border-blue-200' },
}

export function severityStyle(isDark, severity) {
  return (isDark ? SEV_DARK : SEV_LIGHT)[severity] ?? (isDark ? SEV_DARK : SEV_LIGHT).P3
}

export function severityLabel(severity) {
  return msg(SEV_LABEL[severity] ?? SEV_LABEL.P3)
}

export function timeAgo(iso) {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return msg('UI_APPSHELL_JUST_NOW')
  if (mins < 60) return msg('UI_APPSHELL_M_AGO', { mins })
  return msg('UI_APPSHELL_H_AGO', { hrs: Math.floor(mins / 60) })
}

export default function NotificationDrawer({ open, isDark, items, unread, error, hasMore, onClose, onOpenItem, onReadAll, onRetry, onLoadMore }) {
  if (!open) return null
  const th = {
    panel: isDark ? 'bg-[#06102a] border-white/10' : 'bg-white border-slate-200',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    faint: isDark ? 'text-slate-500' : 'text-slate-400',
    row: isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    rowUnread: isDark ? 'bg-white/2' : 'bg-blue-50/40',
    button: isDark ? 'border-white/10 text-slate-400 hover:text-white hover:bg-white/8' : 'border-slate-200 text-slate-500 hover:bg-slate-50',
  }
  const total = unread?.total ?? 0
  return (
    <>
      <div className="fixed inset-0 z-[200]" onClick={onClose} />
      <aside className={`fixed top-0 right-0 bottom-0 z-[201] flex flex-col border-l shadow-2xl ${th.panel}`} style={{ width: 380 }} aria-label={msg('UI_APPSHELL_NOTIFICATIONS')}>
        <div className={`flex items-center justify-between px-5 py-4 border-b shrink-0 ${th.divider}`}>
          <div>
            <h2 className={`text-sm font-semibold ${th.heading}`}>{msg('UI_APPSHELL_NOTIFICATIONS')}</h2>
            <p className={`text-[11px] mt-0.5 ${th.muted}`}>{total > 0 ? msg('UI_APPSHELL_UNREAD', { unreadCount: total }) : msg('UI_APPSHELL_ALL_CAUGHT_UP')}</p>
          </div>
          <div className="flex items-center gap-2">
            {total > 0 && (
              <button onClick={onReadAll} className={`text-[11px] px-2.5 py-1 rounded-lg border font-medium transition-colors ${th.button}`}>
                {msg('UI_APPSHELL_MARK_ALL_READ')}
              </button>
            )}
            <button onClick={onClose} aria-label={msg('UI_COMMON_CLOSE')} className={`w-7 h-7 flex items-center justify-center rounded-lg ${th.button} border-0`}>
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5"><path strokeLinecap="round" d="M4 4l8 8M12 4l-8 8" /></svg>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {error && items.length === 0 && (
            <div className="px-5 py-8 text-center">
              <p className={`text-xs ${th.muted}`}>{msg('UI_INBOX_ERROR')}</p>
              <button onClick={onRetry} className={`mt-3 text-[11px] px-3 py-1 rounded-lg border font-medium ${th.button}`}>{msg('UI_INBOX_RETRY')}</button>
            </div>
          )}
          {!error && items.length === 0 && <p className={`px-5 py-8 text-center text-xs ${th.muted}`}>{msg('UI_INBOX_EMPTY')}</p>}
          {items.map((n) => {
            const s = severityStyle(isDark, n.severity)
            const unreadItem = !n.read_at
            return (
              <div key={n.notification_id} role="button" tabIndex={0}
                className={`relative px-5 py-4 border-b cursor-pointer transition-colors ${th.row} ${unreadItem ? th.rowUnread : ''}`}
                onClick={() => onOpenItem(n)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpenItem(n) } }}>
                {unreadItem && (
                  <>
                    <span aria-hidden="true" className={`absolute left-2 top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full ${s.dot}`} />
                    <span className="sr-only">{msg('UI_INBOX_UNREAD')}</span>
                  </>
                )}
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${s.badge}`}>{severityLabel(n.severity)}</span>
                  <span className={`text-[10px] ${th.faint}`}>{timeAgo(n.created_at)}</span>
                </div>
                <p className={`text-xs font-semibold leading-snug mb-1 ${th.heading} ${unreadItem ? '' : 'opacity-70'}`}>{n.title}</p>
                <p className={`text-[11px] leading-relaxed ${th.muted}`}>{n.body}</p>
              </div>
            )
          })}
          {hasMore && (
            <div className="px-5 py-3 text-center">
              <button onClick={onLoadMore} className={`text-[11px] px-3 py-1 rounded-lg border font-medium ${th.button}`}>{msg('UI_INBOX_LOAD_MORE')}</button>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
