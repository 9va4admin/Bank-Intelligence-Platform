import { Link } from 'react-router-dom'
import { msg } from '../../shared/messages'

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
                <span className="font-bold text-white text-sm">{msg('UI_COMMON_ASTRA')}</span>
                <span className="text-[10px] text-teal-300/60 tracking-widest">{msg('UI_FOOTER_BANKING_INTELLIGENCE')}</span>
              </div>
            </div>
            <p className="text-slate-400 text-xs leading-relaxed mb-3">
             {msg('UI_FOOTER_AUTOMATED_SETTLEMENT_AND_TRANSACTION')}
            </p>
            <p className="text-slate-500 text-xs">
             {msg('UI_FOOTER_DOMAIN_EXPERTISE_NILESH_SHAH')}<br />
             {msg('UI_FOOTER_EX_NPCI_PIRAMAL_FULLERTON_SMFG')}
            </p>
          </div>

          {/* Platform */}
          <div>
            <div className="text-xs font-semibold text-slate-400 tracking-widest uppercase mb-4">{msg('UI_FOOTER_PLATFORM')}</div>
            <div className="space-y-2">
              {[
                { label: msg('UI_FOOTER_CTS_MODULE'), href: '#cts' },
                { label: msg('UI_FOOTER_SECURITY_COMPLIANCE'), href: '#security' },
                { label: msg('UI_ARCHITECTURE_ARCHITECTURE'), href: '#architecture' },
                { label: msg('UI_FOOTER_COMMERCIAL_MODEL'), href: '#commercial' },
                { label: msg('UI_FOOTER_CTS_FAQ'), href: 'CTS_FAQ.html', external: true },
              ].map(({ label, href, external }) => (
                <a
                  key={href}
                  href={href}
                  target={external ? '_blank' : undefined}
                  rel={external ? 'noopener noreferrer' : undefined}
                  className="block text-sm text-slate-400 hover:text-white transition-colors"
                >
                  {label}
                </a>
              ))}
            </div>
          </div>

          {/* Demos */}
          <div>
            <div className="text-xs font-semibold text-slate-400 tracking-widest uppercase mb-4">{msg('UI_FOOTER_LIVE_DEMOS')}</div>
            <div className="space-y-3">
              <Link
                to="/cts"
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-teal-300 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-teal-400" />
               {msg('UI_FOOTER_CTS_OPERATIONS_WORKSTATION')}
              </Link>
            </div>

            <div className="mt-6 pt-6 border-t border-white/10">
              <a
                href="#contact"
                className="inline-flex items-center gap-2 text-sm font-medium bg-teal-400 hover:bg-teal-500 text-forest-900 px-5 py-2.5 rounded-xl transition-colors"
              >
               {msg('UI_FOOTER_REQUEST_DEMO')}
              </a>
            </div>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="border-t border-white/10 pt-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-slate-500">
           {msg('UI_FOOTER_2026_ASTRA_BANK_INTELLIGENCE_PLATFOR')}
          </p>
          <div className="flex items-center gap-4">
            <span className="text-xs text-slate-500">{msg('UI_FOOTER_CLASSIFICATION_CONFIDENTIAL')}</span>
            <span className="text-xs text-teal-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-400 animate-pulse" />
             {msg('UI_FOOTER_RBI_IET_MANDATE_READY')}
            </span>
          </div>
        </div>
      </div>
    </footer>
  )
}
