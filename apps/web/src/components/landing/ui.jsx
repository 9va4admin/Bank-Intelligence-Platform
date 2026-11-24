import { useId } from 'react'

// Small visual kit for the landing page: colour tokens, line icons, double-circle bullets and coloured dashed separators.
export const ACCENTS = { teal: '#1D9E75', sky: '#378ADD', amber: '#E0A030', violet: '#7C5CD6', rose: '#D6586B' }
export const ACCENT_ORDER = ['teal', 'sky', 'violet', 'amber', 'rose']

const PATHS = {
  layers: 'M12 3l9 5-9 5-9-5 9-5z M3 13l9 5 9-5',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z M9 12l2 2 4-4',
  clock: 'M12 21a9 9 0 100-18 9 9 0 000 18z M12 7v5l3 2',
  doc: 'M7 3h7l4 4v14H7z M14 3v4h4 M9 12h6 M9 16h6',
  users: 'M9 11a3 3 0 100-6 3 3 0 000 6z M3 20c0-3 3-5 6-5s6 2 6 5 M17 11a3 3 0 100-6 M21 20c0-2.5-2-4.5-4.5-5',
  chart: 'M4 20V10 M10 20V4 M16 20v-7 M22 20H2',
  bolt: 'M13 2L4 14h7l-1 8 9-12h-7l1-8z',
  link: 'M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1 M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1',
  search: 'M11 17a6 6 0 100-12 6 6 0 000 12z M16 16l5 5',
  gift: 'M4 10h16v10H4z M2 7h20v3H2z M12 7v13 M12 7c-2 0-4-1-4-3s3-2 4 3 M12 7c2 0 4-1 4-3s-3-2-4 3',
  database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6 M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  check: 'M5 13l4 4L19 7',
  down: 'M12 5v14 M6 13l6 6 6-6',
  idcard: 'M3 6h18v12H3z M8 12a2 2 0 100-4 2 2 0 000 4z M13 10h5 M13 14h5 M5.5 16c.5-1.5 5-1.5 5 0',
  scale: 'M12 3v18 M6 21h12 M5 7h14 M5 7l-3 7a3.5 3.5 0 007 0L5 7z M19 7l-3 7a3.5 3.5 0 007 0l-3-7z',
  server: 'M4 5h16v6H4z M4 13h16v6H4z M8 8h.01 M8 16h.01',
  bank: 'M3 10l9-6 9 6 M5 10v8 M9 10v8 M15 10v8 M19 10v8 M3 20h18',
  cheque: 'M3 6h18v12H3z M6 10h6 M6 14h4 M15 14h3',
}

export function Icon({ name, color = ACCENTS.teal, size = 22, className = '' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {(PATHS[name] || PATHS.layers).split(' M').map((d, i) => <path key={i} d={(i ? 'M' : '') + d} />)}
    </svg>
  )
}

// A round tile holding an icon, tinted with the accent colour.
export function IconTile({ name, accent = 'teal', size = 40 }) {
  const c = ACCENTS[accent] || accent
  return (
    <span className="inline-flex items-center justify-center rounded-xl flex-shrink-0" style={{ width: size, height: size, background: `${c}1A`, border: `1px solid ${c}33` }}>
      <Icon name={name} color={c} size={Math.round(size * 0.52)} />
    </span>
  )
}

// A ring with a filled dot inside: the "double circle" bullet.
export function DoubleBullet({ accent = 'teal', size = 16 }) {
  const c = ACCENTS[accent] || accent
  return (
    <span aria-hidden="true" className="inline-flex items-center justify-center rounded-full flex-shrink-0" style={{ width: size, height: size, border: `2px solid ${c}`, marginTop: 2 }}>
      <span className="rounded-full" style={{ width: size - 9, height: size - 9, background: c }} />
    </span>
  )
}

// A dashed line that shifts through the brand colours.
export function DashedDivider({ className = '' }) {
  const id = useId().replace(/:/g, '')
  return (
    <div className={`px-6 ${className}`} role="separator"><div className="max-w-6xl mx-auto">
      <svg width="100%" height="4" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor={ACCENTS.teal} />
            <stop offset="0.35" stopColor={ACCENTS.sky} />
            <stop offset="0.65" stopColor={ACCENTS.violet} />
            <stop offset="1" stopColor={ACCENTS.amber} />
          </linearGradient>
        </defs>
        <line x1="0" y1="2" x2="100%" y2="2" stroke={`url(#${id})`} strokeWidth="2" strokeDasharray="10 8" strokeLinecap="round" />
      </svg>
    </div></div>
  )
}
