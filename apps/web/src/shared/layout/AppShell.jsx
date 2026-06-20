import { useState, useContext } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { PageHeaderCtx } from './PageHeaderContext'

const FLAT_NAV = [
  { to: '/cts',         label: 'Inward',  end: true },
  { to: '/cts/outward', label: 'Outward' },
  { to: '/cts/vault',   label: 'Vault'   },
]

const NAV_GROUPS = [
  {
    label: 'Reports',
    items: [
      { to: '/cts/decisions',      label: 'Decisions Log'    },
      { to: '/cts/reconciliation', label: 'Reconciliation'   },
      { to: '/cts/analytics',      label: 'Analytics'        },
      { to: '/cts/compliance',     label: 'Compliance Cert'  },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/cts/sub-member',  label: 'Sub-Member'       },
      { to: '/cts/exceptions',  label: 'Exceptions'       },
      { to: '/cts/endorsement', label: 'Endorsement'      },
      { to: '/cts/scanner',     label: 'Scanner SDK'      },
      { to: '/cts/rpc',         label: 'RPC Consolidation'},
    ],
  },
]

const PROFILE_MENU = [
  { section: 'Master Config' },
  { to: '/cts/config/sub-member-banks', label: 'Sub-Member Banks',    icon: '🏦' },
  { to: '/cts/config/micr-prefixes',    label: 'MICR Prefix Table',   icon: '🔢' },
  { to: '/cts/config/thresholds',       label: 'Thresholds & Rules',  icon: '⚙️' },
  { to: '/cts/config/ngch-routing',     label: 'NGCH Routing',        icon: '🗺' },
  { section: 'Account' },
  { to: '/profile',                     label: 'My Profile',          icon: '👤' },
  { to: '/logout',                      label: 'Sign Out',            icon: '→'  },
]

const ROUTE_LABELS = {
  '/cts':               ['CTS', 'Inward Queue'],
  '/cts/outward':       ['CTS', 'Outward'],
  '/cts/vault':         ['CTS', 'Vault Status'],
  '/cts/decisions':     ['Reports', 'Decisions Log'],
  '/cts/reconciliation':['Reports', 'Reconciliation'],
  '/cts/analytics':     ['Reports', 'Analytics'],
  '/cts/compliance':    ['Reports', 'Compliance Cert'],
  '/cts/sub-member':    ['Operations', 'Sub-Member Banks'],
  '/cts/exceptions':    ['Operations', 'Exceptions'],
  '/cts/endorsement':   ['Operations', 'Endorsement'],
  '/cts/scanner':       ['Operations', 'Scanner SDK'],
  '/cts/rpc':           ['Operations', 'RPC Consolidation'],
  '/cts/config':        ['Admin', 'Config'],
  '/cts/config/sub-member-banks': ['Admin · Config', 'Sub-Member Banks'],
  '/cts/config/micr-prefixes':    ['Admin · Config', 'MICR Prefix Table'],
  '/cts/config/thresholds':       ['Admin · Config', 'Thresholds & Rules'],
  '/cts/config/ngch-routing':     ['Admin · Config', 'NGCH Routing'],
}

function useBreadcrumb(pathname) {
  const matched = Object.entries(ROUTE_LABELS)
    .filter(([key]) => pathname === key || pathname.startsWith(key + '/'))
    .sort((a, b) => b[0].length - a[0].length)[0]
  return matched ? matched[1] : ['CTS', '']
}

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()
  const location = useLocation()
  const [openGroup, setOpenGroup] = useState(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const [section, page] = useBreadcrumb(location.pathname)

  const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

  const groupHasActive = (items) => items.some(({ to }) => location.pathname.startsWith(to))

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

            {/* Flat items */}
            {FLAT_NAV.map(({ to, label, end }, idx) => (
              <div key={to} className="flex items-center">
                <NavLink
                  to={to} end={end}
                  className={({ isActive }) =>
                    `px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap ${isActive ? 'bg-slate-800 text-white shadow-sm dark:bg-white/15 dark:text-white dark:shadow-sm dark:ring-1 dark:ring-white/10' : 'text-slate-500 hover:text-slate-900 hover:bg-white dark:text-slate-400 dark:hover:text-white dark:hover:bg-white/8'}`
                  }
                >
                  {label}
                </NavLink>
                <div className="w-px h-4 mx-1 shrink-0 bg-slate-300/80 dark:bg-white/10" />
              </div>
            ))}

            {/* Group dropdowns */}
            {NAV_GROUPS.map((group, gIdx) => {
              const isGroupActive = groupHasActive(group.items)
              const isOpen = openGroup === group.label
              return (
                <div key={group.label} className="flex items-center">
                  <div
                    className="relative"
                    onMouseEnter={() => setOpenGroup(group.label)}
                    onMouseLeave={() => setOpenGroup(null)}
                  >
                    <button
                      className={`px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap flex items-center gap-1.5 ${
                        isGroupActive
                          ? 'bg-slate-800 text-white shadow-sm dark:bg-white/15 dark:text-white dark:shadow-sm dark:ring-1 dark:ring-white/10'
                          : 'text-slate-500 hover:text-slate-900 hover:bg-white dark:text-slate-400 dark:hover:text-white dark:hover:bg-white/8'
                      }`}
                    >
                      {group.label}
                      <svg className="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24"
                        stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>

                    {isOpen && (
                      <div
                        className="absolute top-full left-1/2 -translate-x-1/2 z-50"
                        style={{ paddingTop: '6px', minWidth: '190px' }}
                      >
                        <div className="rounded-xl border py-2 bg-white border-slate-200 shadow-2xl shadow-slate-400/30 dark:bg-[#0e1654]/95 dark:backdrop-blur-xl dark:border-white/10 dark:shadow-2xl dark:shadow-black/60">
                          {group.items.map(({ to, label }) => {
                            const isActive = location.pathname.startsWith(to)
                            return (
                              <NavLink
                                key={to} to={to}
                                className={() =>
                                  `flex items-center px-4 py-2 text-xs transition-colors mx-1.5 my-0.5 rounded-lg ${
                                    isActive
                                      ? 'bg-slate-800 text-white font-medium dark:bg-white/15 dark:text-white dark:font-medium'
                                      : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-slate-300 dark:hover:text-white dark:hover:bg-white/10'
                                  }`
                                }
                                onClick={() => setOpenGroup(null)}
                              >
                                {label}
                              </NavLink>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>

                  {gIdx < NAV_GROUPS.length - 1 && (
                    <div className="w-px h-4 mx-1 shrink-0 bg-slate-300/80 dark:bg-white/10" />
                  )}
                </div>
              )
            })}
          </nav>
        </div>

        {/* ── Right: bank info + user + toggle ── */}
        <div className="flex items-center gap-4 shrink-0 ml-4">
          <div className="text-right hidden md:block">
            <div className="text-[11px] font-medium leading-tight text-slate-700 dark:text-slate-200">Saraswat Co-op Bank</div>
            <div className="text-[10px] leading-tight text-slate-400">Zone: MUMBAI · Finacle</div>
          </div>

          {/* Profile avatar */}
          <div className="relative">
            <button
              className="flex items-center gap-2 rounded-lg px-1.5 py-1 transition-all hover:bg-slate-100 dark:hover:bg-white/8"
              onClick={() => setProfileOpen((v) => !v)}
            >
              <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 bg-amber-100 text-amber-700 dark:bg-gold-400/20 dark:text-gold-400">R</div>
              <div className="hidden sm:block text-left">
                <div className="text-[11px] leading-tight font-medium text-slate-700 dark:text-slate-200">Rahul S.</div>
                <div className="text-[10px] leading-tight text-slate-400">ops_reviewer</div>
              </div>
              <svg className="w-3 h-3 opacity-50 hidden sm:block text-slate-400" fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {profileOpen && (
              <div
                className="absolute right-0 top-full mt-2 w-52 z-50 rounded-xl border py-2 bg-white border-slate-200 shadow-2xl shadow-slate-400/30 dark:bg-[#0e1654]/95 dark:backdrop-blur-xl dark:border-white/10 dark:shadow-2xl dark:shadow-black/60"
                onMouseLeave={() => setProfileOpen(false)}
              >
                {PROFILE_MENU.map((item, i) =>
                  item.section ? (
                    <div key={i} className="px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
                      {item.section}
                    </div>
                  ) : (
                    <Link
                      key={item.to} to={item.to}
                      className="flex items-center gap-2.5 px-4 py-1.5 text-xs mx-1.5 my-0.5 transition-colors text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg dark:text-slate-300 dark:hover:text-white dark:hover:bg-white/10"
                      onClick={() => setProfileOpen(false)}
                    >
                      <span className="w-4 text-center opacity-70">{item.icon}</span>
                      {item.label}
                    </Link>
                  )
                )}
              </div>
            )}
          </div>

          <button
            onClick={toggle}
            title={isDark ? 'Switch to light' : 'Switch to dark'}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 hover:bg-slate-100 text-slate-500 dark:hover:bg-white/8 dark:text-slate-400"
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* ── PageHeaderProvider wraps both the breadcrumb bar and content.       */}
      {/* ── Pages call usePageHeader() which sets state on the provider.        */}
      {/* ── PageHeaderBar reads from that same provider — re-renders on change. */}
      <PageHeaderBar page={page} section={section} />
      <div className="flex-1 min-h-0 overflow-y-auto bg-slate-50 dark:bg-black/15">
        {children}
      </div>
    </div>
  )
}

function PageHeaderBar({ page, section }) {
  const { subtitle, actions } = useContext(PageHeaderCtx)
  if (!page) return null

  return (
    <div className="shrink-0 border-b bg-white/80 border-slate-100 dark:bg-white/3 dark:border-white/6 dark:backdrop-blur-sm flex items-center px-6 gap-2" style={{ height: '44px' }}>
      <span className="text-[11px] text-slate-400">{section}</span>
      <span className="text-[11px] text-slate-400 opacity-40">›</span>
      <span className="text-[13px] font-semibold text-slate-700 dark:text-slate-100">{page}</span>
      <div className="ml-auto flex items-center gap-4">
        {subtitle && <span className="text-[11px] text-slate-400 hidden sm:block">{subtitle}</span>}
        {actions}
      </div>
    </div>
  )
}
