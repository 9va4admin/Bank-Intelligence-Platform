import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'

const NAV_LINKS = [
  { label: 'Platform', href: '#platform' },
  { label: 'CTS', href: '#cts' },
  { label: 'EJ Intelligence', href: '#ej' },
  { label: 'Commercial', href: '#commercial' },
  { label: 'Security', href: '#security' },
  { label: 'CTS FAQ', href: 'CTS_FAQ.html', external: true },
]

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 48)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-white/95 backdrop-blur-md border-b border-slate-200 shadow-sm'
          : 'bg-forest-900/95 backdrop-blur-sm'
      }`}
    >
      <nav className="max-w-7xl mx-auto px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Logo */}
        <a href="#" className="flex items-center gap-3 group">
          <div className="relative w-8 h-8">
            <div className={`absolute inset-0 rounded-lg transition-colors ${scrolled ? 'bg-teal-400/10' : 'bg-teal-400/20'}`} />
            <div className="absolute inset-[3px] rounded-md bg-teal-400 flex items-center justify-center">
              <span className="text-forest-900 font-mono font-bold text-xs tracking-wider">A</span>
            </div>
          </div>
          <div className="flex flex-col leading-none">
            <span className={`font-bold tracking-wide text-sm ${scrolled ? 'text-slate-800' : 'text-white'}`}>ASTRA</span>
            <span className={`text-[10px] tracking-widest ${scrolled ? 'text-slate-400' : 'text-teal-300/70'}`}>BANKING INTELLIGENCE</span>
          </div>
        </a>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-7">
          {NAV_LINKS.map(({ label, href, external }) => (
            <a
              key={href}
              href={href}
              target={external ? '_blank' : undefined}
              rel={external ? 'noopener noreferrer' : undefined}
              className={`text-sm font-medium transition-colors duration-200 ${
                scrolled ? 'text-slate-500 hover:text-slate-900' : 'text-slate-300 hover:text-white'
              }`}
            >
              {label}
            </a>
          ))}
        </div>

        {/* CTA */}
        <div className="hidden md:flex items-center gap-3">
          <Link
            to="/cts"
            className={`text-sm px-4 py-1.5 rounded-md border transition-colors ${
              scrolled
                ? 'text-slate-600 border-slate-300 hover:bg-slate-50'
                : 'text-slate-300 border-white/20 hover:bg-white/10'
            }`}
          >
            CTS Demo
          </Link>
          <Link
            to="/ej"
            className="text-sm font-medium bg-teal-400 hover:bg-teal-500 text-forest-900 px-5 py-2 rounded-lg transition-colors"
          >
            EJ Dashboard
          </Link>
          <a
            href="#contact"
            className="text-sm font-medium bg-sky-400 hover:bg-sky-500 text-white px-5 py-2 rounded-lg transition-colors"
          >
            Request Demo
          </a>
        </div>

        {/* Mobile toggle */}
        <button
          className={`md:hidden p-2 ${scrolled ? 'text-slate-600' : 'text-slate-300'}`}
          onClick={() => setMenuOpen(!menuOpen)}
          aria-label="Toggle menu"
        >
          <div className={`w-5 h-0.5 bg-current mb-1.5 transition-all ${menuOpen ? 'rotate-45 translate-y-2' : ''}`} />
          <div className={`w-5 h-0.5 bg-current mb-1.5 transition-all ${menuOpen ? 'opacity-0' : ''}`} />
          <div className={`w-5 h-0.5 bg-current transition-all ${menuOpen ? '-rotate-45 -translate-y-2' : ''}`} />
        </button>
      </nav>

      {/* Mobile menu */}
      <div className={`md:hidden overflow-hidden transition-all duration-300 ${menuOpen ? 'max-h-96' : 'max-h-0'}`}>
        <div className={`border-b px-6 py-4 flex flex-col gap-3 ${scrolled ? 'bg-white border-slate-200' : 'bg-forest-900 border-white/10'}`}>
          {NAV_LINKS.map(({ label, href, external }) => (
            <a
              key={href}
              href={href}
              target={external ? '_blank' : undefined}
              rel={external ? 'noopener noreferrer' : undefined}
              className={`text-sm py-1.5 ${scrolled ? 'text-slate-600' : 'text-slate-300'}`}
              onClick={() => setMenuOpen(false)}
            >
              {label}
            </a>
          ))}
          <Link
            to="/ej"
            className="mt-1 text-sm font-medium bg-teal-400 text-forest-900 px-5 py-2.5 rounded-lg text-center"
            onClick={() => setMenuOpen(false)}
          >
            EJ Dashboard
          </Link>
          <a
            href="#contact"
            className="text-sm font-medium bg-sky-400 text-white px-5 py-2.5 rounded-lg text-center"
            onClick={() => setMenuOpen(false)}
          >
            Request Demo
          </a>
        </div>
      </div>
    </header>
  )
}
