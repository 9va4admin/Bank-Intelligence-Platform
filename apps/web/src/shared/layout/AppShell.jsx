import { NavLink } from 'react-router-dom'
import { useTheme } from '../theme/ThemeContext'

const NAV = [
  { to: '/cts',           icon: '◈', label: 'CTS Queue'     },
  { to: '/cts/vault',     icon: '🔑', label: 'Vault Status'  },
  { to: '/cts/decisions', icon: '📋', label: 'Decisions Log' },
  { to: '/cts/analytics', icon: '📊', label: 'Analytics'     },
  { to: '/cts/config',    icon: '⚙',  label: 'Config'        },
]

export default function AppShell({ children }) {
  const { isDark, toggle } = useTheme()

  const shell = isDark
    ? 'bg-navy-950 text-white'
    : 'bg-slate-100 text-slate-900'
  const sidebar = isDark
    ? 'bg-navy-900/50 border-white/8'
    : 'bg-white border-slate-200'
  const divider = isDark ? 'border-white/8' : 'border-slate-200'
  const subtext = isDark ? 'text-slate-600' : 'text-slate-400'
  const bankName = isDark ? 'text-slate-300' : 'text-slate-700'
  const navActive = isDark
    ? 'bg-gold-400/10 text-gold-400 font-medium'
    : 'bg-amber-50 text-amber-700 font-medium'
  const navIdle = isDark
    ? 'text-slate-500 hover:text-slate-300 hover:bg-white/4'
    : 'text-slate-400 hover:text-slate-700 hover:bg-slate-100'
  const userBg = isDark ? 'bg-gold-400/20 text-gold-400' : 'bg-amber-100 text-amber-700'
  const userName = isDark ? 'text-slate-300' : 'text-slate-700'
  const main = isDark ? 'bg-navy-950' : 'bg-slate-50'

  return (
    <div className={`flex h-screen overflow-hidden ${shell}`}>
      {/* Sidebar */}
      <aside className={`w-56 shrink-0 border-r flex flex-col ${sidebar}`}>
        {/* Logo */}
        <div className={`px-4 py-5 border-b ${divider}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="relative w-7 h-7">
                <div className="absolute inset-0 rounded-md bg-gold-400/20" />
                <div className="absolute inset-[2px] rounded-md bg-gold-400 flex items-center justify-center">
                  <span className="text-navy-950 font-mono font-bold text-xs">A</span>
                </div>
              </div>
              <div>
                <div className="text-sm font-bold">ASTRA</div>
                <div className={`text-[10px] ${subtext}`}>Ops Workstation</div>
              </div>
            </div>
            {/* Theme toggle */}
            <button
              onClick={toggle}
              title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              className={`w-7 h-7 rounded-lg flex items-center justify-center text-sm transition-all ${
                isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500'
              }`}
            >
              {isDark ? '☀' : '🌙'}
            </button>
          </div>
        </div>

        {/* Bank context */}
        <div className={`px-4 py-3 border-b ${divider}`}>
          <div className={`text-[10px] ${subtext} uppercase tracking-wide`}>Bank</div>
          <div className={`text-xs ${bankName} font-medium mt-0.5`}>Saraswat Co-op Bank</div>
          <div className={`text-[10px] ${subtext} mt-0.5`}>Zone: MUMBAI · Finacle</div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 space-y-0.5">
          {NAV.map(({ to, icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/cts'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all ${
                  isActive ? navActive : navIdle
                }`
              }
            >
              <span className="text-base w-5 text-center">{icon}</span>
              <span className="flex-1">{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        <div className={`px-4 py-4 border-t ${divider}`}>
          <div className="flex items-center gap-2">
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${userBg}`}>
              R
            </div>
            <div>
              <div className={`text-xs ${userName}`}>Rahul S.</div>
              <div className={`text-[10px] ${subtext}`}>ops_reviewer</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className={`flex-1 flex flex-col min-w-0 ${main}`}>
        {children}
      </div>
    </div>
  )
}
