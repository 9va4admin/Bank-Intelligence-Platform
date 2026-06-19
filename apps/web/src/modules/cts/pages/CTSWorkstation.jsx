import { useState, useEffect, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import BatchStats from '../components/BatchStats'
import QueueCard from '../components/QueueCard'
import ReviewPanel from '../components/ReviewPanel'
import { MOCK_QUEUE, BATCH_STATS, getStpStream } from '../data/mockQueue'

const STP_DELAY_MS = 3200  // new STP entry every ~3s

export default function CTSWorkstation() {
  const [queue, setQueue] = useState(
    [...MOCK_QUEUE].sort((a, b) => new Date(a.iet_deadline) - new Date(b.iet_deadline))
  )
  const [selected, setSelected] = useState(MOCK_QUEUE[0])
  const [decisions, setDecisions] = useState([])

  // Live STP stream simulation
  const stpSource = useRef(getStpStream())
  const stpIndexRef = useRef(0)
  const [stpStream, setStpStream] = useState([])
  const [batchStats, setBatchStats] = useState({ ...BATCH_STATS })

  useEffect(() => {
    const timer = setInterval(() => {
      const items = stpSource.current
      if (stpIndexRef.current >= items.length) return
      const item = items[stpIndexRef.current]
      stpIndexRef.current += 1

      setStpStream((prev) => [{ ...item, arrivedAt: new Date() }, ...prev].slice(0, 40))
      setBatchStats((prev) => ({
        ...prev,
        stp_confirmed: item.outcome === 'CONFIRM' ? prev.stp_confirmed + 1 : prev.stp_confirmed,
        stp_returned: item.outcome === 'RETURN' ? prev.stp_returned + 1 : prev.stp_returned,
        total_inward: prev.total_inward + 1,
      }))
    }, STP_DELAY_MS)
    return () => clearInterval(timer)
  }, [])

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

  const stpRate = batchStats.total_inward > 0
    ? ((batchStats.stp_confirmed + batchStats.stp_returned) / batchStats.total_inward * 100).toFixed(1)
    : BATCH_STATS.stp_rate.toFixed(1)

  return (
    <AppShell>
      <div className="flex flex-col h-full">
        <BatchStats stats={{ ...batchStats, human_review: pending.length, stp_rate: parseFloat(stpRate) }} />

        <div className="flex flex-1 min-h-0">
          {/* Queue column */}
          <div className="w-72 shrink-0 border-r border-white/8 flex flex-col">
            <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
              <div className="text-xs font-semibold text-white">Human Review Queue</div>
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
                    <div key={item.instrument_id} className="rounded-xl border border-white/5 bg-white/2 px-4 py-3 opacity-50">
                      <div className="flex items-center justify-between">
                        <div className="text-[11px] font-mono text-slate-500">{item.instrument_id}</div>
                        <span className={`text-[10px] font-semibold ${item.status === 'CONFIRMED' ? 'text-emerald-400' : 'text-red-400'}`}>
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
          <ReviewPanel item={selected} onDecision={handleDecision} />

          {/* Live STP stream */}
          <div className="w-64 shrink-0 border-l border-white/8 flex flex-col">
            <div className="px-4 py-3 border-b border-white/5 flex items-center justify-between">
              <div className="text-xs font-semibold text-white">STP Live Stream</div>
              <span className="flex items-center gap-1.5 text-[10px] text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                AI Processing
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1.5">
              {stpStream.length === 0 && (
                <div className="text-[11px] text-slate-600 text-center pt-8 leading-relaxed">
                  <div className="text-2xl mb-2">⚡</div>
                  STP agents processing<br />inward cheques…
                </div>
              )}
              {stpStream.map((item, i) => (
                <div
                  key={`${item.id}-${i}`}
                  className={`rounded-lg border px-3 py-2 ${
                    item.outcome === 'CONFIRM'
                      ? 'border-emerald-500/20 bg-emerald-500/5'
                      : 'border-red-500/20 bg-red-500/5'
                  } ${i === 0 ? 'ring-1 ring-white/10' : ''}`}
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className={`text-[10px] font-semibold ${item.outcome === 'CONFIRM' ? 'text-emerald-400' : 'text-red-400'}`}>
                      {item.outcome === 'CONFIRM' ? '✓ STP Confirmed' : '✕ STP Returned'}
                    </span>
                    <span className="text-[9px] font-mono text-slate-600">{item.ms}ms</span>
                  </div>
                  <div className="text-[10px] font-mono text-slate-500 truncate">{item.id}</div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[9px] text-slate-600">{item.acct}</span>
                    <span className="text-[9px] text-slate-700">·</span>
                    <span className="text-[9px] text-slate-600">{item.amt}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Session summary footer */}
            <div className="px-3 py-3 border-t border-white/5 space-y-1.5">
              <div className="text-[9px] text-slate-600 uppercase tracking-widest mb-2">This Session</div>
              <div className="flex justify-between text-[10px]">
                <span className="text-slate-600">STP Confirmed</span>
                <span className="text-emerald-400 font-mono">{stpStream.filter(s => s.outcome === 'CONFIRM').length}</span>
              </div>
              <div className="flex justify-between text-[10px]">
                <span className="text-slate-600">STP Returned</span>
                <span className="text-red-400 font-mono">{stpStream.filter(s => s.outcome === 'RETURN').length}</span>
              </div>
              <div className="flex justify-between text-[10px]">
                <span className="text-slate-600">Human decisions</span>
                <span className="text-amber-400 font-mono">{decisions.length}</span>
              </div>
              <div className="mt-2 pt-2 border-t border-white/5 flex justify-between text-[10px]">
                <span className="text-slate-600">Immudb writes</span>
                <span className="text-slate-400 font-mono">{stpStream.length + decisions.length}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
