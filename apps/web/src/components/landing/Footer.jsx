export default function Footer() {
  return (
    <footer className="border-t border-white/5 py-12 px-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-6">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="relative w-7 h-7">
              <div className="absolute inset-0 rounded-md bg-gold-400/20" />
              <div className="absolute inset-[2px] rounded-md bg-gold-400 flex items-center justify-center">
                <span className="text-navy-950 font-mono font-bold text-xs">A</span>
              </div>
            </div>
            <div>
              <div className="text-sm font-semibold text-white">ASTRA</div>
              <div className="text-xs text-slate-600">Automated Settlement & Transaction Recognition Architecture</div>
            </div>
          </div>

          {/* Links */}
          <div className="flex items-center gap-6 text-xs text-slate-500">
            <a href="#platform" className="hover:text-slate-300 transition-colors">Platform</a>
            <a href="#cts" className="hover:text-slate-300 transition-colors">CTS</a>
            <a href="#ej" className="hover:text-slate-300 transition-colors">EJ Intelligence</a>
            <a href="#security" className="hover:text-slate-300 transition-colors">Security</a>
            <a href="#contact" className="hover:text-slate-300 transition-colors">Contact</a>
          </div>

          {/* Legal */}
          <div className="text-xs text-slate-700">
            © 2026 ASTRA · Confidential · Banking Grade
          </div>
        </div>

        {/* Bottom tagline */}
        <div className="mt-8 pt-6 border-t border-white/4 text-center">
          <p className="text-xs text-slate-700">
            Built by <span className="text-slate-500">Nilesh Shah</span> · Ex-NPCI · Ex-Piramal · Ex-Fullerton/SMFG ·
            <span className="text-slate-600"> Sanskrit: precision weapon · Latin: star</span>
          </p>
        </div>
      </div>
    </footer>
  )
}
