import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'

export default function EJShell({ children }) {
  const { isDark, toggle } = useTheme()

  const bg      = isDark ? 'bg-gray-900 text-gray-100' : 'bg-gray-100 text-gray-900'
  const topbar  = isDark ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
  const logoText = isDark ? 'text-white' : 'text-gray-900'
  const subtext  = isDark ? 'text-gray-400' : 'text-gray-500'

  return (
    <div className={`min-h-screen ${bg}`}>
      {/* Top bar */}
      <div className={`border-b px-6 py-3 flex items-center justify-between ${topbar}`}>
        <div className="flex items-center gap-3">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <span className={`text-sm font-bold ${logoText}`}>ASTRA</span>
          <span className={`text-xs ${subtext}`}>/ EJ Intelligence</span>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/" className={`text-xs ${subtext} hover:underline`}>← Portal</Link>
          <button
            onClick={toggle}
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            className={`w-8 h-8 rounded-lg flex items-center justify-center text-base transition-all ${
              isDark ? 'hover:bg-white/10 text-gray-400' : 'hover:bg-gray-100 text-gray-500'
            }`}
          >
            {isDark ? '☀' : '🌙'}
          </button>
        </div>
      </div>

      {/* Page content */}
      <div>{children}</div>
    </div>
  )
}
