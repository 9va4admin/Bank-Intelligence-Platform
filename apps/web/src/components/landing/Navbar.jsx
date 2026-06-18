import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-navy-950/95 backdrop-blur-md border-b border-white/5 shadow-xl shadow-black/30'
          : 'bg-transparent'
      }`}
    >
      <nav className="max-w-7xl mx-auto px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Logo */}
        <a href="#" className="flex items-center gap-3 group">
          <div className="relative w-8 h-8">
            <div className="absolute inset-0 rounded-lg bg-gold-400/20 group-hover:bg-gold-400/30 transition-colors" />
            <div className="absolute inset-[3px] rounded-md bg-gold-400 flex items-center justify-center">
              <span className="text-navy-950 font-mono font-bold text-xs tracking-wider">A</span>
            </div>
          </div>
          <span className="font-semibold text-white tracking-wide">ASTRA</span>
        </a>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-8">
          {[
            { label: 'Platform', href: '#platform' },
            { label: 'CTS Module', href: '#cts' },
            { label: 'EJ Module', href: '#ej' },
            { label: 'Security', href: '#security' },
            { label: 'Architecture', href: '#architecture' },
          ].map(({ label, href }) => (
            <a
              key={href}
              href={href}
              className="text-sm text-slate-400 hover:text-white transition-colors duration-200"
            >
              {label}
            </a>
          ))}
        </div>

        {/* CTA */}
        <div className="hidden md:flex items-center gap-3">
          <Link
            to="/cts"
            className="text-sm text-slate-400 hover:text-white transition-colors px-4 py-2"
          >
            CTS Demo
          </Link>
          <Link
            to="/ej"
            className="text-sm font-medium bg-violet-600 hover:bg-violet-500 text-white px-5 py-2 rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-violet-500/20"
          >
            EJ Dashboard
          </Link>
          <a
            href="#contact"
            className="text-sm font-medium bg-gold-400 hover:bg-gold-500 text-navy-950 px-5 py-2 rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-gold-400/20"
          >
            Request Demo
          </a>
        </div>

        {/* Mobile menu button */}
        <button
          className="md:hidden text-slate-400 hover:text-white p-2"
          onClick={() => setMenuOpen(!menuOpen)}
          aria-label="Toggle menu"
        >
          <div className={`w-5 h-0.5 bg-current mb-1.5 transition-all ${menuOpen ? 'rotate-45 translate-y-2' : ''}`} />
          <div className={`w-5 h-0.5 bg-current mb-1.5 transition-all ${menuOpen ? 'opacity-0' : ''}`} />
          <div className={`w-5 h-0.5 bg-current transition-all ${menuOpen ? '-rotate-45 -translate-y-2' : ''}`} />
        </button>
      </nav>

      {/* Mobile menu */}
      <div className={`md:hidden transition-all duration-300 overflow-hidden ${menuOpen ? 'max-h-96' : 'max-h-0'}`}>
        <div className="bg-navy-950/98 border-b border-white/5 px-6 py-4 flex flex-col gap-3">
          {[
            { label: 'Platform', href: '#platform' },
            { label: 'CTS Module', href: '#cts' },
            { label: 'EJ Module', href: '#ej' },
            { label: 'Security', href: '#security' },
            { label: 'Architecture', href: '#architecture' },
          ].map(({ label, href }) => (
            <a
              key={href}
              href={href}
              className="text-sm text-slate-400 hover:text-white py-1.5"
              onClick={() => setMenuOpen(false)}
            >
              {label}
            </a>
          ))}
          <Link
            to="/ej"
            className="mt-1 text-sm font-medium bg-violet-600 text-white px-5 py-2.5 rounded-lg text-center"
            onClick={() => setMenuOpen(false)}
          >
            EJ Dashboard
          </Link>
          <a
            href="#contact"
            className="mt-1 text-sm font-medium bg-gold-400 text-navy-950 px-5 py-2.5 rounded-lg text-center"
            onClick={() => setMenuOpen(false)}
          >
            Request Demo
          </a>
        </div>
      </div>
    </header>
  )
}
