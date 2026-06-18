import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import BatchStats from '../components/BatchStats'
import QueueCard from '../components/QueueCard'
import ReviewPanel from '../components/ReviewPanel'
import { MOCK_QUEUE, BATCH_STATS } from '../data/mockQueue'

export default function CTSWorkstation() {
  const [queue, setQueue] = useState(
    [...MOCK_QUEUE].sort((a, b) => new Date(a.iet_deadline) - new Date(b.iet_deadline))
  )
  const [selected, setSelected] = useState(MOCK_QUEUE[0])
  const [decisions, setDecisions] = useState([])

  const pending = queue.filter((q) => q.status === 'PENDING')
  const decided = queue.filter((q) => q.status !== 'PENDING')

  const handleDecision = (id, action, reason) => {
    setQueue((prev) =>
      prev.map((item) =>
        item.instrument_id === id
          ? { ...item, status: action === 'CONFIRM' ? 'CONFIRMED' : 'RETURNED' }
          : item
      )
    )
    setDecisions((prev) => [{ id, action, reason, ts: new Date().toLocaleTimeString() }, ...prev])
    const next = pending.find((p) => p.instrument_id !== id)
    setSelected(next || null)
  }

  return (
    <AppShell>
      <div className="flex flex-col h-full">
        {/* Batch stats header */}
        <BatchStats stats={{ ...BATCH_STATS, human_review: pending.length }} />

        {/* Main split view */}
        <div className="flex flex-1 min-h-0">
          {/* Queue column */}
          <div className="w-80 shrink-0 border-r border-white/8 flex flex-col">
            <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
              <div className="text-xs font-semibold text-white">
                Human Review Queue
              </div>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                pending.length > 0
                  ? 'text-amber-400 border-amber-400/30 bg-amber-400/10'
                  : 'text-emerald-400 border-emerald-400/30 bg-emerald-400/10'
              }`}>
                {pending.length} pending
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
              {pending.length === 0 && (
                <div className="text-center text-slate-600 text-sm py-12">
                  <div className="text-3xl mb-2">✓</div>
                  <div>Queue clear</div>
                </div>
              )}
              {pending.map((item) => (
                <QueueCard
                  key={item.instrument_id}
                  item={item}
                  selected={selected?.instrument_id === item.instrument_id}
                  onClick={() => setSelected(item)}
                />
              ))}

              {decided.length > 0 && (
                <>
                  <div className="text-[10px] text-slate-600 uppercase tracking-widest pt-3 pb-1 px-1">
                    Decided this session
                  </div>
                  {decided.map((item) => (
                    <div
                      key={item.instrument_id}
                      className="rounded-xl border border-white/5 bg-white/2 px-4 py-3 opacity-50"
                    >
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] font-mono text-slate-500">{item.instrument_id}</div>
                        <span className={`text-[10px] font-semibold ${
                          item.status === 'CONFIRMED' ? 'text-emerald-400' : 'text-red-400'
                        }`}>
                          {item.status === 'CONFIRMED' ? '✓ Confirmed' : '✕ Returned'}
                        </span>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Review panel */}
          <ReviewPanel
            item={selected}
            onDecision={handleDecision}
          />

          {/* Activity log */}
          <div className="w-56 shrink-0 border-l border-white/8 flex flex-col">
            <div className="px-4 py-3 border-b border-white/5">
              <div className="text-xs font-semibold text-white">Activity Log</div>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
              {decisions.length === 0 && (
                <div className="text-[11px] text-slate-600 text-center pt-6">No decisions yet</div>
              )}
              {decisions.map((d, i) => (
                <div key={i} className="rounded-lg border border-white/5 bg-white/2 px-3 py-2">
                  <div className={`text-[10px] font-semibold ${d.action === 'CONFIRM' ? 'text-emerald-400' : 'text-red-400'}`}>
                    {d.action === 'CONFIRM' ? '✓ Confirmed' : '✕ Returned'}
                  </div>
                  <div className="text-[10px] font-mono text-slate-600 mt-0.5 truncate">{d.id}</div>
                  {d.reason && <div className="text-[10px] text-slate-500 mt-0.5 leading-tight">{d.reason}</div>}
                  <div className="text-[10px] text-slate-700 mt-1">{d.ts}</div>
                </div>
              ))}
            </div>

            <div className="px-3 py-3 border-t border-white/5 space-y-1.5">
              <div className="flex justify-between text-[10px]">
                <span className="text-slate-600">Confirmed</span>
                <span className="text-emerald-400 font-mono">{decisions.filter(d => d.action === 'CONFIRM').length}</span>
              </div>
              <div className="flex justify-between text-[10px]">
                <span className="text-slate-600">Returned</span>
                <span className="text-red-400 font-mono">{decisions.filter(d => d.action === 'RETURN').length}</span>
              </div>
              <div className="flex justify-between text-[10px]">
                <span className="text-slate-600">Immudb writes</span>
                <span className="text-slate-400 font-mono">{decisions.length}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
