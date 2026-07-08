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
  const payee    = fields.payee          || 'Sample Payee Name'
  const date     = fields.date           || '07/07/2026'
  const figStr   = (fields.amount_figures || '₹50,000').replace('₹', '').trim()
  const words    = fields.amount_words   || 'Fifty Thousand Only'
  const micr     = fields.micr           || '000012340050000012100000000005000123456789'
  const altered  = fields.alterations    || false

  const bg      = gray ? '#f0f0f0' : '#ffffff'
  const ink     = '#111111'
  const light   = gray ? '#666666' : '#444444'
  const micrBg  = gray ? '#e4e4e4' : '#f2f2f2'
  const altClr  = altered ? '#cc2200' : ink

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 320">
  <rect width="760" height="320" fill="${bg}"/>
  <rect x="2" y="2" width="756" height="316" rx="3" fill="none" stroke="${ink}" stroke-width="1.5"/>
  <!-- Crossing lines -->
  <line x1="15" y1="2" x2="15" y2="80" stroke="${ink}" stroke-width="1.2"/>
  <line x1="47" y1="2" x2="47" y2="80" stroke="${ink}" stroke-width="1.2"/>
  <text x="18" y="54" font-size="7.5" fill="${ink}" font-family="sans-serif" transform="rotate(0)">A/C</text>
  <text x="16" y="65" font-size="7.5" fill="${ink}" font-family="sans-serif">PAYEE</text>
  <!-- Bank header -->
  <text x="58" y="23" font-size="13" font-weight="bold" fill="${ink}" font-family="sans-serif">SARASWAT CO-OP. BANK LTD.</text>
  <text x="58" y="38" font-size="8.5" fill="${light}" font-family="sans-serif">Fort Branch, Mumbai — 400 001  |  CTS-2010 Compliant</text>
  <!-- Date -->
  <text x="596" y="20" font-size="9" fill="${light}" font-family="sans-serif">Date</text>
  <line x1="620" y1="20" x2="748" y2="20" stroke="${ink}" stroke-width="0.7"/>
  <text x="622" y="19" font-size="11" fill="${ink}" font-family="sans-serif">${date}</text>
  <!-- Cheque no -->
  <text x="596" y="38" font-size="9" fill="${light}" font-family="sans-serif">Chq: 100001</text>
  <!-- Divider under header -->
  <line x1="8" y1="52" x2="752" y2="52" stroke="${ink}" stroke-width="0.6"/>
  <!-- Pay to line -->
  <text x="14" y="80" font-size="10" fill="${light}" font-family="sans-serif">Pay</text>
  <line x1="40" y1="80" x2="586" y2="80" stroke="${ink}" stroke-width="0.7"/>
  <text x="42" y="79" font-size="12" fill="${ink}" font-family="sans-serif">${payee}</text>
  <text x="590" y="79" font-size="9" fill="${ink}" font-family="sans-serif">or Bearer</text>
  <!-- Amount box -->
  <rect x="618" y="55" width="134" height="34" fill="none" stroke="${ink}" stroke-width="1.1"/>
  <text x="624" y="70" font-size="8" fill="${light}" font-family="sans-serif">₹</text>
  <text x="636" y="81" font-size="13" font-weight="bold" fill="${altClr}" font-family="monospace">${figStr}</text>
  ${altered ? `<line x1="618" y1="55" x2="752" y2="89" stroke="#cc2200" stroke-width="1.5" opacity="0.6"/>` : ''}
  <!-- Amount words -->
  <text x="14" y="114" font-size="10" fill="${light}" font-family="sans-serif">Rupees</text>
  <line x1="56" y1="114" x2="748" y2="114" stroke="${ink}" stroke-width="0.7"/>
  <text x="58" y="113" font-size="11" fill="${ink}" font-family="sans-serif">${words}</text>
  <line x1="14" y1="133" x2="748" y2="133" stroke="${ink}" stroke-width="0.7"/>
  <!-- Bank details -->
  <text x="14" y="160" font-size="8.5" fill="${light}" font-family="sans-serif">Branch: Fort Branch, Mumbai – 400 001</text>
  <text x="14" y="173" font-size="8.5" fill="${light}" font-family="sans-serif">IFSC: SRCB0000001   MICR: 400015002</text>
  <!-- Sig line -->
  <line x1="515" y1="218" x2="748" y2="218" stroke="${ink}" stroke-width="0.7"/>
  <text x="578" y="230" font-size="8.5" fill="${light}" font-family="sans-serif">Authorised Signatory</text>
  <!-- Above-MICR rule -->
  <line x1="8" y1="256" x2="752" y2="256" stroke="${ink}" stroke-width="0.6"/>
  <!-- MICR band -->
  <rect x="0" y="258" width="760" height="62" fill="${micrBg}"/>
  <line x1="0" y1="258" x2="760" y2="258" stroke="${ink}" stroke-width="0.5"/>
  <text x="18" y="295" font-size="13.5" fill="${ink}" font-family="'Courier New',monospace" letter-spacing="2.5">${micr}</text>
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
