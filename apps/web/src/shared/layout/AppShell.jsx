import { useState, useContext, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'
import { PageHeaderCtx } from './PageHeaderContext'

const FLAT_NAV = [
  { to: '/cts',               label: 'Inward Queue',   end: true },
  { to: '/cts/ops-dashboard', label: 'Ops Dashboard'  },
  { to: '/cts/pipeline',      label: 'Inward View'    },
  { to: '/cts/outward',       label: 'Outward'        },
  { to: '/cts/drawee',        label: 'Drawee / Outward' },
  { to: '/cts/settlement',    label: 'Settlement'     },
  { to: '/cts/batches',       label: 'Batches'        },
  { to: '/cts/vault',         label: 'Vault'          },
]

const NAV_GROUPS = [
  {
    label: 'Reports',
    items: [
      { to: '/cts/decisions',     label: 'Decisions Log'    },
      { to: '/cts/discrepancy',   label: 'Discrepancy'      },
      { to: '/cts/reconciliation',label: 'Reconciliation'   },
      { to: '/cts/analytics',     label: 'Analytics'        },
      { to: '/cts/compliance',    label: 'Compliance Cert'  },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/cts/sub-member',  label: 'Sub-Member'       },
      { to: '/cts/exceptions',  label: 'Exceptions'       },
      { to: '/cts/endorsement', label: 'Endorsement'      },
      { to: '/cts/iqa',         label: 'Image Quality'    },
      { to: '/cts/scanner',     label: 'Scanner SDK'      },
      { to: '/cts/rpc',         label: 'RPC Consolidation'},
    ],
  },
  {
    label: 'Commercial',
    items: [
      { to: '/cts/business-model', label: 'Business Model' },
    ],
  },
  {
    label: 'Admin',
    items: [
      { to: '/admin/users', label: 'User Management' },
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
  '/cts':               ['CTS', 'Inward Queue — Human Review'],
  '/cts/outward':       ['CTS', 'Outward'],
  '/cts/vault':         ['CTS', 'Vault Status'],
  '/cts/decisions':     ['Reports', 'Decisions Log'],
  '/cts/reconciliation':['Reports', 'Reconciliation'],
  '/cts/analytics':     ['Reports', 'Analytics'],
  '/cts/compliance':    ['Reports', 'Compliance Cert'],
  '/cts/sub-member':    ['Operations', 'Sub-Member Banks'],
  '/cts/exceptions':    ['Operations', 'Exceptions'],
  '/cts/endorsement':   ['Operations', 'Endorsement'],
  '/cts/iqa':           ['Operations', 'Image Quality Assessment'],
  '/cts/scanner':       ['Operations', 'Scanner SDK'],
  '/cts/rpc':           ['Operations', 'RPC Consolidation'],
  '/cts/business-model':  ['Commercial', 'Business Model — Cost & Revenue'],
  '/cts/pipeline':        ['CTS', 'Inward View — AI Pipeline'],
  '/cts/ops-dashboard':   ['CTS', 'Ops Dashboard'],
  '/cts/drawee':          ['CTS', 'Drawee & Outward Position'],
  '/cts/settlement':      ['CTS', 'Settlement Lifecycle'],
  '/admin/users':         ['Admin', 'User Management'],
  '/cts/config':          ['Admin', 'Config'],
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
  const closeTimer = useRef(null)

  const openNav = (label) => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOpenGroup(label)
  }
  const closeNav = () => {
    closeTimer.current = setTimeout(() => setOpenGroup(null), 150)
  }
  const [section, page] = useBreadcrumb(location.pathname)

  const darkGradient = 'linear-gradient(145deg, #020917 0%, #0e1654 38%, #060d2e 65%, #03061a 100%)'

  const groupHasActive = (items) => items.some(({ to }) => location.pathname.startsWith(to))

  return (
    <div
      className={`flex flex-col h-screen ${isDark ? 'text-white' : 'bg-slate-50 text-slate-900'}`}
      style={isDark ? { background: darkGradient } : undefined}
    >

      {/* ── Topbar ──────────────────────────────────────── */}
      <header className={`shrink-0 border-b flex items-center px-5 ${isDark ? 'bg-navy-950/95 backdrop-blur-md border-white/10' : 'bg-white border-slate-200'}`} style={{ height: '52px' }}>

        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 shrink-0 group mr-4">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <span className={`text-sm font-bold tracking-tight leading-none ${isDark ? 'text-white' : 'text-slate-900'}`}>stra</span>
        </Link>

        {/* ── Centered pill nav ─────────────────────────── */}
        <div className="flex-1 flex justify-center">
          <nav className={`flex items-center rounded-full px-1.5 py-1 gap-0.5 ${isDark ? 'bg-[#0e1654]/70 border border-white/20 backdrop-blur-sm' : 'bg-slate-100 border border-slate-200'}`}>

            {/* Flat items */}
            {FLAT_NAV.map(({ to, label, end }, idx) => (
              <div key={to} className="flex items-center">
                <NavLink
                  to={to} end={end}
                  className={({ isActive }) =>
                    `px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap ${isActive
                      ? (isDark ? 'bg-white/20 text-white shadow-sm ring-1 ring-white/20' : 'bg-slate-800 text-white shadow-sm')
                      : (isDark ? 'text-slate-200 hover:text-white hover:bg-white/15' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200')}`
                  }
                >
                  {label}
                </NavLink>
                <div className={`w-px h-4 mx-1 shrink-0 ${isDark ? 'bg-white/10' : 'bg-slate-300/80'}`} />
              </div>
            ))}

            {/* Group dropdowns */}
            {NAV_GROUPS.map((group, gIdx) => {
              const isGroupActive = groupHasActive(group.items)
              const isOpen = openGroup === group.label
              return (
                <NavGroup
                  key={group.label}
                  group={group}
                  isGroupActive={isGroupActive}
                  isOpen={isOpen}
                  isDark={isDark}
                  onOpen={() => openNav(group.label)}
                  onClose={closeNav}
                  onItemClick={() => setOpenGroup(null)}
                  location={location}
                  showDivider={gIdx < NAV_GROUPS.length - 1}
                />
              )
            })}
          </nav>
        </div>

        {/* ── Right: bank info + user + toggle ── */}
        <div className="flex items-center gap-4 shrink-0 ml-4">
          <div className="text-right hidden md:block">
            <div className={`text-[11px] font-medium leading-tight ${isDark ? 'text-white' : 'text-slate-700'}`}>Saraswat Co-op Bank</div>
            <div className={`text-[10px] leading-tight ${isDark ? 'text-slate-300' : 'text-slate-400'}`}>Zone: MUMBAI · Finacle</div>
          </div>

          {/* Profile avatar */}
          <div className="relative">
            <button
              className={`flex items-center gap-2 rounded-lg px-1.5 py-1 transition-all ${isDark ? 'hover:bg-white/8' : 'hover:bg-slate-100'}`}
              onClick={() => setProfileOpen((v) => !v)}
            >
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${isDark ? 'bg-gold-400/20 text-gold-400' : 'bg-amber-100 text-amber-700'}`}>R</div>
              <div className="hidden sm:block text-left">
                <div className={`text-[11px] leading-tight font-medium ${isDark ? 'text-white' : 'text-slate-700'}`}>Rahul S.</div>
                <div className={`text-[10px] leading-tight ${isDark ? 'text-slate-300' : 'text-slate-400'}`}>ops_reviewer</div>
              </div>
              <svg className="w-3 h-3 opacity-50 hidden sm:block text-slate-400" fill="none" viewBox="0 0 24 24"
                stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {profileOpen && (
              <div
                className={`absolute right-0 top-full mt-2 w-52 z-50 rounded-xl border py-2 shadow-2xl ${isDark ? 'bg-[#0e1654]/95 backdrop-blur-xl border-white/10 shadow-black/60' : 'bg-white border-slate-200 shadow-slate-400/30'}`}
                onMouseLeave={() => setProfileOpen(false)}
              >
                {PROFILE_MENU.map((item, i) =>
                  item.section ? (
                    <div key={i} className={`px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
                      {item.section}
                    </div>
                  ) : (
                    <Link
                      key={item.to} to={item.to}
                      className={`flex items-center gap-2.5 px-4 py-1.5 text-xs mx-1.5 my-0.5 transition-colors rounded-lg ${isDark ? 'text-slate-300 hover:text-white hover:bg-white/10' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'}`}
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
            className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all shrink-0 ${isDark ? 'hover:bg-white/10 text-slate-200' : 'hover:bg-slate-100 text-slate-500'}`}
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </header>

      {/* ── PageHeaderProvider wraps both the breadcrumb bar and content.       */}
      {/* ── Pages call usePageHeader() which sets state on the provider.        */}
      {/* ── PageHeaderBar reads from that same provider — re-renders on change. */}
      <PageHeaderBar page={page} section={section} isDark={isDark} />
      <div className={`flex-1 min-h-0 overflow-y-auto ${isDark ? 'bg-black/15' : 'bg-slate-50'}`}>
        {children}
      </div>
    </div>
  )
}

function NavGroup({ group, isGroupActive, isOpen, isDark, onOpen, onClose, onItemClick, location, showDivider }) {
  const btnRef = useRef(null)
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 })

  useEffect(() => {
    if (isOpen && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + 6, left: r.left + r.width / 2, width: Math.max(r.width, 190) })
    }
  }, [isOpen])

  const panelBg = isDark
    ? { background: 'rgba(14,22,84,0.97)', border: '1px solid rgba(255,255,255,0.12)', boxShadow: '0 20px 60px rgba(0,0,0,0.6)', backdropFilter: 'blur(20px)' }
    : { background: '#fff', border: '1px solid #e2e8f0', boxShadow: '0 20px 40px rgba(100,116,139,0.25)' }

  return (
    <div className="flex items-center">
      <div
        ref={btnRef}
        onMouseEnter={onOpen}
        onMouseLeave={onClose}
        style={{ position: 'relative' }}
      >
        <button
          className={`px-4 py-1.5 text-xs rounded-full transition-all whitespace-nowrap flex items-center gap-1.5 ${
            isGroupActive
              ? (isDark ? 'bg-white/20 text-white shadow-sm ring-1 ring-white/20' : 'bg-slate-800 text-white shadow-sm')
              : (isDark ? 'text-slate-200 hover:text-white hover:bg-white/15' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-200')
          }`}
        >
          {group.label}
          <svg className="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {isOpen && createPortal(
        <div
          style={{ position: 'fixed', top: pos.top, left: pos.left, transform: 'translateX(-50%)', zIndex: 9999, minWidth: '200px', paddingTop: '2px' }}
          onMouseEnter={onOpen}
          onMouseLeave={onClose}
        >
          <div style={{ borderRadius: '12px', padding: '6px 0', ...panelBg }}>
            {group.items.map(({ to, label }) => {
              const isActive = location.pathname.startsWith(to)
              return (
                <NavLink
                  key={to} to={to}
                  style={isActive
                    ? { display: 'flex', alignItems: 'center', padding: '8px 16px', fontSize: '12px', margin: '2px 6px', borderRadius: '8px', background: isDark ? 'rgba(255,255,255,0.15)' : '#1e293b', color: '#fff', fontWeight: 500, textDecoration: 'none' }
                    : { display: 'flex', alignItems: 'center', padding: '8px 16px', fontSize: '12px', margin: '2px 6px', borderRadius: '8px', color: isDark ? 'rgb(203,213,225)' : '#475569', textDecoration: 'none' }
                  }
                  onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = isDark ? 'rgba(255,255,255,0.1)' : '#f1f5f9'; e.currentTarget.style.color = isDark ? '#fff' : '#0f172a' }}
                  onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = ''; e.currentTarget.style.color = isDark ? 'rgb(203,213,225)' : '#475569' }}
                  onClick={onItemClick}
                >
                  {label}
                </NavLink>
              )
            })}
          </div>
        </div>,
        document.body
      )}

      {showDivider && <div className={`w-px h-4 mx-1 shrink-0 ${isDark ? 'bg-white/10' : 'bg-slate-300/80'}`} />}
    </div>
  )
}

function PageHeaderBar({ page, section, isDark }) {
  const { subtitle, actions } = useContext(PageHeaderCtx)
  if (!page) return null

  return (
    <div
      className="shrink-0 border-b flex items-center px-6 gap-2"
      style={{
        height: '44px',
        background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.85)',
        borderColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgb(241 245 249)',
        backdropFilter: 'blur(8px)',
      }}
    >
      <span className={`text-[11px] ${isDark ? 'text-slate-400' : 'text-slate-400'}`}>{section}</span>
      <span className={`text-[11px] opacity-40 ${isDark ? 'text-slate-400' : 'text-slate-400'}`}>›</span>
      <span className={`text-[13px] font-semibold ${isDark ? 'text-white' : 'text-slate-700'}`}>{page}</span>
      <div className="ml-auto flex items-center gap-4">
        {subtitle && <span className={`text-[11px] hidden sm:block ${isDark ? 'text-slate-400' : 'text-slate-400'}`}>{subtitle}</span>}
        {actions}
      </div>
    </div>
  )
}
