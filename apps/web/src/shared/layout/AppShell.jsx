import { useState, useRef } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'

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

// Profile menu items (master config + account)
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

// Map routes → readable breadcrumb label
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

  // ── Theme tokens ────────────────────────────────────────
  // ── Gradient dark shell ─────────────────────────────────
  // Rich indigo-navy diagonal — breaks the flat pitch-black feel
  const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

  const shell    = isDark ? 'text-white'                     : 'bg-slate-50 text-slate-900'
  const shellStyle = isDark ? { background: darkGradient }  : undefined

  // Topbar: glass over gradient
  const topbar   = isDark
    ? 'bg-white/4 backdrop-blur-md border-white/8'
    : 'bg-white border-slate-200'

  const subtext  = isDark ? 'text-slate-400'                : 'text-slate-400'
  const userBg   = isDark ? 'bg-gold-400/20 text-gold-400'  : 'bg-amber-100 text-amber-700'
  const userName = isDark ? 'text-slate-200'                : 'text-slate-700'

  // Content area: subtle darker overlay so cards pop
  const main     = isDark ? 'bg-black/15'                   : 'bg-slate-50'

  // Pill nav — glass effect over gradient
  const navPill  = isDark
    ? 'bg-white/6 border border-white/10 rounded-full px-1.5 py-1 backdrop-blur-sm'
    : 'bg-slate-100 border border-slate-200 rounded-full px-1.5 py-1'

  // Active capsule
  const activeCapsule = isDark
    ? 'bg-white/15 text-white shadow-sm ring-1 ring-white/10'
    : 'bg-slate-800 text-white shadow-sm'

  const idleItem = isDark
    ? 'text-slate-400 hover:text-white hover:bg-white/8'
    : 'text-slate-500 hover:text-slate-900 hover:bg-white'

  const divider = isDark ? 'bg-white/10' : 'bg-slate-300/80'

  // Dropdown panel — glass card
  const dropdownBg = isDark
    ? 'bg-[#0e1654]/90 backdrop-blur-xl border-white/10 shadow-2xl shadow-black/60'
    : 'bg-white border-slate-200 shadow-2xl shadow-slate-400/30'

  const groupHasActive = (items) =>
    items.some(({ to }) => location.pathname.startsWith(to))

  // Breadcrumb strip colours
  const breadcrumbBg    = isDark ? 'bg-white/3 border-white/6 backdrop-blur-sm' : 'bg-white/80 border-slate-100'
  const breadcrumbMuted = isDark ? 'text-slate-400' : 'text-slate-400'
  const breadcrumbPage  = isDark ? 'text-slate-100' : 'text-slate-700'

  // Profile dropdown
  const profileBg = isDark
    ? 'bg-[#0e1654]/95 backdrop-blur-xl border-white/10 shadow-2xl shadow-black/60'
    : 'bg-white border-slate-200 shadow-2xl shadow-slate-400/30'
  const profileItem = isDark
    ? 'text-slate-300 hover:text-white hover:bg-white/8 rounded-lg'
    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg'
  const profileSection = isDark ? 'text-slate-500' : 'text-slate-400'

  return (
    <div className={`flex flex-col h-screen overflow-hidden ${shell}`} style={shellStyle}>

      {/* ── Topbar ──────────────────────────────────────── */}
      <header
        className={`shrink-0 border-b ${topbar} flex items-center px-5`}
        style={{ height: '52px' }}
      >
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
            <span className={`font-bold ${isDark ? 'text-gold-400' : 'text-amber-500'}`}>+</span>
            <span className="font-bold">stra</span>
          </span>
        </Link>

        {/* ── Centered pill nav ─────────────────────────── */}
        <div className="flex-1 flex justify-center">
          <nav className={`flex items-center ${navPill} gap-0.5`}>

            {/* Flat items */}
            {FLAT_NAV.map(({ to, label, end }, idx) => (
              <div key={to} className="flex items-center">
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap ${
                      isActive ? activeCapsule : idleItem
                    }`
                  }
                >
                  {label}
                </NavLink>
                <div className={`w-px h-4 mx-1 shrink-0 ${divider}`} />
              </div>
            ))}

            {/* Group dropdowns */}
            {NAV_GROUPS.map((group, gIdx) => {
              const isGroupActive = groupHasActive(group.items)
              return (
                <div key={group.label} className="flex items-center">
                  {/* Wrapper covers button + dropdown so hover doesn't break */}
                  <div
                    className="relative"
                    onMouseEnter={() => setOpenGroup(group.label)}
                    onMouseLeave={() => setOpenGroup(null)}
                  >
                    <button
                      className={`px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap flex items-center gap-1.5 ${
                        isGroupActive ? activeCapsule : idleItem
                      }`}
                    >
                      {group.label}
                      <svg className="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24"
                        stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>

                    {openGroup === group.label && (
                      /* -mt-1 + pt-3 bridges the gap so cursor moving down doesn't close it */
                      <div className={`absolute top-full left-1/2 -translate-x-1/2 -mt-1 pt-2 min-w-[190px] z-50`}>
                        <div className={`rounded-xl border py-2 ${dropdownBg}`}>
                          {group.items.map(({ to, label }) => {
                            const isActive = location.pathname.startsWith(to)
                            return (
                              <NavLink
                                key={to}
                                to={to}
                                className={() =>
                                  `flex items-center px-4 py-2 text-xs transition-colors mx-1.5 my-0.5 rounded-lg ${
                                    isActive
                                      ? (isDark ? 'bg-slate-700 text-white font-medium' : 'bg-slate-800 text-white font-medium')
                                      : (isDark ? 'text-slate-300 hover:text-white hover:bg-white/8' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100')
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
                    <div className={`w-px h-4 mx-1 shrink-0 ${divider}`} />
                  )}
                </div>
              )
            })}
          </nav>
        </div>

        {/* ── Right: bank info + user (with profile menu) + toggle ── */}
        <div className="flex items-center gap-4 shrink-0 ml-4">
          <div className="text-right hidden md:block">
            <div className={`text-[11px] font-medium leading-tight ${userName}`}>Saraswat Co-op Bank</div>
            <div className={`text-[10px] leading-tight ${subtext}`}>Zone: MUMBAI · Finacle</div>
          </div>

          {/* Profile avatar — click to open config menu */}
          <div className="relative">
            <button
              className={`flex items-center gap-2 rounded-lg px-1.5 py-1 transition-all ${
                isDark ? 'hover:bg-white/8' : 'hover:bg-slate-100'
              }`}
              onClick={() => setProfileOpen((v) => !v)}
            >
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${userBg}`}>R</div>
              <div className="hidden sm:block text-left">
                <div className={`text-[11px] leading-tight font-medium ${userName}`}>Rahul S.</div>
                <div className={`text-[10px] leading-tight ${subtext}`}>ops_reviewer</div>
              </div>
              <svg className={`w-3 h-3 opacity-50 hidden sm:block ${subtext}`} fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {profileOpen && (
              <div
                className={`absolute right-0 top-full mt-2 w-52 z-50 rounded-xl border py-2 ${profileBg}`}
                onMouseLeave={() => setProfileOpen(false)}
              >
                {PROFILE_MENU.map((item, i) =>
                  item.section ? (
                    <div key={i} className={`px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest ${profileSection}`}>
                      {item.section}
                    </div>
                  ) : (
                    <Link
                      key={item.to}
                      to={item.to}
                      className={`flex items-center gap-2.5 px-4 py-1.5 text-xs mx-1.5 my-0.5 transition-colors ${profileItem}`}
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
            className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 ${
              isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500'
            }`}
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* ── Breadcrumb strip ────────────────────────────── */}
      {page && (
        <div className={`shrink-0 border-b ${breadcrumbBg} flex items-center px-6 gap-1.5`}
          style={{ height: '30px' }}>
          <span className={`text-[11px] ${breadcrumbMuted}`}>{section}</span>
          <span className={`text-[11px] ${breadcrumbMuted} opacity-50`}>›</span>
          <span className={`text-[11px] font-medium ${breadcrumbPage}`}>{page}</span>
        </div>
      )}

      {/* ── Main content ────────────────────────────────── */}
      <div className={`flex-1 min-h-0 overflow-hidden ${main}`}>
        {children}
      </div>
    </div>
  )
}
