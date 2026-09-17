/**
 * CommandPalette — global Ctrl+K launcher for ASTRA CTS.
 * Rendered inside AppShell, which passes open/onClose/isDark/onToggleTheme.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

const COMMANDS = [
  { id: 'nav-hrq',      group: 'CTS Inward',  label: 'Human Review Queue',         sub: 'Claim and review pending instruments',         to: '/cts/inward/review-queue', icon: '👁' },
  { id: 'nav-inward',   group: 'CTS Inward',  label: 'Inward Monitor',              sub: 'Live swimlane view of inward clearing session', to: '/cts/inward',              icon: '📥' },
  { id: 'nav-decisions',group: 'CTS Inward',  label: 'AI Decisions Log',            sub: 'All AI-driven cheque decisions',               to: '/cts/decisions',           icon: '🧠' },
  { id: 'nav-vault-st', group: 'CTS Vault',   label: 'Vault Status',                sub: 'Signature and PPS vault health + trends',      to: '/cts/vault/status',        icon: '🔐' },
  { id: 'nav-vault-up', group: 'CTS Vault',   label: 'Vault Upload',                sub: 'Upload signature / PPS / stop payment CSV',    to: '/cts/vault/upload',        icon: '📤' },
  { id: 'nav-vault-sy', group: 'CTS Vault',   label: 'Vault Sync Schedule',         sub: 'Next sync countdown and sync history',         to: '/cts/vault/sync',          icon: '🔄' },
  { id: 'nav-vault-gap',group: 'CTS Vault',   label: 'Vault Gap Report',            sub: 'Accounts with no vault specimen — enroll before next session', to: '/cts/vault/gaps', icon: '⚠️' },
  { id: 'nav-outward',  group: 'CTS Outward', label: 'Outward Clearing',            sub: 'Scanner capture, lot management, NGCH filing', to: '/cts/outward',             icon: '📄' },
  { id: 'nav-ops',      group: 'Operations',  label: 'Operations Dashboard',        sub: 'Platform health, alerts, and throughput',      to: '/ops/dashboard',           icon: '📊' },
  { id: 'nav-audit',    group: 'Admin',       label: 'Audit Trail',                 sub: 'Immutable audit log (Immudb)',                  to: '/admin/audit',             icon: '📋' },
  { id: 'nav-admin',    group: 'Admin',       label: 'Admin Console',               sub: 'Bank configuration and user management',       to: '/admin',                   icon: '⚙️' },
  { id: 'act-theme',    group: 'Actions',     label: 'Toggle Dark / Light Theme',   sub: 'Switch between dark and light mode',           action: 'toggle-theme',         icon: '🌙' },
]

export default function CommandPalette({ open, onClose, onToggleTheme, isDark }) {
  const [query, setQuery] = useState('')
  const [cursor, setCursor] = useState(0)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const navigate = useNavigate()

  const filtered = query.trim()
    ? COMMANDS.filter(c =>
        c.label.toLowerCase().includes(query.toLowerCase()) ||
        c.sub.toLowerCase().includes(query.toLowerCase()) ||
        c.group.toLowerCase().includes(query.toLowerCase())
      )
    : COMMANDS

  useEffect(() => {
    if (open) {
      setQuery('')
      setCursor(0)
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }, [open])

  useEffect(() => { setCursor(0) }, [query])

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${cursor}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  const execute = useCallback((cmd) => {
    if (cmd.to) navigate(cmd.to)
    else if (cmd.action === 'toggle-theme') onToggleTheme?.()
    onClose()
  }, [navigate, onClose, onToggleTheme])

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, filtered.length - 1)) }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)) }
      if (e.key === 'Enter' && filtered[cursor]) execute(filtered[cursor])
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, cursor, filtered, execute, onClose])

  if (!open) return null

  const bg     = isDark ? '#0a1535' : '#ffffff'
  const border = isDark ? 'rgba(255,255,255,0.1)' : '#e2e8f0'
  const text   = isDark ? '#e2e8f0' : '#1e293b'
  const muted  = isDark ? '#64748b' : '#94a3b8'
  const hover  = isDark ? 'rgba(255,255,255,0.07)' : '#f1f5f9'
  const accent = isDark ? 'rgba(245,200,66,0.08)'  : '#fefce8'

  // Build grouped view
  const groups = {}
  for (const cmd of filtered) {
    if (!groups[cmd.group]) groups[cmd.group] = []
    groups[cmd.group].push(cmd)
  }
  let globalIdx = 0

  return (
    <div
      className="fixed inset-0 z-[9998] flex items-start justify-center pt-[14vh]"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg mx-4 rounded-2xl shadow-2xl overflow-hidden"
        style={{ background: bg, border: `1px solid ${border}` }}
        onClick={e => e.stopPropagation()}
      >
        {/* Search row */}
        <div className="flex items-center gap-3 px-4 py-3" style={{ borderBottom: `1px solid ${border}` }}>
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4 shrink-0" style={{ color: muted }}>
            <circle cx="8.5" cy="8.5" r="5.5" />
            <path d="M12.5 12.5l4 4" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search pages and actions…"
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: text }}
          />
          <kbd className="text-[10px] px-1.5 py-0.5 rounded font-mono" style={{ color: muted, border: `1px solid ${border}` }}>Esc</kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="overflow-y-auto py-2" style={{ maxHeight: '55vh' }}>
          {filtered.length === 0 ? (
            <div className="text-center py-10 text-sm" style={{ color: muted }}>No results for "{query}"</div>
          ) : (
            Object.entries(groups).map(([group, cmds]) => (
              <div key={group}>
                <div className="px-4 pt-3 pb-1 text-[10px] font-bold uppercase tracking-widest" style={{ color: muted }}>{group}</div>
                {cmds.map((cmd) => {
                  const idx = globalIdx++
                  const isActive = idx === cursor
                  return (
                    <button
                      key={cmd.id}
                      data-idx={idx}
                      onClick={() => execute(cmd)}
                      onMouseEnter={() => setCursor(idx)}
                      className="w-full text-left flex items-center gap-3 px-4 py-2.5 transition-colors"
                      style={{ background: isActive ? (cursor === idx ? accent : hover) : 'transparent', color: text }}
                    >
                      <span className="w-5 text-base shrink-0">{cmd.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium truncate" style={{ color: isActive ? (isDark ? '#f5c842' : '#b45309') : text }}>{cmd.label}</div>
                        <div className="text-[11px] truncate mt-0.5" style={{ color: muted }}>{cmd.sub}</div>
                      </div>
                      {cmd.to && (
                        <kbd className="text-[10px] px-1.5 py-0.5 rounded font-mono shrink-0" style={{ color: muted, border: `1px solid ${border}` }}>↵</kbd>
                      )}
                    </button>
                  )
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2.5 text-[10px]" style={{ borderTop: `1px solid ${border}`, color: muted }}>
          <span><kbd className="font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="font-mono">↵</kbd> open</span>
          <span><kbd className="font-mono">Esc</kbd> close</span>
          <span className="ml-auto font-mono">Ctrl K</span>
        </div>
      </div>
    </div>
  )
}
