// Small building blocks shared by the alerting screens. Theme-aware (dark and light); status and severity are always written in words, never colour alone.
import { msg } from '../../shared/messages'

export function useTh(isDark) {
  return {
    page: isDark ? 'bg-navy-950' : 'bg-slate-50',
    card: isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body: isDark ? 'text-slate-300' : 'text-slate-700',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    faint: isDark ? 'text-slate-500' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row: isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    rowActive: isDark ? 'bg-white/5' : 'bg-blue-50',
    input: isDark ? 'bg-navy-950 border-white/10 text-slate-100 placeholder-slate-500' : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400',
    button: isDark ? 'border-white/10 text-slate-300 hover:bg-white/8' : 'border-slate-300 text-slate-700 hover:bg-slate-50',
    primary: 'bg-blue-600 hover:bg-blue-500 text-white',
    danger: isDark ? 'border-red-700/50 text-red-300 hover:bg-red-900/30' : 'border-red-300 text-red-700 hover:bg-red-50',
  }
}

const SEV_DARK = { P0: 'bg-red-900/50 text-red-300 border-red-700/50', P1: 'bg-orange-900/40 text-orange-300 border-orange-700/40', P2: 'bg-amber-900/40 text-amber-300 border-amber-700/40', P3: 'bg-blue-900/40 text-blue-300 border-blue-700/40' }
const SEV_LIGHT = { P0: 'bg-red-50 text-red-700 border-red-200', P1: 'bg-orange-50 text-orange-700 border-orange-200', P2: 'bg-amber-50 text-amber-700 border-amber-200', P3: 'bg-blue-50 text-blue-700 border-blue-200' }
const STATE_DARK = { OPEN: 'bg-red-900/40 text-red-300 border-red-700/40', ACKED: 'bg-amber-900/40 text-amber-300 border-amber-700/40', RESOLVED: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  PENDING: 'bg-slate-800 text-slate-300 border-white/10', SENDING: 'bg-slate-800 text-slate-300 border-white/10', SENT: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  FAILED: 'bg-amber-900/40 text-amber-300 border-amber-700/40', UNDELIVERED: 'bg-red-900/40 text-red-300 border-red-700/40', SKIPPED: 'bg-slate-800 text-slate-400 border-white/10',
  ACTIVE: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40', SUPERSEDED: 'bg-slate-800 text-slate-400 border-white/10', REJECTED: 'bg-red-900/40 text-red-300 border-red-700/40' }
const STATE_LIGHT = { OPEN: 'bg-red-50 text-red-700 border-red-200', ACKED: 'bg-amber-50 text-amber-700 border-amber-200', RESOLVED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  PENDING: 'bg-slate-100 text-slate-700 border-slate-200', SENDING: 'bg-slate-100 text-slate-700 border-slate-200', SENT: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  FAILED: 'bg-amber-50 text-amber-700 border-amber-200', UNDELIVERED: 'bg-red-50 text-red-700 border-red-200', SKIPPED: 'bg-slate-100 text-slate-500 border-slate-200',
  ACTIVE: 'bg-emerald-50 text-emerald-700 border-emerald-200', SUPERSEDED: 'bg-slate-100 text-slate-500 border-slate-200', REJECTED: 'bg-red-50 text-red-700 border-red-200' }

const SEV_KEY = { P0: 'UI_INBOX_SEV_P0', P1: 'UI_INBOX_SEV_P1', P2: 'UI_INBOX_SEV_P2', P3: 'UI_INBOX_SEV_P3' }
const STATE_KEY = {
  OPEN: 'UI_ALERTING_STATE_OPEN', ACKED: 'UI_ALERTING_STATE_ACKED', RESOLVED: 'UI_ALERTING_STATE_RESOLVED', PENDING: 'UI_ALERTING_STATE_PENDING', SENDING: 'UI_ALERTING_STATE_SENDING',
  SENT: 'UI_ALERTING_STATE_SENT', FAILED: 'UI_ALERTING_STATE_FAILED', UNDELIVERED: 'UI_ALERTING_STATE_UNDELIVERED', SKIPPED: 'UI_ALERTING_STATE_SKIPPED',
  ACTIVE: 'UI_ALERTING_STATE_ACTIVE', SUPERSEDED: 'UI_ALERTING_STATE_SUPERSEDED', REJECTED: 'UI_ALERTING_STATE_REJECTED',
}

export function SeverityBadge({ severity, isDark }) {
  const cls = (isDark ? SEV_DARK : SEV_LIGHT)[severity] ?? (isDark ? SEV_DARK : SEV_LIGHT).P3
  return <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${cls}`}>{msg(SEV_KEY[severity] ?? SEV_KEY.P3)}</span>
}

export function StateBadge({ state, isDark }) {
  const cls = (isDark ? STATE_DARK : STATE_LIGHT)[state] ?? (isDark ? STATE_DARK : STATE_LIGHT).PENDING
  return <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${cls}`}>{msg(STATE_KEY[state] ?? STATE_KEY.PENDING)}</span>
}

export function Card({ isDark, className = '', children }) {
  return <div className={`rounded-xl border ${useTh(isDark).card} ${className}`}>{children}</div>
}

export function PageTitle({ isDark, title, subtitle, children }) {
  const th = useTh(isDark)
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div>
        <h1 className={`text-lg font-semibold ${th.heading}`}>{title}</h1>
        {subtitle && <p className={`text-xs mt-0.5 ${th.muted}`}>{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  )
}

export function Button({ isDark, kind = 'secondary', className = '', ...props }) {
  const th = useTh(isDark)
  const look = kind === 'primary' ? th.primary : kind === 'danger' ? `border ${th.danger}` : `border ${th.button}`
  return <button type="button" {...props} className={`text-xs font-medium px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50 ${look} ${className}`} />
}

export function ErrorNote({ isDark, error, onRetry }) {
  const th = useTh(isDark)
  if (!error) return null
  return (
    <div role="alert" className={`rounded-lg border px-3 py-2 text-xs mb-3 ${isDark ? 'border-red-700/40 bg-red-900/20 text-red-300' : 'border-red-200 bg-red-50 text-red-700'}`}>
      {msg('UI_ALERTING_LOAD_ERROR')} {error.status ? msg('UI_COMMON_HTTP', { status: error.status }) : ''}
      {onRetry && <button type="button" onClick={onRetry} className={`ml-3 underline ${th.heading}`}>{msg('UI_INBOX_RETRY')}</button>}
    </div>
  )
}

export function Empty({ isDark, text }) {
  return <p className={`px-4 py-8 text-center text-xs ${useTh(isDark).muted}`}>{text}</p>
}

export function Field({ isDark, label, children }) {
  return (
    <label className="block text-[11px]">
      <span className={`block mb-1 font-medium ${useTh(isDark).muted}`}>{label}</span>
      {children}
    </label>
  )
}

export function when(iso) {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('en-IN', { hour12: false, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch { return String(iso) }
}

export function ago(iso) {
  if (!iso) return ''
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return msg('UI_APPSHELL_JUST_NOW')
  if (mins < 60) return msg('UI_APPSHELL_M_AGO', { mins })
  return msg('UI_APPSHELL_H_AGO', { hrs: Math.floor(mins / 60) })
}
