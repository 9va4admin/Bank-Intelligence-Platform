/**
 * InfoTooltip — reusable hover/click tooltip for configuration field descriptions.
 *
 * Usage:
 *   <InfoTooltip text="Description of the config key…" isDark={isDark} />
 *
 * Shows a small ℹ icon. On hover (desktop) or tap (mobile), shows the text in a
 * floating tooltip above the icon. Theme-aware via isDark prop.
 *
 * Accessibility: the ℹ button has role="button" and aria-label so screen readers
 * announce it as an info button.
 */
import { useState, useRef, useEffect } from 'react'

export default function InfoTooltip({ text, isDark, placement = 'top' }) {
  const [visible, setVisible] = useState(false)
  const ref = useRef(null)

  // Close when clicking outside
  useEffect(() => {
    if (!visible) return
    function handle(e) {
      if (ref.current && !ref.current.contains(e.target)) setVisible(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [visible])

  if (!text) return null

  const tipCls = isDark
    ? 'bg-navy-800 border border-white/12 text-slate-300 shadow-xl'
    : 'bg-white border border-slate-200 text-slate-700 shadow-lg'

  const placementCls = placement === 'bottom'
    ? 'top-full mt-1.5'
    : 'bottom-full mb-1.5'

  return (
    <span ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        aria-label="Show description"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        onClick={() => setVisible(v => !v)}
        className={`inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] leading-none font-bold transition-colors select-none
          ${isDark
            ? 'text-slate-500 hover:text-slate-300 border border-slate-600/50 hover:border-slate-400/50'
            : 'text-slate-400 hover:text-slate-600 border border-slate-300 hover:border-slate-400'
          }`}
      >
        ℹ
      </button>

      {visible && (
        <span
          className={`absolute z-50 left-1/2 -translate-x-1/2 w-64 max-w-xs text-xs leading-relaxed rounded-xl px-3 py-2.5 ${tipCls} ${placementCls}`}
          role="tooltip"
        >
          {text}
          {/* Arrow */}
          <span className={`absolute left-1/2 -translate-x-1/2 w-2 h-2 rotate-45
            ${placement === 'bottom'
              ? `-top-1 ${isDark ? 'bg-navy-800 border-l border-t border-white/12' : 'bg-white border-l border-t border-slate-200'}`
              : `-bottom-1 ${isDark ? 'bg-navy-800 border-r border-b border-white/12' : 'bg-white border-r border-b border-slate-200'}`
            }`}
          />
        </span>
      )}
    </span>
  )
}
