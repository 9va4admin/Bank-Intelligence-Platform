import { NavLink } from 'react-router-dom'

const NAV = [
  { to: '/cts',           icon: '◈', label: 'CTS Queue',     badge: null },
  { to: '/cts/vault',     icon: '🔑', label: 'Vault Status',  badge: null },
  { to: '/cts/decisions', icon: '📋', label: 'Decisions Log', badge: null },
  { to: '/cts/analytics', icon: '📊', label: 'Analytics',     badge: null },
  { to: '/cts/config',    icon: '⚙',  label: 'Config',        badge: null },
]

export default function AppShell({ children }) {
  return (
    <div className="flex h-screen bg-navy-950 text-white overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r border-white/8 flex flex-col bg-navy-900/50">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-white/8">
          <div className="flex items-center gap-2.5">
            <div className="relative w-7 h-7">
              <div className="absolute inset-0 rounded-md bg-gold-400/20" />
              <div className="absolute inset-[2px] rounded-md bg-gold-400 flex items-center justify-center">
                <span className="text-navy-950 font-mono font-bold text-xs">A</span>
              </div>
            </div>
            <div>
              <div className="text-sm font-bold text-white">ASTRA</div>
              <div className="text-[10px] text-slate-600">Ops Workstation</div>
            </div>
          </div>
        </div>

        {/* Bank context */}
        <div className="px-4 py-3 border-b border-white/5">
          <div className="text-[10px] text-slate-600 uppercase tracking-wide">Bank</div>
          <div className="text-xs text-slate-300 font-medium mt-0.5">Saraswat Co-op Bank</div>
          <div className="text-[10px] text-slate-600 mt-0.5">Zone: MUMBAI · Finacle</div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 space-y-0.5">
          {NAV.map(({ to, icon, label, badge }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all ${
                  isActive
                    ? 'bg-gold-400/10 text-gold-400 font-medium'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-white/4'
                }`
              }
            >
              <span className="text-base w-5 text-center">{icon}</span>
              <span className="flex-1">{label}</span>
              {badge && (
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/8 text-slate-500 uppercase tracking-wide">
                  {badge}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {/* User footer */}
        <div className="px-4 py-4 border-t border-white/8">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-gold-400/20 flex items-center justify-center text-gold-400 text-xs font-bold">
              R
            </div>
            <div>
              <div className="text-xs text-slate-300">Rahul S.</div>
              <div className="text-[10px] text-slate-600">ops_reviewer</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {children}
      </div>
    </div>
  )
}
