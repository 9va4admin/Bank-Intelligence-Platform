/**
 * ChequeImageViewer — multi-view cheque image display for ASTRA CTS.
 *
 * Shows up to 3 scan views per instrument:
 *   BFB  Front Black & White  (CHI Spec: ImageViewDetail ViewType="FrontBlackAndWhite")
 *   BBB  Back Black & White   (CHI Spec: ImageViewDetail ViewType="BackBlackAndWhite")
 *   BFG  Front Grayscale      (CHI Spec: ImageViewDetail ViewType="FrontGrayscale")
 *
 * Props:
 *   views    [{key, label, url, iqaScore?}]  — url null → SVG placeholder
 *   fields   {payee, date, amount_figures, amount_words, micr, alterations}
 *   isDark   boolean
 *   compact  boolean   — reduced chrome for hover popups
 *   title    string    — e.g. instrument_id shown in lightbox
 */
import { useState, useEffect, useCallback } from 'react'

// ── SVG placeholder generator ─────────────────────────────────────────────────

function _svgFront(fields = {}, gray = false) {
  const payee      = fields.payee          || 'Sample Payee Name'
  const date       = fields.date           || '07/07/2026'
  const figStr     = (fields.amount_figures || '₹50,000').replace('₹', '').trim()
  const words      = fields.amount_words   || 'Fifty Thousand Only'
  const micr       = fields.micr           || '000012340050000012100000000005000123456789'
  const altered    = fields.alterations    || false
  const bankName   = fields.bank_name      || 'SARASWAT CO-OP. BANK LTD.'
  const bankBranch = fields.bank_branch    || 'Fort Branch, Mumbai — 400 001'
  const bankIfsc   = fields.bank_ifsc      || 'SRCB0000001'
  const bankMicr   = fields.bank_micr      || '400015002'

  const bg     = gray ? '#f0f0f0' : '#ffffff'
  const ink    = '#111111'
  const light  = gray ? '#666666' : '#444444'
  const micrBg = gray ? '#e4e4e4' : '#f2f2f2'
  const altClr = altered ? '#cc2200' : ink

  // Parse DD MM YYYY from any common format: DD/MM/YYYY or DD-MM-YYYY or DD-Mon-YYYY
  const MON = { Jan:'01',Feb:'02',Mar:'03',Apr:'04',May:'05',Jun:'06',
                Jul:'07',Aug:'08',Sep:'09',Oct:'10',Nov:'11',Dec:'12' }
  let dd = '01', mm = '01', yyyy = '2026'
  if (date) {
    const sep  = date.includes('/') ? '/' : '-'
    const p    = date.split(sep)
    dd   = (p[0] || '01').padStart(2, '0')
    mm   = (MON[p[1]] || (p[1] || '01').padStart(2, '0'))
    yyyy = (p[2] || '2026').padStart(4, '0')
  }
  const dDigits = [...dd, ...mm, ...yyyy]

  const sigSeed = (payee.charCodeAt(0) || 65) % 3
  const sigPaths = [
    `<path d="M518,207 C526,197 536,194 543,200 C550,206 556,192 566,188 C576,184 586,192 595,188 C604,184 614,190 624,186 C632,183 641,189 650,186 L655,207" stroke="${ink}" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M518,211 C528,209 538,212 548,210" stroke="${ink}" stroke-width="0.9" fill="none" stroke-linecap="round"/>`,
    `<path d="M520,210 C529,201 537,197 544,202 S560,196 570,203 C577,208 586,198 596,194 S615,189 625,195 C632,199 641,192 650,195 C657,197 663,202 668,209" stroke="${ink}" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
    `<path d="M522,209 C530,200 536,196 542,201 C548,206 552,194 560,190 C568,186 576,193 584,189 C592,185 601,191 610,188 C619,185 628,191 637,188 L644,208 M522,213 C530,211 538,214 546,211" stroke="${ink}" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
  ]
  const sig = sigPaths[sigSeed]

  const isPrivate = /hdfc|icici|axis|kotak|yes\s*bank/i.test(bankName)

  // ── HDFC / private bank SVG ──────────────────────────────────────────────────
  if (isPrivate) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 320">
  <rect width="760" height="320" fill="${bg}"/>
  <rect x="2" y="2" width="756" height="316" fill="none" stroke="${ink}" stroke-width="1.5"/>
  <!-- Left fine security lines -->
  <line x1="4"  y1="2" x2="4"  y2="318" stroke="#e0e0e0" stroke-width="0.9"/>
  <line x1="7"  y1="2" x2="7"  y2="318" stroke="#e0e0e0" stroke-width="0.9"/>
  <line x1="10" y1="2" x2="10" y2="318" stroke="#e0e0e0" stroke-width="0.9"/>
  <line x1="13" y1="2" x2="13" y2="318" stroke="#e0e0e0" stroke-width="0.9"/>
  <!-- Black HDFC logo box -->
  <rect x="18" y="9" width="148" height="28" fill="#000000"/>
  <text x="26" y="28" font-size="13" font-weight="bold" fill="#ffffff" font-family="Arial,sans-serif" letter-spacing="2">${bankName.toUpperCase()}</text>
  <!-- Bank address -->
  <text x="18" y="50" font-size="8" fill="${light}" font-family="Arial,sans-serif">${bankBranch}</text>
  <text x="18" y="62" font-size="8" fill="${light}" font-family="Arial,sans-serif">RTGS / NEFT IFSC : ${bankIfsc}</text>
  <!-- Weekly holiday note top-right -->
  <text x="568" y="14" font-size="7" fill="#aaaaaa" font-family="Arial,sans-serif">Weekly Holiday on SUNDAY</text>
  <!-- Large loose date digits — no boxes -->
  <text x="566" y="42" font-size="25" font-weight="bold" fill="${ink}" font-family="Courier New,monospace" letter-spacing="4">${dd} ${mm} ${yyyy}</text>
  <text x="567" y="54" font-size="6.5" fill="#888888" font-family="Arial,sans-serif" letter-spacing="5">D D  M M  Y Y Y Y</text>
  <text x="568" y="66" font-size="7" fill="#aaaaaa" font-family="Arial,sans-serif">Valid for 3 months only</text>
  <!-- Divider under header -->
  <line x1="14" y1="74" x2="746" y2="74" stroke="${ink}" stroke-width="0.6"/>
  <!-- Pay line -->
  <text x="18" y="97" font-size="10" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">Pay</text>
  <line x1="40" y1="97" x2="556" y2="97" stroke="${ink}" stroke-width="0.7"/>
  <text x="42" y="96" font-size="13" fill="${ink}" font-family="Georgia,serif" font-style="italic" font-weight="600">${payee}</text>
  <!-- Or Bearer + ya dharak ko stacked right -->
  <text x="562" y="90" font-size="10" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">Or Bearer</text>
  <text x="562" y="103" font-size="8.5" fill="#444444" font-family="Arial,sans-serif">या धारक को</text>
  <!-- Rupees line -->
  <text x="18" y="122" font-size="9" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">Rupees रुपये</text>
  <line x1="98" y1="122" x2="746" y2="122" stroke="${ink}" stroke-width="0.7"/>
  <text x="100" y="121" font-size="12" fill="${ink}" font-family="Georgia,serif" font-style="italic">${words}</text>
  <!-- Second underline -->
  <line x1="14" y1="140" x2="746" y2="140" stroke="${ink}" stroke-width="0.7"/>
  <!-- ada karen label + amount box -->
  <text x="476" y="156" font-size="8.5" fill="${ink}" font-family="Arial,sans-serif">अदा करें</text>
  <rect x="514" y="143" width="226" height="30" fill="none" stroke="#333333" stroke-width="1.5"/>
  <line x1="542" y1="143" x2="542" y2="173" stroke="#666666" stroke-width="1"/>
  <text x="520" y="162" font-size="13" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">&#8377;</text>
  <text x="548" y="164" font-size="14" fill="${altClr}" font-family="Georgia,serif" font-style="italic" font-weight="700">${figStr}/-</text>
  ${altered ? `<line x1="514" y1="143" x2="740" y2="173" stroke="#cc2200" stroke-width="1.5" opacity="0.6"/>` : ''}
  <!-- Account box -->
  <rect x="18" y="184" width="286" height="26" fill="none" stroke="#888888" stroke-width="1"/>
  <line x1="68" y1="184" x2="68" y2="210" stroke="#aaaaaa" stroke-width="0.7"/>
  <text x="22" y="196" font-size="7" fill="#666666" font-family="Arial,sans-serif">A/c No.</text>
  <text x="22" y="207" font-size="7" fill="#666666" font-family="Arial,sans-serif">खाता सं.</text>
  <text x="74" y="202" font-size="11" fill="${ink}" font-family="Courier New,monospace" font-weight="bold">${bankMicr.slice(0, 4)}XXXXXX${bankMicr.slice(-4)}</text>
  <text x="314" y="196" font-size="7.5" fill="#666666" font-family="Arial,sans-serif">Brn: ${bankMicr.slice(0,4)}  Pdt: 100</text>
  <text x="314" y="207" font-size="7.5" fill="#666666" font-family="Arial,sans-serif">SB A/C</text>
  <!-- Payable at par -->
  <text x="18" y="226" font-size="7.5" fill="#888888" font-family="Arial,sans-serif">Payable at par through clearing/transfer at all branches of ${bankName.toUpperCase()} LTD</text>
  <!-- Wavy security pattern bottom-left (faint) -->
  <g opacity="0.09">
    <path d="M18,235 C55,221 95,249 135,235 C175,221 215,249 255,235 C285,225 310,241 335,235" fill="none" stroke="${ink}" stroke-width="3"/>
    <path d="M18,245 C55,231 95,259 135,245 C175,231 215,259 255,245 C285,235 310,251 335,245" fill="none" stroke="${ink}" stroke-width="2.2"/>
    <path d="M18,254 C55,240 95,268 135,254 C175,240 215,268 255,254 C285,244 310,260 335,254" fill="none" stroke="${ink}" stroke-width="1.5"/>
    <path d="M18,262 C55,248 95,276 135,262 C175,248 215,276 255,262 C285,252 310,268 335,262" fill="none" stroke="${ink}" stroke-width="1"/>
    <path d="M18,269 C55,255 95,283 135,269 C175,255 215,283 255,269 C285,259 310,275 335,269" fill="none" stroke="${ink}" stroke-width="0.7"/>
  </g>
  <!-- Signature (shifted down by 45px vs baseline y≈207 → y≈252) -->
  <g transform="translate(0 45)">${sig}</g>
  <!-- Sig line -->
  <line x1="515" y1="262" x2="748" y2="262" stroke="${ink}" stroke-width="0.7"/>
  <text x="528" y="272" font-size="7.5" fill="${light}" font-family="Arial,sans-serif">Please sign above / कृपया ऊपर हस्ताक्षर करें</text>
  <!-- Rule above MICR -->
  <line x1="8" y1="280" x2="752" y2="280" stroke="${ink}" stroke-width="0.6"/>
  <!-- MICR band -->
  <rect x="0" y="282" width="760" height="38" fill="${micrBg}"/>
  <line x1="0" y1="282" x2="760" y2="282" stroke="${ink}" stroke-width="0.5"/>
  <text x="18" y="307" font-size="13.5" fill="${ink}" font-family="'Courier New',monospace" letter-spacing="2.5">${micr}</text>
</svg>`
  }

  // ── PSB / co-op bank SVG (NKGSB, SBI, Saraswat …) ──────────────────────────

  // Individual date digit boxes — 8 squares at top-right
  const digitBoxes = dDigits.map((d, i) => {
    const xOffset = i * 18 + (i >= 2 ? 5 : 0) + (i >= 4 ? 5 : 0)
    const bx = 582 + xOffset
    return `<rect x="${bx}" y="34" width="15" height="20" fill="${bg}" stroke="${ink}" stroke-width="0.9"/>
  <text x="${bx + 7}" y="49" font-size="11" font-weight="bold" fill="${ink}" font-family="Courier New,monospace" text-anchor="middle">${d?.trim() || ''}</text>`
  }).join('\n  ')

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 320">
  <rect width="760" height="320" fill="${bg}"/>
  <rect x="2" y="2" width="756" height="316" fill="none" stroke="${ink}" stroke-width="1.5"/>
  <!-- Left CTS-2010 strip -->
  <rect x="2" y="2" width="13" height="316" fill="#f0f0f0"/>
  <line x1="15" y1="2" x2="15" y2="318" stroke="${ink}" stroke-width="0.6"/>
  <text x="8" y="240" font-size="4.5" fill="#cccccc" font-family="Arial,sans-serif" text-anchor="middle"
        transform="rotate(-90 8 240)" letter-spacing="1">National Technologies Limited • Navi Mumbai / CTS-2010</text>
  <!-- A/C PAYEE crossing lines -->
  <line x1="17" y1="2" x2="17" y2="74" stroke="${ink}" stroke-width="1"/>
  <line x1="46" y1="2" x2="46" y2="74" stroke="${ink}" stroke-width="1"/>
  <text x="20" y="50" font-size="7.5" fill="${ink}" font-family="Arial,sans-serif">A/C</text>
  <text x="18" y="62" font-size="7.5" fill="${ink}" font-family="Arial,sans-serif">PAYEE</text>
  <!-- Bank name (coloured navy) -->
  <text x="56" y="24" font-size="14" font-weight="bold" fill="#1a3a6e" font-family="Arial,sans-serif">${bankName}</text>
  <text x="56" y="38" font-size="8" fill="${light}" font-family="Arial,sans-serif">${bankBranch}</text>
  <text x="56" y="50" font-size="8" fill="${light}" font-family="Arial,sans-serif">IFSC CODE : ${bankIfsc}</text>
  <!-- VALID FOR THREE MONTHS -->
  <text x="570" y="28" font-size="7" fill="#888888" font-family="Arial,sans-serif">VALID FOR THREE MONTHS FROM DATE OF ISSUE</text>
  <!-- Date label + digit boxes -->
  <text x="556" y="49" font-size="7.5" fill="#555555" font-family="Arial,sans-serif">दिनांक / Date</text>
  ${digitBoxes}
  <!-- D D  M M  Y Y Y Y labels -->
  <text x="589" y="62" font-size="5.5" fill="#aaaaaa" font-family="Arial,sans-serif">D D   M M   Y Y Y Y</text>
  <!-- Divider under header -->
  <line x1="14" y1="74" x2="746" y2="74" stroke="${ink}" stroke-width="0.6"/>
  <!-- Pay line -->
  <text x="52" y="97" font-size="10" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">Pay</text>
  <line x1="74" y1="97" x2="564" y2="97" stroke="${ink}" stroke-width="0.7"/>
  <text x="76" y="96" font-size="13" fill="${ink}" font-family="Georgia,serif" font-style="italic" font-weight="600">${payee}</text>
  <text x="568" y="96" font-size="8.5" fill="${ink}" font-family="Arial,sans-serif">या धारक को Or Bearer</text>
  <!-- Rupees line + amount box inline -->
  <text x="52" y="122" font-size="9" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">रुपये Rupees</text>
  <line x1="124" y1="122" x2="490" y2="122" stroke="${ink}" stroke-width="0.7"/>
  <text x="126" y="121" font-size="12" fill="${ink}" font-family="Georgia,serif" font-style="italic">${words}</text>
  <!-- ada karen + amount box -->
  <text x="492" y="120" font-size="8.5" fill="${ink}" font-family="Arial,sans-serif">अदा करें।</text>
  <rect x="536" y="108" width="204" height="28" fill="none" stroke="#333333" stroke-width="1.5"/>
  <line x1="560" y1="108" x2="560" y2="136" stroke="#666666" stroke-width="1"/>
  <text x="540" y="127" font-size="13" fill="${ink}" font-family="Arial,sans-serif" font-weight="bold">&#8377;</text>
  <text x="566" y="128" font-size="14" fill="${altClr}" font-family="Georgia,serif" font-style="italic" font-weight="700">${figStr}/-</text>
  ${altered ? `<line x1="536" y1="108" x2="740" y2="136" stroke="#cc2200" stroke-width="1.5" opacity="0.6"/>` : ''}
  <!-- Account box -->
  <rect x="52" y="148" width="270" height="26" fill="none" stroke="#888888" stroke-width="1"/>
  <line x1="100" y1="148" x2="100" y2="174" stroke="#aaaaaa" stroke-width="0.7"/>
  <text x="56" y="160" font-size="7" fill="#666666" font-family="Arial,sans-serif">खाता सं.</text>
  <text x="56" y="171" font-size="7" fill="#666666" font-family="Arial,sans-serif">A/c No.</text>
  <text x="106" y="167" font-size="11" fill="${ink}" font-family="Courier New,monospace" font-weight="bold">${bankMicr.slice(0,4)}XXXXXX${bankMicr.slice(-4)}</text>
  <!-- Payable at par + bank details -->
  <text x="52" y="196" font-size="8" fill="#888888" font-family="Arial,sans-serif">Payable at par at all branches   ${bankMicr}</text>
  <text x="52" y="210" font-size="8" fill="${light}" font-family="Arial,sans-serif">Branch: ${bankBranch}   IFSC: ${bankIfsc}   MICR: ${bankMicr}</text>
  <!-- Signature (shifted down by 40px) -->
  <g transform="translate(0 40)">${sig}</g>
  <!-- Sig line -->
  <line x1="515" y1="258" x2="748" y2="258" stroke="${ink}" stroke-width="0.7"/>
  <text x="578" y="268" font-size="8.5" fill="${light}" font-family="Arial,sans-serif">Please sign above</text>
  <!-- Rule above MICR -->
  <line x1="8" y1="278" x2="752" y2="278" stroke="${ink}" stroke-width="0.6"/>
  <!-- MICR band -->
  <rect x="0" y="280" width="760" height="40" fill="${micrBg}"/>
  <line x1="0" y1="280" x2="760" y2="280" stroke="${ink}" stroke-width="0.5"/>
  <text x="18" y="306" font-size="13.5" fill="${ink}" font-family="'Courier New',monospace" letter-spacing="2.5">${micr}</text>
</svg>`
}

function _svgBack(fields = {}) {
  const micr   = fields.micr || '000012340050000012100000000005000123456789'
  const ink    = '#111111'
  const light  = '#444444'
  const micrBg = '#f2f2f2'

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 320">
  <rect width="760" height="320" fill="#ffffff"/>
  <rect x="2" y="2" width="756" height="316" rx="3" fill="none" stroke="${ink}" stroke-width="1.5"/>
  <!-- Vertical crossing band -->
  <rect x="5" y="5" width="44" height="310" fill="none" stroke="${ink}" stroke-width="1.1"/>
  <text x="27" y="160" font-size="7.5" fill="${ink}" font-family="sans-serif"
        text-anchor="middle" transform="rotate(-90 27 160)">ACCOUNT PAYEE ONLY — NOT NEGOTIABLE</text>
  <!-- Endorsement area label -->
  <text x="68" y="35" font-size="10" fill="${light}" font-family="sans-serif" text-decoration="underline">ENDORSEMENT</text>
  <!-- Endorsement lines -->
  <line x1="68" y1="55"  x2="748" y2="55"  stroke="${ink}" stroke-width="0.6"/>
  <line x1="68" y1="90"  x2="748" y2="90"  stroke="${ink}" stroke-width="0.6"/>
  <line x1="68" y1="125" x2="748" y2="125" stroke="${ink}" stroke-width="0.6"/>
  <!-- Credit area -->
  <text x="68" y="175" font-size="10" fill="${light}" font-family="sans-serif">FOR THE CREDIT OF A/C</text>
  <line x1="68" y1="188" x2="748" y2="188" stroke="${ink}" stroke-width="0.6"/>
  <line x1="68" y1="215" x2="748" y2="215" stroke="${ink}" stroke-width="0.6"/>
  <!-- Stamp impression hint -->
  <ellipse cx="400" cy="155" rx="70" ry="30" fill="none" stroke="${ink}" stroke-width="0.6" stroke-dasharray="4 2" opacity="0.4"/>
  <text x="400" y="160" font-size="8" fill="${ink}" font-family="sans-serif" text-anchor="middle" opacity="0.5">BANK STAMP</text>
  <!-- Rule above MICR -->
  <line x1="8" y1="256" x2="752" y2="256" stroke="${ink}" stroke-width="0.6"/>
  <!-- MICR band -->
  <rect x="0" y="258" width="760" height="62" fill="${micrBg}"/>
  <line x1="0" y1="258" x2="760" y2="258" stroke="${ink}" stroke-width="0.5"/>
  <text x="18" y="295" font-size="13.5" fill="${ink}" font-family="'Courier New',monospace" letter-spacing="2.5">${micr}</text>
</svg>`
}

function makePlaceholderDataUrl(viewKey, fields) {
  let svg
  if (viewKey === 'BBB') {
    svg = _svgBack(fields)
  } else {
    svg = _svgFront(fields, viewKey === 'BFG')
  }
  // btoa with UTF-8 safe encoding
  const encoded = btoa(unescape(encodeURIComponent(svg)))
  return `data:image/svg+xml;base64,${encoded}`
}

// ── IQA badge ─────────────────────────────────────────────────────────────────

function IQABadge({ score, isDark }) {
  if (score == null) return null
  const pct = Math.round(score * 100)
  const color = pct >= 90
    ? 'bg-emerald-500/80 text-white'
    : pct >= 70
    ? 'bg-amber-400/80 text-black'
    : 'bg-red-500/80 text-white'
  return (
    <span className={`absolute top-2 right-2 text-[10px] font-bold px-1.5 py-0.5 rounded ${color}`}>
      IQA {pct}%
    </span>
  )
}

// ── Lightbox ──────────────────────────────────────────────────────────────────

function Lightbox({ src, label, title, onClose, isDark }) {
  useEffect(() => {
    const fn = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-black/90 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 flex items-center justify-between px-6 py-3 bg-black/60">
        <div className="text-xs text-slate-300">
          <span className="text-white font-semibold">{label}</span>
          {title && <span className="ml-2 text-slate-500 font-mono">{title}</span>}
        </div>
        <div className="flex items-center gap-4">
          <a
            href={src}
            download
            onClick={(e) => e.stopPropagation()}
            className="text-[11px] text-slate-400 hover:text-white transition-colors px-3 py-1 rounded border border-white/20 hover:border-white/40"
          >
            ↓ Download
          </a>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-lg leading-none"
          >
            ✕
          </button>
        </div>
      </div>
      {/* Image */}
      <img
        src={src}
        alt={label}
        onClick={(e) => e.stopPropagation()}
        className="max-w-[90vw] max-h-[80vh] object-contain rounded shadow-2xl border border-white/10"
        style={{ imageRendering: 'crisp-edges' }}
      />
      <div className="absolute bottom-4 text-[11px] text-slate-500">Click anywhere or press Esc to close</div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function ChequeImageViewer({
  views,
  fields = {},
  isDark = true,
  compact = false,
  title = '',
}) {
  const [activeKey, setActiveKey]   = useState(views?.[0]?.key ?? 'BFB')
  const [lightbox, setLightbox]     = useState(null)

  const activeView = views?.find(v => v.key === activeKey) ?? views?.[0]

  const src = activeView?.url ?? makePlaceholderDataUrl(activeView?.key, fields)

  const openLightbox = useCallback(() => {
    setLightbox({ src, label: activeView?.label ?? '', title })
  }, [src, activeView, title])

  if (!views?.length) return null

  const th = {
    wrap:   isDark ? 'bg-navy-900/60 border-white/10' : 'bg-slate-50 border-slate-200',
    tabs:   isDark ? 'bg-white/5 border-white/8'      : 'bg-slate-100 border-slate-200',
    tabA:   isDark ? 'bg-white/10 text-white border-white/20'    : 'bg-white text-slate-900 border-slate-300 shadow-sm',
    tabI:   isDark ? 'text-slate-500 hover:text-slate-300'        : 'text-slate-400 hover:text-slate-700',
    imgWrap: isDark ? 'bg-black/40' : 'bg-white',
    footer: isDark ? 'border-white/8 text-slate-600' : 'border-slate-200 text-slate-400',
    badge:  isDark ? 'bg-white/5 text-slate-500 border-white/10' : 'bg-slate-100 text-slate-500 border-slate-200',
    mock:   isDark ? 'text-slate-600' : 'text-slate-400',
  }

  const isPlaceholder = !activeView?.url

  return (
    <>
      <div className={`rounded-xl border overflow-hidden ${th.wrap} ${compact ? '' : ''}`}>
        {/* View tab switcher */}
        <div className={`flex items-center gap-1 px-2 py-1.5 border-b ${th.tabs}`}>
          {views.map(v => (
            <button
              key={v.key}
              onClick={() => setActiveKey(v.key)}
              className={`px-3 py-1 text-[11px] font-medium rounded border transition-all ${
                v.key === activeKey ? th.tabA : th.tabI + ' border-transparent'
              }`}
            >
              {v.label}
            </button>
          ))}
          <div className="flex-1" />
          {/* IQA badge in tab bar */}
          {activeView?.iqaScore != null && (() => {
            const pct = Math.round(activeView.iqaScore * 100)
            const cls = pct >= 90
              ? (isDark ? 'text-emerald-400 border-emerald-400/30' : 'text-emerald-600 border-emerald-300')
              : pct >= 70
              ? (isDark ? 'text-amber-400 border-amber-400/30' : 'text-amber-600 border-amber-300')
              : (isDark ? 'text-red-400 border-red-400/30' : 'text-red-600 border-red-300')
            return (
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${cls}`}>
                IQA {pct}%
              </span>
            )
          })()}
          {/* Expand button */}
          <button
            onClick={openLightbox}
            title="View full screen"
            className={`ml-1 px-2 py-1 text-[11px] rounded border transition-colors ${th.badge} hover:opacity-80`}
          >
            ⤢
          </button>
          {/* Download */}
          <a
            href={src}
            download={`${title ? title + '_' : ''}${activeView?.key ?? 'cheque'}.${isPlaceholder ? 'svg' : 'jpg'}`}
            className={`ml-0.5 px-2 py-1 text-[11px] rounded border transition-colors ${th.badge} hover:opacity-80`}
            title="Download image"
          >
            ↓
          </a>
        </div>

        {/* Image area */}
        <div
          className={`relative overflow-hidden cursor-zoom-in ${th.imgWrap} ${compact ? 'h-[160px]' : 'h-[260px]'}`}
          onClick={openLightbox}
        >
          <img
            key={src}
            src={src}
            alt={activeView?.label}
            className="w-full h-full object-contain transition-opacity duration-200"
            style={{ imageRendering: 'crisp-edges' }}
          />
          {/* "Mock" watermark when no real URL */}
          {isPlaceholder && (
            <div className={`absolute bottom-1 left-2 text-[9px] italic ${th.mock} pointer-events-none`}>
              preview — real image from scanner/MinIO
            </div>
          )}
        </div>

        {/* Footer: view metadata */}
        {!compact && (
          <div className={`flex items-center gap-3 px-3 py-1.5 border-t text-[10px] ${th.footer}`}>
            <span className="font-mono">{activeView?.key}</span>
            <span>·</span>
            <span>{activeView?.label}</span>
            {activeView?.iqaScore != null && (
              <>
                <span>·</span>
                <span>IQA {Math.round(activeView.iqaScore * 100)}%</span>
              </>
            )}
            <span className="flex-1" />
            <span className="italic">{isPlaceholder ? 'No image URL — showing SVG preview' : 'Live scan image'}</span>
          </div>
        )}
      </div>

      {lightbox && (
        <Lightbox
          src={lightbox.src}
          label={lightbox.label}
          title={lightbox.title}
          isDark={isDark}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  )
}
