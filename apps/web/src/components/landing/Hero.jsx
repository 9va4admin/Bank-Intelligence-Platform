import { useEffect, useRef } from 'react'

const STATS = [
  { value: '₹71L Cr', label: 'Cleared annually via CTS', sub: 'FY25' },
  { value: '609M', label: 'Cheques processed per year', sub: 'India' },
  { value: '<600ms', label: 'AI decision wall-clock', sub: 'p99 guarantee' },
  { value: '2.5L+', label: 'ATMs generating EJ logs', sub: '5+ OEM formats' },
]

export default function Hero() {
  const heroRef = useRef(null)

  useEffect(() => {
    const el = heroRef.current
    if (!el) return
    const items = el.querySelectorAll('.animate-item')
    items.forEach((item, i) => {
      setTimeout(() => {
        item.classList.add('animate-fade-up')
        item.classList.remove('opacity-0-init')
      }, i * 120)
    })
  }, [])

  return (
    <section
      ref={heroRef}
      className="relative min-h-screen flex flex-col items-center justify-center text-center pt-20 pb-16 overflow-hidden"
    >
      {/* Background grid */}
      <div className="absolute inset-0 grid-pattern opacity-60" />

      {/* Radial glows */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full bg-blue-600/8 blur-3xl pointer-events-none" />
      <div className="absolute top-1/3 left-1/4 w-[400px] h-[400px] rounded-full bg-gold-400/6 blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-[300px] h-[300px] rounded-full bg-violet-600/8 blur-3xl pointer-events-none" />

      <div className="relative z-10 max-w-5xl mx-auto px-6">
        {/* Badge */}
        <div className="animate-item opacity-0-init inline-flex items-center gap-2 glass rounded-full px-4 py-1.5 mb-8">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse-slow" />
          <span className="text-xs font-medium text-slate-300 tracking-wide uppercase">
            RBI IET Mandate · Jan 2026 · <span className="text-gold-400">18-Month First-Mover Window</span>
          </span>
        </div>

        {/* Main headline */}
        <h1 className="animate-item opacity-0-init text-5xl sm:text-6xl lg:text-7xl font-bold leading-[1.08] tracking-tight mb-6">
          <span className="text-gradient">Precision Banking.</span>
          <br />
          <span className="text-white">Zero Compromise.</span>
        </h1>

        {/* Sub-headline */}
        <p className="animate-item opacity-0-init text-lg sm:text-xl text-slate-400 leading-relaxed max-w-2xl mx-auto mb-10">
          ASTRA is an AI-native platform for Indian banks — solving the RBI T+3 IET mandate
          for cheque clearing and bringing intelligence to ATM EJ logs across all OEM formats.
          <span className="text-slate-300"> 100% on-premises. No cloud. No vendor data access.</span>
        </p>

        {/* CTA row */}
        <div className="animate-item opacity-0-init flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
          <a
            href="#contact"
            className="group relative inline-flex items-center gap-2 bg-gold-400 hover:bg-gold-500 text-navy-950 font-semibold px-8 py-3.5 rounded-xl text-sm transition-all duration-200 hover:shadow-2xl hover:shadow-gold-400/25 hover:-translate-y-0.5"
          >
            Schedule a Demo
            <svg className="w-4 h-4 transition-transform group-hover:translate-x-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
            </svg>
          </a>
          <a
            href="#platform"
            className="inline-flex items-center gap-2 glass text-slate-300 hover:text-white font-medium px-8 py-3.5 rounded-xl text-sm transition-all duration-200 hover:-translate-y-0.5"
          >
            <svg className="w-4 h-4 text-gold-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
            </svg>
            See How It Works
          </a>
        </div>

        {/* Stats bar */}
        <div className="animate-item opacity-0-init grid grid-cols-2 lg:grid-cols-4 gap-px bg-white/5 rounded-2xl overflow-hidden border border-white/5">
          {STATS.map(({ value, label, sub }) => (
            <div key={label} className="bg-navy-900/60 px-6 py-6 text-center">
              <div className="text-2xl sm:text-3xl font-bold text-gradient mb-1">{value}</div>
              <div className="text-xs text-slate-400 leading-tight">{label}</div>
              <div className="text-xs text-slate-600 mt-0.5">{sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Scroll indicator */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 animate-bounce opacity-40">
        <span className="text-xs text-slate-500 uppercase tracking-widest">Scroll</span>
        <svg className="w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </section>
  )
}
