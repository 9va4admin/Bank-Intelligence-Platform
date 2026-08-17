import { useNavigate } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'

export default function AccessDenied() {
  const { isDark } = useTheme()
  const navigate = useNavigate()

  return (
    <div className={`min-h-screen w-full grid place-items-center ${isDark ? 'bg-[#020817] text-white' : 'bg-slate-50 text-slate-900'}`}>
      <div className="text-center max-w-sm px-6">
        <div className={`text-5xl font-bold mb-3 tabular-nums ${isDark ? 'text-white/10' : 'text-slate-200'}`}>403</div>
        <h1 className={`text-lg font-semibold mb-2 ${isDark ? 'text-white' : 'text-slate-900'}`}>Access Denied</h1>
        <p className={`text-sm mb-6 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
          Your role does not have permission to view this page.
          Contact your bank IT admin if you believe this is incorrect.
        </p>
        <button
          onClick={() => navigate(-1)}
          className={`text-sm px-4 py-2 rounded-lg border font-medium transition-colors
            ${isDark
              ? 'border-white/12 text-slate-300 hover:bg-white/5'
              : 'border-slate-200 text-slate-700 hover:bg-slate-100'}`}
        >
          Go back
        </button>
      </div>
    </div>
  )
}
