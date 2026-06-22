import { Link } from 'react-router-dom'
import { NavLink, useLocation } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'

const NAV_ITEMS = [
  { to: '/ej',               label: 'Command Center', end: true },
  { to: '/ej/incidents',     label: 'Incidents'                 },
  { to: '/ej/portal',        label: 'Manager Portal'            },
  { to: '/ej/bre',           label: 'BRE Policy'                },
  { to: '/ej/notifications', label: 'Notifications'             },
]

const ROUTE_LABELS = {
  '/ej':               ['EJ', 'Command Center'],
  '/ej/incidents':     ['EJ', 'Incident Management'],
  '/ej/portal':        ['EJ', 'Manager Portal'],
  '/ej/bre':           ['EJ', 'BRE Policy'],
  '/ej/notifications': ['EJ', 'Notifications'],
}

function useBreadcrumb(pathname) {
  const matched = Object.entries(ROUTE_LABELS)
    .filter(([key]) => pathname === key || pathname.startsWith(key + '/'))
    .sort((a, b) => b[0].length - a[0].length)[0]
  return matched ? matched[1] : ['EJ', '']
}

const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

export default function EJShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [section, page] = useBreadcrumb(location.pathname)

  return (
    <div
      className="flex flex-col h-screen bg-slate-50 text-slate-900 dark:text-white"
      style={isDark ? { background: darkGradient } : undefined}
    >
      {/* ── Topbar ──────────────────────────────────────── */}
      <header className="shrink-0 border-b bg-white border-slate-200 dark:bg-white/4 dark:backdrop-blur-md dark:border-white/8 flex items-center px-5" style={{ height: '52px' }}>

        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 shrink-0 group mr-4">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <span className="text-sm tracking-tight leading-none">
            <span className="font-bold">A</span>
            <span className="font-bold text-amber-500 dark:text-gold-400">+</span>
            <span className="font-bold">stra</span>
          </span>
        </Link>

        {/* ── Centered pill nav ─────────────────────────── */}
        <div className="flex-1 flex justify-center">
          <nav className="flex items-center bg-slate-100 border border-slate-200 rounded-full px-1.5 py-1 dark:bg-white/6 dark:border dark:border-white/10 dark:backdrop-blur-sm gap-0.5">
            {NAV_ITEMS.map(({ to, label, end }, idx) => (
              <div key={to} className="flex items-center">
                <NavLink
                  to={to} end={end}
                  className={({ isActive }) =>
                    `px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap ${
                      isActive
                        ? 'bg-slate-800 text-white shadow-sm dark:bg-white/15 dark:text-white dark:shadow-sm dark:ring-1 dark:ring-white/10'
                        : 'text-slate-500 hover:text-slate-900 hover:bg-white dark:text-slate-400 dark:hover:text-white dark:hover:bg-white/8'
                    }`
                  }
                >
                  {label}
                </NavLink>
                {idx < NAV_ITEMS.length - 1 && (
                  <div className="w-px h-4 mx-1 shrink-0 bg-slate-300/80 dark:bg-white/10" />
                )}
              </div>
            ))}
          </nav>
        </div>

        {/* ── Right: module tag + back link + toggle ── */}
        <div className="flex items-center gap-3 shrink-0 ml-4">
          <span className="hidden md:block text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">EJ Intelligence</span>
          <Link
            to="/"
            className="text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
          >
            ← Portal
          </Link>
          <button
            onClick={toggle}
            title={isDark ? 'Switch to light' : 'Switch to dark'}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 hover:bg-slate-100 text-slate-500 dark:hover:bg-white/8 dark:text-slate-400"
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* ── Breadcrumb bar ───────────────────────────────── */}
      {page && (
        <div className="shrink-0 border-b bg-white/80 border-slate-100 dark:bg-white/3 dark:border-white/6 dark:backdrop-blur-sm flex items-center px-6 gap-2" style={{ height: '44px' }}>
          <span className="text-[11px] text-slate-400">{section}</span>
          <span className="text-[11px] text-slate-400 opacity-40">›</span>
          <span className="text-[13px] font-semibold text-slate-700 dark:text-slate-100">{page}</span>
        </div>
      )}

      {/* ── Page content ─────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto bg-slate-50 dark:bg-black/15">
        {children}
      </div>
    </div>
  )
}
