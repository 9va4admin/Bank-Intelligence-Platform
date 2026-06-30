import { useState, useEffect, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import BatchStats from '../components/BatchStats'
import QueueCard from '../components/QueueCard'
import ReviewPanel from '../components/ReviewPanel'
import { BATCH_STATS, getStpStream } from '../data/mockQueue'
import useReviewQueue from '../hooks/useReviewQueue'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'

const STP_DELAY_MS = 3200
const SESSION_START = new Date(new Date().setHours(10, 0, 0, 0))
const IET_WINDOW_MINS = 180

export default function CTSWorkstation() {
  const { bankId, bankName, bankIfsc, bankType, isSB, isSMB } = useBankContext()
  const { isDark } = useTheme()
  // Token would come from auth context in production; undefined triggers mock fallback in dev
  const { items: liveItems, loading: queueLoading, useMock } = useReviewQueue({ pollEnabled: true })
  const [queue, setQueue] = useState([])
  const [selected, setSelected] = useState(null)
  const [decisions, setDecisions] = useState([])

  useEffect(() => {
    if (!queueLoading) {
      setQueue((prev) => {
        // Preserve local decision state (CONFIRMED/RETURNED) across poll refreshes
        const localDecisions = new Map(prev.map(item => [item.instrument_id, item.status]))
        const merged = liveItems.map(item => ({
          ...item,
          status: localDecisions.get(item.instrument_id) ?? item.status,
        }))
        // Auto-select first pending item when queue first loads
        if (prev.length === 0 && merged.length > 0) {
          const firstPending = merged.find(i => i.status === 'PENDING')
          if (firstPending) setSelected(firstPending)
        }
        return merged
      })
    }
  }, [liveItems, queueLoading])

  const stpSource   = useRef(getStpStream())
  const stpIndexRef = useRef(0)
  const [stpStream, setStpStream]   = useState([])
  const [batchStats, setBatchStats] = useState({ ...BATCH_STATS })
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

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
        stp_returned:  item.outcome === 'RETURN'  ? prev.stp_returned  + 1 : prev.stp_returned,
        total_inward:  prev.total_inward + 1,
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

  const sessionElapsedSec = Math.max(0, Math.floor((now - SESSION_START) / 1000))
  const sessionElapsedStr = `${String(Math.floor(sessionElapsedSec / 3600)).padStart(2,'0')}:${String(Math.floor((sessionElapsedSec % 3600) / 60)).padStart(2,'0')}:${String(sessionElapsedSec % 60).padStart(2,'0')}`

  usePageHeader({
    subtitle: `AM Clearing · SES-0619-001 · IET Window: ${IET_WINDOW_MINS}min`,
    actions: (
      <div className="flex items-center gap-3">
        <div className={`text-[10px] font-mono px-3 py-1.5 rounded-lg border ${isDark ? 'border-white/10 text-slate-300 bg-white/4' : 'border-slate-200 text-slate-600 bg-white'}`}>
          Session {sessionElapsedStr}
        </div>
        <div className={`flex items-center gap-1.5 text-[10px] px-3 py-1.5 rounded-lg border ${
          pending.length > 0
            ? isDark ? 'border-amber-700/40 bg-amber-900/20 text-amber-300' : 'border-amber-200 bg-amber-50 text-amber-700'
            : isDark ? 'border-emerald-700/40 bg-emerald-900/20 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${pending.length > 0 ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
          {pending.length > 0 ? `${pending.length} awaiting review` : 'Queue clear'}
        </div>
      </div>
    ),
  })

  const stpRate = batchStats.total_inward > 0
    ? ((batchStats.stp_confirmed + batchStats.stp_returned) / batchStats.total_inward * 100).toFixed(1)
    : BATCH_STATS.stp_rate.toFixed(1)

  const th = {
    divider:  isDark ? 'border-white/8'   : 'border-slate-200',
    dividerSm:isDark ? 'border-white/5'   : 'border-slate-100',
    heading:  isDark ? 'text-white'       : 'text-slate-900',
    muted:    isDark ? 'text-slate-400'   : 'text-slate-500',
    faint:    isDark ? 'text-slate-500'   : 'text-slate-400',
    decided:  isDark ? 'border-white/5 bg-white/5' : 'border-slate-100 bg-slate-50',
    footer:   isDark ? 'border-white/5'   : 'border-slate-100',
    empty:    isDark ? 'text-slate-500'   : 'text-slate-400',
  }

  return (
    <AppShell>
      <div className="flex flex-col h-full">
        <BatchStats stats={{ ...batchStats, human_review: pending.length, stp_rate: parseFloat(stpRate) }} />

        <div className="flex flex-1 min-h-0">
          {/* Queue column */}
          <div className={`w-72 shrink-0 border-r ${th.divider} flex flex-col`}>
            <div className={`px-4 py-3 border-b ${th.dividerSm} flex items-center justify-between`}>
              <div className={`text-xs font-semibold ${th.heading}`}>Human Review Queue</div>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                pending.length > 0
                  ? 'text-amber-500 border-amber-500/30 bg-amber-500/10'
                  : 'text-emerald-500 border-emerald-500/30 bg-emerald-500/10'
              }`}>
                {pending.length} pending
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
              {pending.length === 0 && (
                <div className={`text-center ${th.empty} text-sm py-12`}>
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
                  isDark={isDark}
                />
              ))}

              {decided.length > 0 && (
                <>
                  <div className={`text-[10px] ${th.faint} uppercase tracking-widest pt-3 pb-1 px-1`}>
                    Decided this session
                  </div>
                  {decided.map((item) => (
                    <div key={item.instrument_id} className={`rounded-xl border ${th.decided} px-4 py-3 opacity-50`}>
                      <div className="flex items-center justify-between">
                        <div className={`text-[11px] font-mono ${th.muted}`}>{item.instrument_id}</div>
                        <span className={`text-[10px] font-semibold ${item.status === 'CONFIRMED' ? 'text-emerald-500' : 'text-red-500'}`}>
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
          <div className={`w-64 shrink-0 border-l ${th.divider} flex flex-col`}>
            <div className={`px-4 py-3 border-b ${th.dividerSm} flex items-center justify-between`}>
              <div className={`text-xs font-semibold ${th.heading}`}>STP Live Stream</div>
              <span className="flex items-center gap-1.5 text-[10px] text-emerald-500">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                AI Processing
              </span>
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1.5">
              {stpStream.length === 0 && (
                <div className={`text-[11px] ${th.empty} text-center pt-8 leading-relaxed`}>
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
                  }`}
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className={`text-[10px] font-semibold ${item.outcome === 'CONFIRM' ? 'text-emerald-500' : 'text-red-500'}`}>
                      {item.outcome === 'CONFIRM' ? '✓ STP Confirmed' : '✕ STP Returned'}
                    </span>
                    <span className={`text-[9px] font-mono ${th.faint}`}>{item.ms}ms</span>
                  </div>
                  <div className={`text-[10px] font-mono ${th.muted} truncate`}>{item.id}</div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={`text-[9px] ${th.faint}`}>{item.acct}</span>
                    <span className={`text-[9px] ${th.faint}`}>·</span>
                    <span className={`text-[9px] ${th.faint}`}>{item.amt}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Session summary footer */}
            <div className={`px-4 pt-4 pb-4 border-t ${th.footer}`}>
              <div className={`text-[11px] font-extrabold uppercase tracking-widest mb-4 ${isDark ? 'text-slate-100' : 'text-slate-900'}`}>
                This Session
              </div>

              <div className="flex flex-col gap-3.5">
                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-medium ${th.muted}`}>STP Confirmed</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-emerald-400' : 'text-emerald-600'}`}>
                    {stpStream.filter(s => s.outcome === 'CONFIRM').length}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-medium ${th.muted}`}>STP Returned</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                    {stpStream.filter(s => s.outcome === 'RETURN').length}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className={`text-[11px] font-medium ${th.muted}`}>Human decisions</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                    {decisions.length}
                  </span>
                </div>

                <div className={`flex items-center justify-between pt-3 border-t ${th.divider}`}>
                  <span className={`text-[11px] font-medium ${th.muted}`}>Immudb writes</span>
                  <span className={`text-3xl font-black leading-none tabular-nums ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>
                    {stpStream.length + decisions.length}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
