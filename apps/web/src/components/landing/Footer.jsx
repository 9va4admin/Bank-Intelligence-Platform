import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="bg-forest-900 text-white py-12 px-6">
      <div className="max-w-6xl mx-auto">
        <div className="grid sm:grid-cols-3 gap-8 mb-10">
          {/* Brand */}
          <div>
            <div className="flex items-center gap-3 mb-4">
              <div className="relative w-8 h-8">
                <div className="absolute inset-0 rounded-lg bg-teal-400/20" />
                <div className="absolute inset-[3px] rounded-md bg-teal-400 flex items-center justify-center">
                  <span className="text-forest-900 font-mono font-bold text-xs">A</span>
                </div>
              </div>
              <div className="flex flex-col leading-none">
                <span className="font-bold text-white text-sm">ASTRA</span>
                <span className="text-[10px] text-teal-300/60 tracking-widest">BANKING INTELLIGENCE</span>
              </div>
            </div>
            <p className="text-slate-400 text-xs leading-relaxed mb-3">
              Automated Settlement and Transaction Recognition Architecture. Built for Indian banks. Deployed on-premises. RBI-compliant from day one.
            </p>
            <p className="text-slate-500 text-xs">
              Domain expertise: Nilesh Shah<br />
              Ex-NPCI · Piramal · Fullerton/SMFG
            </p>
          </div>

          {/* Platform */}
          <div>
            <div className="text-xs font-semibold text-slate-400 tracking-widest uppercase mb-4">Platform</div>
            <div className="space-y-2">
              {[
                { label: 'CTS Module', href: '#cts' },
                { label: 'ATM EJ Intelligence', href: '#ej' },
                { label: 'Security & Compliance', href: '#security' },
                { label: 'Architecture', href: '#architecture' },
                { label: 'Commercial Model', href: '#commercial' },
              ].map(({ label, href }) => (
                <a key={href} href={href} className="block text-sm text-slate-400 hover:text-white transition-colors">{label}</a>
              ))}
            </div>
          </div>

          {/* Demos */}
          <div>
            <div className="text-xs font-semibold text-slate-400 tracking-widest uppercase mb-4">Live Demos</div>
            <div className="space-y-3">
              <Link
                to="/cts"
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-teal-300 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-teal-400" />
                CTS Operations Workstation
              </Link>
              <Link
                to="/ej"
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-sky-300 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
                EJ Intelligence Dashboard
              </Link>
              <Link
                to="/ej/portal"
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-300 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                Manager Portal
              </Link>
            </div>

            <div className="mt-6 pt-6 border-t border-white/10">
              <a
                href="#contact"
                className="inline-flex items-center gap-2 text-sm font-medium bg-teal-400 hover:bg-teal-500 text-forest-900 px-5 py-2.5 rounded-xl transition-colors"
              >
                Request Demo →
              </a>
            </div>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="border-t border-white/10 pt-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
            © 2026 ASTRA Bank Intelligence Platform. Confidential — Banking Grade.
          </p>
          <div className="flex items-center gap-4">
            <span className="text-xs text-slate-500">Classification: Confidential</span>
            <span className="text-xs text-teal-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
              RBI IET Mandate Ready
            </span>
          </div>
        </div>
      </div>
    </footer>
  )
}
