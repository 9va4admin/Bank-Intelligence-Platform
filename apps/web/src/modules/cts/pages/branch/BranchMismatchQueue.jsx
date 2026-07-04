/**
 * Branch Portal — Mismatch Queue (/branch/mismatch)
 *
 * Supervisor-only screen. Lists cheques currently HELD due to Vision LLM ↔
 * scanner data mismatch. Supervisor can GO_AHEAD (proceed to lot) or REJECT
 * (return to drawer). Calls EEH ResolveMismatch RPC.
 *
 * In Phase 3, mismatches are created by OutwardScanWorkflow when Vision LLM
 * returns different amount/fields from scanner OCR. Until Phase 3, this screen
 * shows the schema and mock data.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import AppShell from '../../../../shared/layout/AppShell'

// ─── Mock mismatch data ───────────────────────────────────────────────────────

const MOCK_MISMATCHES = [
  {
    mismatch_id: 'MM-001',
    scan_id: 'SC-001245',
    branch_id: 'BRANCH-ANDHERI-01',
    held_at: '10:43:47',
    mismatch_fields: ['amount_figures'],
    scanner_amount: '₹45,000',
    vision_amount: '₹4,500',
    payee_display: 'R***',
    lot_id: '',
    status: 'HELD',
  },
  {
    mismatch_id: 'MM-002',
    scan_id: 'SC-001239',
    branch_id: 'BRANCH-ANDHERI-01',
    held_at: '10:41:22',
    mismatch_fields: ['amount_words', 'amount_figures'],
    scanner_amount: '₹1,25,000',
    vision_amount: '₹12,500',
    payee_display: 'B***',
    lot_id: '',
    status: 'HELD',
  },
]

function MismatchCard({ item, onResolve, isDark }) {
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)

  const th = {
    card:    isDark ? 'bg-navy-900 border-amber-500/30' : 'bg-white border-amber-300',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    input:   isDark ? 'bg-navy-950 border-white/10 text-slate-300 placeholder-slate-600'
                    : 'bg-slate-50 border-slate-200 text-slate-700 placeholder-slate-400',
  }

  async function handleResolve(action) {
    setLoading(true)
    await new Promise(r => setTimeout(r, 400))   // mock API call
    onResolve(item.mismatch_id, action, note)
    setLoading(false)
  }

  return (
    <div className={`rounded-lg border p-4 mb-3 ${th.card}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className={`text-xs font-mono ${th.muted}`}>{item.mismatch_id}</span>
          <span className="mx-2 text-amber-400">·</span>
          <span className={`text-xs font-mono ${th.muted}`}>{item.scan_id}</span>
          <span className="mx-2 text-amber-400">·</span>
          <span className={`text-xs ${th.muted}`}>Held {item.held_at}</span>
        </div>
        <span className="inline-flex items-center text-xs px-2 py-0.5 rounded border bg-amber-500/15 text-amber-400 border-amber-500/30">
          HELD
        </span>
      </div>

      {/* Mismatch detail */}
      <div className="grid grid-cols-2 gap-4 mb-3">
        <div>
          <p className={`text-xs font-medium uppercase tracking-wider mb-1 ${th.muted}`}>
            Scanner Read
          </p>
          <p className={`text-lg font-bold tabular-nums text-white`}>{item.scanner_amount}</p>
          <p className={`text-xs mt-0.5 ${th.muted}`}>
            Fields: {item.mismatch_fields.join(', ')}
          </p>
        </div>
        <div>
          <p className={`text-xs font-medium uppercase tracking-wider mb-1 ${th.muted}`}>
            Vision LLM Read
          </p>
          <p className={`text-lg font-bold tabular-nums text-red-400`}>{item.vision_amount}</p>
          <p className={`text-xs mt-0.5 ${th.muted}`}>Mismatch detected</p>
        </div>
      </div>
      <div className="mb-3 text-xs">
        <span className={th.muted}>Payee: </span>
        <span className={`font-medium ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
          {item.payee_display}
        </span>
      </div>

      {/* Supervisor note */}
      <input
        type="text"
        placeholder="Supervisor note (optional)"
        value={note}
        onChange={e => setNote(e.target.value)}
        className={`w-full text-xs px-3 py-2 rounded border mb-3 outline-none focus:ring-1 focus:ring-blue-500/40 ${th.input}`}
      />

      {/* Resolution buttons */}
      <div className="flex gap-2">
        <button
          onClick={() => handleResolve('GO_AHEAD')}
          disabled={loading}
          className="flex-1 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-medium rounded transition-colors"
        >
          {loading ? '…' : 'Go Ahead (trust scanner)'}
        </button>
        <button
          onClick={() => handleResolve('REJECTED')}
          disabled={loading}
          className="flex-1 py-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs font-medium rounded transition-colors"
        >
          {loading ? '…' : 'Reject (return to drawer)'}
        </button>
      </div>
    </div>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function BranchMismatchQueue() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const [mismatches, setMismatches] = useState(MOCK_MISMATCHES)
  const [resolved, setResolved] = useState([])

  function handleResolve(mismatch_id, action, note) {
    setResolved(prev => [...prev, { mismatch_id, action, note, resolved_at: new Date().toLocaleTimeString() }])
    setMismatches(prev => prev.filter(m => m.mismatch_id !== mismatch_id))
  }

  const th = {
    page:    isDark ? 'bg-navy-950'  : 'bg-slate-50',
    heading: isDark ? 'text-white'   : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
  }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        <div className="flex items-center gap-4 mb-5">
          <Link to="/branch" className={`text-sm ${th.muted} hover:text-blue-400 transition-colors`}>
            ← Dashboard
          </Link>
          <h1 className={`text-lg font-semibold ${th.heading}`}>Mismatch Queue</h1>
          {mismatches.length > 0 && (
            <span className="text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded px-2 py-0.5">
              {mismatches.length} pending
            </span>
          )}
        </div>

        {mismatches.length === 0 && resolved.length === 0 && (
          <div className={`text-center py-12 ${th.muted} text-sm`}>
            No held items. All mismatches resolved.
          </div>
        )}

        {mismatches.map(item => (
          <MismatchCard
            key={item.mismatch_id}
            item={item}
            onResolve={handleResolve}
            isDark={isDark}
          />
        ))}

        {resolved.length > 0 && (
          <div className="mt-4">
            <h2 className={`text-sm font-medium mb-2 ${th.muted}`}>Resolved this session</h2>
            {resolved.map(r => (
              <div key={r.mismatch_id} className={`rounded-lg border p-3 mb-2 ${th.card}`}>
                <div className="flex items-center justify-between text-xs">
                  <span className={`font-mono ${th.muted}`}>{r.mismatch_id}</span>
                  <span className={r.action === 'GO_AHEAD' ? 'text-emerald-400' : 'text-red-400'}>
                    {r.action === 'GO_AHEAD' ? 'Proceeded' : 'Rejected'}
                  </span>
                  <span className={th.muted}>{r.resolved_at}</span>
                </div>
                {r.note && <p className={`text-xs mt-1 ${th.muted}`}>{r.note}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  )
}
