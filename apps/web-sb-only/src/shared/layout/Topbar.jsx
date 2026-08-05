import { useTheme } from '../theme/ThemeContext'
import { BANK_CONFIG } from '../config/bank.config'

function SunIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4">
      <circle cx="10" cy="10" r="3.5" />
      <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.9 4.9l1.4 1.4M13.7 13.7l1.4 1.4M4.9 15.1l1.4-1.4M13.7 6.3l1.4-1.4"
        strokeLinecap="round" />
    </svg>
  )
}
function MoonIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4">
      <path d="M17 12A7 7 0 118 3a5.5 5.5 0 009 9z" strokeLinejoin="round" />
    </svg>
  )
}

export default function Topbar({ title }) {
  const { isDark, toggle } = useTheme()

  return (
    <header className={[
      'h-12 flex items-center justify-between px-5 border-b flex-shrink-0',
      isDark
        ? 'bg-shell-800 border-white/8'
        : 'bg-white border-slate-200',
    ].join(' ')}>

      {/* Left: page title */}
      <h1 className={[
        'text-sm font-semibold',
        isDark ? 'text-white' : 'text-slate-900',
      ].join(' ')}>
        {title}
      </h1>

      {/* Right: bank id badge + theme toggle */}
      <div className="flex items-center gap-3">
        <span className={[
          'text-[10px] font-mono px-2 py-0.5 rounded-full border',
          isDark
            ? 'text-slate-400 border-white/10 bg-white/4'
            : 'text-slate-500 border-slate-200 bg-slate-50',
        ].join(' ')}>
          {BANK_CONFIG.bank_short_name} · {BANK_CONFIG.clearing_zone}
        </span>

        <button
          onClick={toggle}
          aria-label="Toggle theme"
          className={[
            'p-1.5 rounded-md transition-colors',
            isDark
              ? 'text-slate-400 hover:text-slate-200 hover:bg-white/8'
              : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100',
          ].join(' ')}>
          {isDark ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>
    </header>
  )
}
