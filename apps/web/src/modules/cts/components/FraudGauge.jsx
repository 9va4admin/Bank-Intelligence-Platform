export default function FraudGauge({ score }) {
  const pct = Math.round(score * 100)

  const color =
    score >= 0.80 ? '#ef4444'
    : score >= 0.72 ? '#f59e0b'
    : '#22c55e'

  const label =
    score >= 0.80 ? 'HIGH RISK'
    : score >= 0.72 ? 'REVIEW'
    : 'LOW RISK'

  // SVG arc gauge
  const r = 52
  const cx = 64
  const cy = 64
  const startAngle = -210
  const endAngle = 30
  const totalDeg = endAngle - startAngle
  const scoreDeg = startAngle + totalDeg * score

  const toRad = (d) => (d * Math.PI) / 180
  const arcX = (deg) => cx + r * Math.cos(toRad(deg))
  const arcY = (deg) => cy + r * Math.sin(toRad(deg))

  const bgPath = `M ${arcX(startAngle)} ${arcY(startAngle)} A ${r} ${r} 0 1 1 ${arcX(endAngle)} ${arcY(endAngle)}`
  const fgPath = `M ${arcX(startAngle)} ${arcY(startAngle)} A ${r} ${r} 0 ${score > 0.5 ? 1 : 0} 1 ${arcX(scoreDeg)} ${arcY(scoreDeg)}`

  return (
    <div className="flex flex-col items-center">
      <svg width="128" height="90" viewBox="0 0 128 90">
        <path d={bgPath} fill="none" stroke="#ffffff10" strokeWidth="10" strokeLinecap="round" />
        <path d={fgPath} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" />
        <text x="64" y="62" textAnchor="middle" fill={color} fontSize="22" fontWeight="700" fontFamily="monospace">
          {pct}
        </text>
        <text x="64" y="76" textAnchor="middle" fill={color} fontSize="9" fontFamily="monospace" opacity="0.8">
          {label}
        </text>
      </svg>
      <div className="text-[10px] text-slate-500 uppercase tracking-widest -mt-1">Fraud Score</div>
    </div>
  )
}
