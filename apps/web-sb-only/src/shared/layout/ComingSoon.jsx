import { useTheme } from '../theme/ThemeContext'

export default function ComingSoon({ page }) {
  const { isDark } = useTheme()
  return (
    <div className="flex items-center justify-center h-full min-h-64">
      <div className={[
        'text-center px-8 py-10 rounded-xl border',
        isDark ? 'bg-shell-800 border-white/8 text-slate-400' : 'bg-white border-slate-200 text-slate-500',
      ].join(' ')}>
        <div className="text-3xl mb-3">🚧</div>
        <p className="text-sm font-medium">{page}</p>
        <p className="text-xs mt-1 opacity-60">Coming next sprint</p>
      </div>
    </div>
  )
}
