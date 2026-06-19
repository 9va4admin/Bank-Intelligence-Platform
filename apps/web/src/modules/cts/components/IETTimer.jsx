import { useState, useEffect } from 'react'

function getTimeLeft(deadline) {
  const diff = new Date(deadline) - Date.now()
  if (diff <= 0) return { mins: 0, secs: 0, total: 0 }
  return {
    total: diff,
    mins: Math.floor(diff / 60000),
    secs: Math.floor((diff % 60000) / 1000),
  }
}

function urgencyClass(mins, bright) {
  if (bright) {
    if (mins < 10) return 'text-white bg-red-500 border-red-400 font-bold'
    if (mins < 30) return 'text-white bg-amber-500 border-amber-400 font-bold'
    return 'text-white bg-emerald-600 border-emerald-500 font-bold'
  }
  if (mins < 10) return 'text-red-400 border-red-400/40 bg-red-400/10'
  if (mins < 30) return 'text-amber-400 border-amber-400/40 bg-amber-400/10'
  return 'text-emerald-400 border-emerald-400/40 bg-emerald-400/10'
}

export default function IETTimer({ deadline, compact = false, bright = false }) {
  const [left, setLeft] = useState(() => getTimeLeft(deadline))

  useEffect(() => {
    const id = setInterval(() => setLeft(getTimeLeft(deadline)), 1000)
    return () => clearInterval(id)
  }, [deadline])

  const cls = urgencyClass(left.mins, bright)
  const pulse = left.mins < 10

  if (compact) {
    return (
      <span className={`inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded border ${cls} ${pulse ? 'animate-pulse' : ''}`}>
        ⏱ {left.mins}m {String(left.secs).padStart(2, '0')}s
      </span>
    )
  }

  return (
    <div className={`rounded-xl border px-4 py-3 ${cls} ${pulse ? 'animate-pulse' : ''}`}>
      <div className="text-[10px] uppercase tracking-widest opacity-70 mb-1">IET Remaining</div>
      <div className="font-mono text-2xl font-bold tabular-nums">
        {String(left.mins).padStart(2, '0')}:{String(left.secs).padStart(2, '0')}
      </div>
      <div className="text-[10px] opacity-60 mt-0.5">T+3h deadline</div>
    </div>
  )
}
