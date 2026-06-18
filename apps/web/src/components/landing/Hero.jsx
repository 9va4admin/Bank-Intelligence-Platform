import { useEffect, useRef } from 'react'

const STATS = [
  { value: '₹71.1L Cr', label: 'Cleared via CTS', sub: 'FY2024–25' },
  { value: '609M', label: 'Cheques processed', sub: 'India, per year' },
  { value: '<600ms', label: 'AI decision wall-clock', sub: 'Any batch size, p99' },
  { value: '2.5L+', label: 'ATMs, 5+ OEM formats', sub: 'Zero standard EJ exists' },
]

export default function Hero() {
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.querySelectorAll('.anim').forEach((item, i) => {
      setTimeout(() => {
        item.style.opacity = '1'
        item.style.transform = 'translateY(0)'
      }, i * 130)
    })
  }, [])

  return (
    <>
      {/* Dark band hero */}
      <section
        ref={ref}
        className="relative bg-forest-900 text-white pt-32 pb-20 overflow-hidden"
      >
        {/* Subtle grid */}
        <div className="absolute inset-0 opacity-20"
          style={{
            backgroundImage: 'linear-gradient(rgba(29,158,117,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(29,158,117,0.15) 1px, transparent 1px)',
            backgroundSize: '48px 48px',
          }}
        />
        {/* Glow */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] rounded-full bg-teal-400/8 blur-3xl pointer-events-none" />

        <div className="relative z-10 max-w-6xl mx-auto px-6 text-center">
          {/* Mandate badge */}
          <div
            className="anim inline-flex items-center gap-2.5 border border-teal-400/30 bg-teal-400/8 rounded-full px-5 py-2 mb-8 text-xs font-medium text-teal-300 tracking-wide uppercase"
            style={{ opacity: 0, transform: 'translateY(20px)', transition: 'all 0.5s ease' }}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
            RBI IET Mandate · T+3 Hour Regime · Jan 2026
            <span className="text-teal-400 font-semibold">· 18-Month First-Mover Window</span>
          </div>

          {/* Headline */}
          <h1
            className="anim text-5xl sm:text-6xl lg:text-7xl font-bold leading-[1.07] tracking-tight mb-6"
            style={{ opacity: 0, transform: 'translateY(20px)', transition: 'all 0.5s ease' }}
          >
            <span className="text-white">The Missing Intelligence</span>
            <br />
            <span style={{ background: 'linear-gradient(135deg, #1D9E75, #378ADD)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Layer for Indian Banks.
            </span>
          </h1>

          {/* Sub */}
          <p
            className="anim text-lg sm:text-xl text-slate-300 leading-relaxed max-w-2xl mx-auto mb-4"
            style={{ opacity: 0, transform: 'translateY(20px)', transition: 'all 0.5s ease' }}
          >
            ASTRA brings agentic AI to India's two largest unresolved banking operations —
            cheque truncation compliance and ATM EJ dispute resolution.
            <span className="text-slate-200"> 100% on-premises. No cloud. No vendor data access.</span>
          </p>

          <p
            className="anim text-sm text-slate-400 max-w-xl mx-auto mb-10"
            style={{ opacity: 0, transform: 'translateY(20px)', transition: 'all 0.5s ease' }}
          >
            Built for Urban Co-operative Banks, RRBs, and mid-tier private banks. Certified once for RBI compliance.
            Deployed inside your data center — ASTRA never touches your data.
          </p>

          {/* CTAs */}
          <div
            className="anim flex flex-col sm:flex-row items-center justify-center gap-4 mb-16"
            style={{ opacity: 0, transform: 'translateY(20px)', transition: 'all 0.5s ease' }}
          >
            <a
              href="#contact"
              className="group inline-flex items-center gap-2 bg-teal-400 hover:bg-teal-500 text-forest-900 font-semibold px-8 py-3.5 rounded-xl text-sm transition-all hover:shadow-xl hover:shadow-teal-400/20 hover:-translate-y-0.5"
            >
              Schedule a Demo
              <svg className="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </a>
            <a
              href="#platform"
              className="inline-flex items-center gap-2 border border-white/20 text-slate-300 hover:text-white hover:border-white/40 font-medium px-8 py-3.5 rounded-xl text-sm transition-all"
            >
              See How It Works
            </a>
          </div>

          {/* Stats */}
          <div
            className="anim grid grid-cols-2 lg:grid-cols-4 gap-px rounded-2xl overflow-hidden border border-white/8"
            style={{ opacity: 0, transform: 'translateY(20px)', transition: 'all 0.5s ease', background: 'rgba(255,255,255,0.04)' }}
          >
            {STATS.map(({ value, label, sub }) => (
              <div key={label} className="bg-white/4 px-6 py-6 text-center">
                <div className="text-2xl sm:text-3xl font-bold mb-1" style={{ color: '#1D9E75' }}>{value}</div>
                <div className="text-xs text-slate-300 leading-snug">{label}</div>
                <div className="text-xs text-slate-500 mt-0.5">{sub}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}
