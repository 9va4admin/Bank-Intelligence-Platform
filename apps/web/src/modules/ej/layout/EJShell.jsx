import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'

export default function EJShell({ children }) {
  const { isDark, toggle } = useTheme()

  const bg      = 'bg-gray-100 text-gray-900 dark:bg-gray-900 dark:text-gray-100'
  const topbar  = 'bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-700'
  const logoText = 'text-gray-900 dark:text-white'
  const subtext  = 'text-gray-500 dark:text-gray-400'

  return (
    <div className={`min-h-screen ${bg}`}>
      {/* Top bar */}
      <div className={`border-b px-6 py-3 flex items-center justify-between ${topbar}`}>
        <Link to="/" className="flex items-center gap-3 group">
          <div className="relative w-6 h-6">
            <div className="absolute inset-0 rounded bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[2px] rounded bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-[10px]">A</span>
            </div>
          </div>
          <span className={`text-sm font-bold ${logoText}`}>ASTRA</span>
          <span className={`text-xs ${subtext}`}>/ EJ Intelligence</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link to="/" className={`text-xs ${subtext} hover:underline`}>← Portal</Link>
          <button
            onClick={toggle}
            title={'Switch to dark mode dark:Switch dark:to dark:light dark:mode'}
            className={`w-8 h-8 rounded-lg flex items-center justify-center text-base transition-all ${
              'hover:bg-gray-100 text-gray-500 dark:hover:bg-white/10 dark:text-gray-400'
            }`}
          >
            {'🌙 dark:☀'}
          </button>
        </div>
      </div>

      {/* Page content */}
      <div>{children}</div>
    </div>
  )
}
