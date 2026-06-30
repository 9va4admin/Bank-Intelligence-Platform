import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

const MOCK_RESULTS = [
  { instrument_id: 'INS-2024-001234', cheque_number: '000234', account_display: '****4521', payee_display: 'R***', amount_range: '₹[1L-5L]', status: 'STP_CONFIRM', clearing_zone: 'MUMBAI', received_at: '2026-06-25T09:14:23Z', fraud_score: 0.12, ocr_confidence: 0.97 },
  { instrument_id: 'INS-2024-001235', cheque_number: '000235', account_display: '****7890', payee_display: 'S***', amount_range: '₹[5L-10L]', status: 'HUMAN_REVIEW', clearing_zone: 'DELHI',  received_at: '2026-06-25T09:18:05Z', fraud_score: 0.74, ocr_confidence: 0.91 },
  { instrument_id: 'INS-2024-001236', cheque_number: '000236', account_display: '****1122', payee_display: 'M***', amount_range: '₹[<1L]',    status: 'STP_RETURN',  clearing_zone: 'MUMBAI', received_at: '2026-06-25T08:52:11Z', fraud_score: 0.88, ocr_confidence: 0.95 },
]

const STATUS_STYLE = {
  STP_CONFIRM:  { dot: 'bg-emerald-400', label: 'Confirmed',     text: 'text-emerald-400' },
  STP_RETURN:   { dot: 'bg-red-400',     label: 'Returned',      text: 'text-red-400'     },
  HUMAN_REVIEW: { dot: 'bg-amber-400',   label: 'Human Review',  text: 'text-amber-400'   },
  RUNNING:      { dot: 'bg-blue-400',    label: 'Processing',    text: 'text-blue-400'    },
}

function useDebouncedSearch(query, delay = 300) {
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (query.trim().length < 3) {
      setResults([])
      return
    }
    setLoading(true)
    const timer = setTimeout(async () => {
      try {
        // In production: fetch(`/v1/cts/instruments/search?q=${encodeURIComponent(query)}&limit=8`)
        const q = query.toLowerCase()
        const filtered = MOCK_RESULTS.filter(
          (r) =>
            r.cheque_number.includes(q) ||
            r.instrument_id.toLowerCase().includes(q) ||
            r.account_display.includes(q)
        )
        setResults(filtered)
      } finally {
        setLoading(false)
      }
    }, delay)
    return () => clearTimeout(timer)
  }, [query, delay])

  return { results, loading }
}

export default function ChequeSearchBar({ isDark }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState(null)
  const [activeIdx, setActiveIdx] = useState(-1)
  const inputRef = useRef(null)
  const dropdownRef = useRef(null)
  const navigate = useNavigate()
  const { results, loading } = useDebouncedSearch(query)

  const showDropdown = open && query.trim().length >= 3

  const closeAll = useCallback(() => {
    setOpen(false)
    setSelected(null)
    setActiveIdx(-1)
  }, [])

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (!inputRef.current?.closest('[data-search-root]')?.contains(e.target)) closeAll()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [closeAll])

  // Keyboard nav
  const onKeyDown = (e) => {
    if (!showDropdown) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIdx((i) => Math.min(i + 1, results.length - 1)) }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setActiveIdx((i) => Math.max(i - 1, 0)) }
    if (e.key === 'Enter' && activeIdx >= 0) openDetail(results[activeIdx])
    if (e.key === 'Escape') { closeAll(); inputRef.current?.blur() }
  }

  const openDetail = (item) => {
    setSelected(item)
    setOpen(false)
    setActiveIdx(-1)
  }

  const clearAndClose = () => {
    setQuery('')
    setSelected(null)
    setOpen(false)
    setActiveIdx(-1)
  }

  const ib = isDark
    ? 'bg-white/8 border-white/10 text-white placeholder-slate-500 focus:border-gold-400/60 focus:bg-white/12'
    : 'bg-slate-100 border-slate-200 text-slate-800 placeholder-slate-400 focus:border-amber-400 focus:bg-white'

  return (
    <div data-search-root="1" className="relative">
      {/* Input */}
      <div className="relative flex items-center">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
          className={`absolute left-2.5 w-3.5 h-3.5 pointer-events-none ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
          <circle cx="6.5" cy="6.5" r="4" />
          <path strokeLinecap="round" d="M11 11l2.5 2.5" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActiveIdx(-1) }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search cheque / instrument…"
          className={`h-7 w-56 pl-7 pr-6 rounded-lg border text-[11px] outline-none transition-all ${ib}`}
        />
        {query && (
          <button onClick={clearAndClose} className={`absolute right-2 ${isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600'}`}>
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" className="w-3 h-3">
              <path strokeLinecap="round" d="M2 2l8 8M10 2l-8 8" />
            </svg>
          </button>
        )}
      </div>

      {/* Dropdown results */}
      {showDropdown && (
        <div
          ref={dropdownRef}
          className={`absolute top-full mt-1.5 right-0 w-80 rounded-xl border shadow-2xl z-50 overflow-hidden ${
            isDark ? 'bg-[#0e1654]/98 backdrop-blur-xl border-white/10 shadow-black/60' : 'bg-white border-slate-200 shadow-slate-300/50'
          }`}
        >
          {loading ? (
            <div className={`px-4 py-3 text-[11px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>Searching…</div>
          ) : results.length === 0 ? (
            <div className={`px-4 py-3 text-[11px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>No cheques found for "{query}"</div>
          ) : (
            <ul>
              {results.map((r, i) => {
                const st = STATUS_STYLE[r.status] ?? STATUS_STYLE.RUNNING
                return (
                  <li key={r.instrument_id}>
                    <button
                      onClick={() => openDetail(r)}
                      className={`w-full text-left px-4 py-2.5 transition-colors flex items-start gap-3 ${
                        i === activeIdx
                          ? (isDark ? 'bg-white/10' : 'bg-slate-100')
                          : (isDark ? 'hover:bg-white/6' : 'hover:bg-slate-50')
                      } ${i > 0 ? (isDark ? 'border-t border-white/5' : 'border-t border-slate-100') : ''}`}
                    >
                      <div className="shrink-0 pt-0.5">
                        <span className={`inline-block w-1.5 h-1.5 rounded-full mt-1 ${st.dot}`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-[12px] font-mono font-semibold ${isDark ? 'text-white' : 'text-slate-800'}`}>
                            #{r.cheque_number}
                          </span>
                          <span className={`text-[10px] font-medium ${st.text}`}>{st.label}</span>
                        </div>
                        <div className={`text-[10px] mt-0.5 flex items-center gap-2 ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
                          <span>{r.account_display}</span>
                          <span className="opacity-40">·</span>
                          <span>{r.payee_display}</span>
                          <span className="opacity-40">·</span>
                          <span>{r.amount_range}</span>
                          <span className="opacity-40">·</span>
                          <span>{r.clearing_zone}</span>
                        </div>
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          <div className={`px-4 py-1.5 text-[10px] border-t flex items-center justify-between ${isDark ? 'border-white/5 text-slate-600' : 'border-slate-100 text-slate-400'}`}>
            <span>↑↓ navigate · Enter to open · Esc to close</span>
            <span>{results.length} result{results.length !== 1 ? 's' : ''}</span>
          </div>
        </div>
      )}

      {/* Detail modal */}
      {selected && (
        <ChequeDetailModal item={selected} isDark={isDark} onClose={clearAndClose} />
      )}
    </div>
  )
}

function ChequeDetailModal({ item, isDark, onClose }) {
  const st = STATUS_STYLE[item.status] ?? STATUS_STYLE.RUNNING

  const overlay = 'fixed inset-0 z-[100] flex items-center justify-center'
  const backdrop = isDark ? 'bg-black/70 backdrop-blur-sm' : 'bg-black/40 backdrop-blur-sm'
  const panel = isDark
    ? 'bg-[#0c1445] border border-white/10 shadow-2xl shadow-black/60'
    : 'bg-white border border-slate-200 shadow-2xl shadow-slate-400/30'

  const row = (label, value, mono = false) => (
    <div className={`flex items-start gap-2 py-1.5 border-b last:border-0 ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
      <span className={`w-36 shrink-0 text-[11px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
      <span className={`text-[12px] ${mono ? 'font-mono' : 'font-medium'} ${isDark ? 'text-white' : 'text-slate-800'}`}>{value ?? '—'}</span>
    </div>
  )

  return (
    <div className={overlay} onClick={onClose}>
      <div className={`relative w-[480px] max-w-[95vw] rounded-2xl ${panel}`} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className={`flex items-center justify-between px-5 pt-4 pb-3 border-b ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
          <div>
            <div className="flex items-center gap-2.5">
              <span className={`text-[15px] font-bold font-mono ${isDark ? 'text-white' : 'text-slate-900'}`}>
                Cheque #{item.cheque_number}
              </span>
              <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium border ${
                item.status === 'STP_CONFIRM'  ? (isDark ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' : 'bg-emerald-50 text-emerald-700 border-emerald-200') :
                item.status === 'STP_RETURN'   ? (isDark ? 'bg-red-900/40 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200') :
                item.status === 'HUMAN_REVIEW' ? (isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40' : 'bg-amber-50 text-amber-700 border-amber-200') :
                (isDark ? 'bg-blue-900/40 text-blue-300 border-blue-700/40' : 'bg-blue-50 text-blue-700 border-blue-200')
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${st.dot}`} />
                {st.label}
              </span>
            </div>
            <div className={`text-[10px] mt-0.5 font-mono ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{item.instrument_id}</div>
          </div>
          <button
            onClick={onClose}
            className={`w-7 h-7 rounded-lg flex items-center justify-center transition-colors ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/10' : 'text-slate-400 hover:text-slate-700 hover:bg-slate-100'}`}
          >
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5">
              <path strokeLinecap="round" d="M2 2l8 8M10 2l-8 8" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-3">
          <div className={`text-[10px] font-semibold uppercase tracking-widest mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Instrument Details</div>
          {row('Cheque Number', item.cheque_number, true)}
          {row('Account', item.account_display, true)}
          {row('Payee', item.payee_display)}
          {row('Amount Range', item.amount_range)}
          {row('Clearing Zone', item.clearing_zone)}
          {row('Received At', new Date(item.received_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }))}

          <div className={`text-[10px] font-semibold uppercase tracking-widest mt-3 mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>AI Scores</div>
          {row('Fraud Score', item.fraud_score != null ? (
            <span className={item.fraud_score > 0.7 ? 'text-red-400' : item.fraud_score > 0.4 ? 'text-amber-400' : 'text-emerald-400'}>
              {(item.fraud_score * 100).toFixed(1)}%
            </span>
          ) : null)}
          {row('OCR Confidence', item.ocr_confidence != null ? `${(item.ocr_confidence * 100).toFixed(1)}%` : null)}
        </div>

        {/* Footer */}
        <div className={`px-5 py-3 border-t flex justify-end gap-2 ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
          <button
            onClick={onClose}
            className={`px-3 py-1.5 text-[11px] rounded-lg transition-colors ${isDark ? 'text-slate-400 hover:text-white hover:bg-white/10' : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100'}`}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
