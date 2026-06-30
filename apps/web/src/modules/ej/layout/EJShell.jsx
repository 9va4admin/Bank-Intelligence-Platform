import { useState } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'

const NAV_SECTIONS = [
  {
    label: 'Operations',
    items: [
      { to: '/ej',               label: 'Command Center', end: true },
      { to: '/ej/incidents',     label: 'Incidents'                 },
      { to: '/ej/fleet',         label: 'ATM Fleet Map'             },
      { to: '/ej/disputes',      label: 'Dispute Console'           },
    ],
  },
  {
    label: 'Management',
    items: [
      { to: '/ej/portal',        label: 'Manager Portal'  },
      { to: '/ej/bre',           label: 'BRE Policy'      },
      { to: '/ej/notifications', label: 'Notifications'   },
    ],
  },
  {
    label: 'Admin',
    items: [
      { to: '/ej/schedules', label: 'Schedules' },
    ],
  },
]

const ROUTE_LABELS = {
  '/ej':               ['EJ', 'Command Center'],
  '/ej/incidents':     ['EJ', 'Incident Management'],
  '/ej/fleet':         ['EJ', 'ATM Fleet Map'],
  '/ej/disputes':      ['EJ', 'Dispute Console'],
  '/ej/portal':        ['Management', 'Manager Portal'],
  '/ej/bre':           ['Management', 'BRE Policy Manager'],
  '/ej/notifications': ['Management', 'Notification Center'],
  '/ej/schedules':     ['Admin', 'Temporal Schedules'],
}

function useBreadcrumb(pathname) {
  const matched = Object.entries(ROUTE_LABELS)
    .filter(([key]) => pathname === key || pathname.startsWith(key + '/'))
    .sort((a, b) => b[0].length - a[0].length)[0]
  return matched ? matched[1] : ['EJ', '']
}

function ChevronIcon({ style }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3 h-3 shrink-0" style={style}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 4l4 4-4 4" />
    </svg>
  )
}

const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

export default function EJShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [expandedSections, setExpandedSections] = useState(() => {
    const set = new Set()
    NAV_SECTIONS.forEach((sec) => {
      if (sec.items.some(({ to }) => location.pathname === to || location.pathname.startsWith(to + '/'))) {
        set.add(sec.label)
      }
    })
    if (set.size === 0) set.add('Operations')
    return set
  })

  const [section, page] = useBreadcrumb(location.pathname)

  const toggleSection = (label) => {
    setExpandedSections((prev) => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  const th = {
    shell:   isDark ? 'text-white' : 'bg-slate-100 text-slate-900',
    sidebar: isDark ? 'bg-[#040d2a] border-white/8' : 'bg-white border-slate-200',
    topbar:  isDark ? 'bg-navy-950/95 backdrop-blur-md border-white/10' : 'bg-white border-slate-200',
    content: isDark ? 'bg-black/15' : 'bg-slate-50',
  }

  return (
    <div
      className={`flex h-screen overflow-hidden ${th.shell}`}
      style={isDark ? { background: darkGradient } : undefined}
    >
      {/* ── Left Sidebar ─────────────────────────────────────────────── */}
      <aside
        className={`shrink-0 flex flex-col border-r transition-all duration-200 ${th.sidebar}`}
        style={{ width: collapsed ? '52px' : '192px' }}
      >
        {/* Logo row */}
        <div className={`flex items-center h-[52px] px-3 border-b shrink-0 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
          <Link to="/" className="flex items-center gap-2 group min-w-0">
            <div className="relative w-6 h-6 shrink-0">
              <div className="absolute inset-0 rounded" style={{ background: 'rgba(212,175,55,0.2)' }} />
              <div className="absolute inset-[2px] rounded flex items-center justify-center" style={{ background: '#d4af37' }}>
                <span className="font-mono font-bold text-[10px]" style={{ color: '#020817' }}>A</span>
              </div>
            </div>
            {!collapsed && (
              <span className={`text-sm font-bold tracking-tight leading-none ${isDark ? 'text-white' : 'text-slate-900'}`}>stra</span>
            )}
          </Link>
          {!collapsed && (
            <button
              onClick={() => setCollapsed(true)}
              className={`ml-auto p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
              title="Collapse sidebar"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 4L6 8l4 4" />
              </svg>
            </button>
          )}
          {collapsed && (
            <button
              onClick={() => setCollapsed(false)}
              className={`w-full flex justify-center p-1 rounded-md opacity-40 hover:opacity-100 transition-opacity ${isDark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
              title="Expand sidebar"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 4l4 4-4 4" />
              </svg>
            </button>
          )}
        </div>

        {/* Module label strip */}
        {!collapsed && (
          <div className={`px-3 py-2 border-b ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            <span className="text-[10px] font-semibold uppercase tracking-widest text-cyan-500">EJ Intelligence</span>
          </div>
        )}
        {collapsed && (
          <div className={`flex justify-center py-2 border-b ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            <span className="text-[9px] font-bold text-cyan-500">EJ</span>
          </div>
        )}

        {/* Nav sections */}
        <nav className="flex-1 overflow-y-auto overflow-x-hidden py-2">
          {collapsed ? (
            <div className="flex flex-col items-center gap-1 px-1.5">
              {NAV_SECTIONS.flatMap((sec) => sec.items).map(({ to, label, end }) => {
                const isActive = end ? location.pathname === to : location.pathname === to || location.pathname.startsWith(to + '/')
                return (
                  <NavLink
                    key={to} to={to} end={end} title={label}
                    className={`w-8 h-8 flex items-center justify-center rounded-lg text-[10px] font-bold transition-all ${
                      isActive
                        ? 'bg-cyan-600/30 text-cyan-300'
                        : (isDark ? 'text-slate-500 hover:text-white hover:bg-white/10' : 'text-slate-400 hover:text-slate-900 hover:bg-slate-100')
                    }`}
                  >
                    {label.charAt(0)}
                  </NavLink>
                )
              })}
            </div>
          ) : (
            NAV_SECTIONS.map((sec) => {
              const expanded = expandedSections.has(sec.label)
              const hasActive = sec.items.some(({ to }) => location.pathname === to || location.pathname.startsWith(to + '/'))
              return (
                <div key={sec.label} className="mb-1">
                  <button
                    onClick={() => toggleSection(sec.label)}
                    className={`w-full flex items-center gap-1.5 px-3 py-1 text-[10px] font-medium uppercase tracking-wider transition-all ${
                      hasActive
                        ? (isDark ? 'text-slate-300' : 'text-slate-600')
                        : (isDark ? 'text-slate-600 hover:text-slate-400' : 'text-slate-400 hover:text-slate-600')
                    }`}
                  >
                    <ChevronIcon style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s' }} />
                    {sec.label}
                  </button>
                  {expanded && (
                    <ul className="pb-1">
                      {sec.items.map(({ to, label, end }) => {
                        const isActive = end ? location.pathname === to : location.pathname === to || location.pathname.startsWith(to + '/')
                        return (
                          <li key={to}>
                            <NavLink
                              to={to} end={end}
                              className={`flex items-center gap-2 pl-6 pr-3 py-1.5 text-xs transition-all rounded-lg mx-1.5 my-0.5 ${
                                isActive
                                  ? 'bg-cyan-600/20 text-cyan-300 font-medium'
                                  : (isDark ? 'text-slate-400 hover:text-white hover:bg-white/8' : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100')
                              }`}
                            >
                              {isActive && <span className="w-1 h-1 rounded-full bg-cyan-400 shrink-0" />}
                              <span className={isActive ? '' : 'pl-3'}>{label}</span>
                            </NavLink>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              )
            })
          )}
        </nav>

        {/* Bottom: back to CTS */}
        <div className={`shrink-0 border-t px-2 py-2 ${isDark ? 'border-white/8' : 'border-slate-200'}`}>
          <Link
            to="/cts"
            title="CTS Workstation"
            className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-all ${isDark ? 'text-slate-500 hover:text-white hover:bg-white/8' : 'text-slate-400 hover:text-slate-900 hover:bg-slate-100'}`}
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 shrink-0">
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 12L6 8l4-4" />
            </svg>
            {!collapsed && <span>CTS Workstation</span>}
          </Link>
        </div>
      </aside>

      {/* ── Main area ───────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* Topbar */}
        <header className={`shrink-0 border-b flex items-center px-5 gap-4 ${th.topbar}`} style={{ height: '52px' }}>
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            <span className={`text-[11px] shrink-0 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{section}</span>
            <span className="text-[11px] opacity-30 shrink-0 text-slate-400">›</span>
            <span className={`text-[13px] font-semibold truncate ${isDark ? 'text-white' : 'text-slate-800'}`}>{page}</span>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <span className={`hidden lg:block text-[11px] font-medium ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>EJ Intelligence</span>
            <button
              onClick={toggle}
              title={isDark ? 'Switch to light' : 'Switch to dark'}
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 ${isDark ? 'hover:bg-white/10 text-slate-200' : 'hover:bg-slate-100 text-slate-500'}`}
            >
              {isDark ? '☀' : '🌙'}
            </button>
          </div>
        </header>

        {/* Content */}
        <div className={`flex-1 min-h-0 overflow-y-auto ${th.content}`}>
          {children}
        </div>
      </div>
    </div>
  )
}
