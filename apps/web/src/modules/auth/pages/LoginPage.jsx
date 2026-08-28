/**
 * LoginPage — full-bleed animated HUD login with 3-step auth flow.
 *
 * Flow: password → MFA_REQUIRED → verify (existing users)
 *             └→ MFA_ENROL_REQUIRED → beginEnrol → enrol + QR (first login)
 *
 * APIs:
 *   POST /v1/auth/login            → half-session cookie + outcome
 *   POST /v1/auth/mfa/verify       → full session (enrolled users)
 *   POST /v1/auth/mfa/enrol/begin  → { secret, otpauth_uri }
 *   POST /v1/auth/mfa/enrol/confirm→ full session (first login)
 *
 * Session token rides in an httpOnly cookie set by the server — never
 * visible here. CSRF token from body is stored in sessionStorage.
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { useAuth } from '../../../shared/context/AuthContext'
import './LoginPage.css'

/* ── API helper ──────────────────────────────────────────── */

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = await res.json() } catch { /* empty body */ }
  return { ok: res.ok, status: res.status, data }
}

function groupSecret(secret) {
  return (secret || '').replace(/(.{4})/g, '$1 ').trim()
}

/* ── Stat cycling data ───────────────────────────────────── */

const STATS = [
  { num: '<600ms',  desc: 'AI agent decision — per cheque, every cheque' },
  { num: '0.000%',  desc: 'IET breach rate — RBI mandate, zero always' },
  { num: '500',     desc: 'Parallel AI agents per inward batch' },
  { num: '₹71L Cr', desc: 'CTS clearing market · FY25 · 609M cheques/year' },
]

/* ── Inline style objects (complex CSS that Tailwind can't express) ── */

const S = {
  hud: {
    position: 'absolute', top: '50%', left: '44%',
    transform: 'translate(-50%, -50%)',
    width: 680, height: 680, pointerEvents: 'none',
  },
  hudGlow: {
    position: 'absolute', inset: 0, borderRadius: '50%',
    background: 'radial-gradient(circle at 50% 50%, rgba(245,200,66,0.055) 0%, rgba(245,200,66,0.018) 35%, transparent 68%)',
  },
  hudSweep: {
    position: 'absolute', inset: 0, borderRadius: '50%',
    background: 'conic-gradient(from 0deg at 50% 50%, rgba(245,200,66,0) 0deg, rgba(245,200,66,0) 15deg, rgba(245,200,66,0.28) 52deg, rgba(245,200,66,0.07) 80deg, rgba(245,200,66,0) 105deg, rgba(245,200,66,0) 360deg)',
  },
  // Shadow layers — siblings of the frame, so backdrop-filter on the glass still works
  shadow1: {
    position: 'absolute', inset: 0, zIndex: -1, pointerEvents: 'none',
    background: 'rgba(0,0,0,0.75)',
    clipPath: 'polygon(0 0, calc(100% - 38px) 0, 100% 38px, 100% 100%, 0 100%)',
    filter: 'blur(22px)',
    transform: 'translate(7px, 14px)',
  },
  shadow2: {
    position: 'absolute', inset: -16, zIndex: -2, pointerEvents: 'none',
    background: 'rgba(0,0,0,0.35)',
    filter: 'blur(42px)',
    transform: 'translate(2px, 10px)',
  },
  // Chamfered frame — 1px bevel border via padding + gradient background
  frame: {
    padding: 1,
    background: 'linear-gradient(148deg, rgba(255,255,255,0.65) 0%, rgba(245,200,66,0.55) 6%, rgba(245,200,66,0.22) 35%, rgba(245,200,66,0.08) 65%, rgba(8,4,0,0.55) 100%)',
    clipPath: 'polygon(0 0, calc(100% - 38px) 0, 100% 38px, 100% 100%, 0 100%)',
    position: 'relative',
  },
  // Glass interior — directional gradient reinforces the 3D raised surface
  glass: {
    clipPath: 'polygon(0 0, calc(100% - 38px) 0, 100% 38px, 100% 100%, 0 100%)',
    padding: '44px 40px 36px',
    background: 'linear-gradient(148deg, rgba(12,22,62,0.82) 0%, rgba(4,9,28,0.78) 100%)',
    backdropFilter: 'blur(24px) saturate(1.3)',
    WebkitBackdropFilter: 'blur(24px) saturate(1.3)',
    position: 'relative',
  },
  // Bevel highlight: 1px bright line on top/left interior edges
  edgeTop: {
    position: 'absolute', top: 1, left: 1, right: 0, height: 1,
    background: 'linear-gradient(90deg, rgba(255,255,255,0.50) 0%, rgba(255,255,255,0.18) 55%, rgba(245,200,66,0.20) 100%)',
    pointerEvents: 'none', zIndex: 20,
  },
  edgeLeft: {
    position: 'absolute', top: 1, left: 1, bottom: 0, width: 1,
    background: 'linear-gradient(180deg, rgba(255,255,255,0.38) 0%, rgba(255,255,255,0.06) 45%, transparent 100%)',
    pointerEvents: 'none', zIndex: 20,
  },
  // Chamfer endpoint dots
  chfA: { position: 'absolute', top: 0, right: 38, transform: 'translate(50%, -50%)' },
  chfB: { position: 'absolute', top: 38, right: 0, transform: 'translate(50%, -50%)' },
  // Error banner
  errBanner: {
    borderLeft: '2px solid rgba(248,113,113,0.8)',
    background: 'rgba(248,113,113,0.08)',
    padding: '10px 14px',
    marginBottom: 18,
    fontSize: 13,
    color: '#f87171',
    lineHeight: 1.5,
  },
  // QR block
  qrWrap: {
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10,
    padding: 20,
    border: '1px solid rgba(255,255,255,0.08)',
    background: 'rgba(255,255,255,0.03)',
    marginBottom: 18,
  },
  qrInner: { padding: 14, background: '#fff' }, // white bg required for QR scan
  // Secret key box
  secretBox: {
    border: '1px solid rgba(255,255,255,0.08)',
    background: 'rgba(255,255,255,0.03)',
    padding: '11px 13px',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 12.5,
    color: '#f5c842',
    wordBreak: 'break-all',
    letterSpacing: '0.07em',
    marginBottom: 16,
  },
  // Footer inside glass panel
  panelFoot: {
    marginTop: 24,
    paddingTop: 18,
    borderTop: '1px solid rgba(255,255,255,0.07)',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 9.5,
    color: 'rgba(255,255,255,0.18)',
    textAlign: 'center',
    letterSpacing: '0.05em',
    lineHeight: 1.7,
  },
}

/* ── Component ───────────────────────────────────────────── */

export default function LoginPage() {
  const { refresh } = useAuth()
  const navigate = useNavigate()

  const [step, setStep]     = useState('password') // 'password' | 'verify' | 'enrol'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode]     = useState('')
  const [enrol, setEnrol]   = useState(null)       // { secret, otpauth_uri }
  const [error, setError]   = useState('')
  const [busy, setBusy]     = useState(false)

  // Cycling hero stat
  const [statIdx, setStatIdx]       = useState(0)
  const [statVisible, setStatVisible] = useState(true)

  useEffect(() => {
    const boot = setTimeout(() => {
      const iv = setInterval(() => {
        setStatVisible(false)
        setTimeout(() => {
          setStatIdx(i => (i + 1) % STATS.length)
          setStatVisible(true)
        }, 360)
      }, 3200)
      return () => clearInterval(iv)
    }, 2400)
    return () => clearTimeout(boot)
  }, [])

  /* ── Auth handlers (unchanged from original) ─────────── */

  async function submitPassword(e) {
    e.preventDefault()
    setError(''); setBusy(true)
    const { ok, status, data } = await postJSON('/v1/auth/login', { username, password })
    setBusy(false)
    if (ok && data) {
      if (data.csrf_token) sessionStorage.setItem('astra-csrf', data.csrf_token)
      if (data.outcome === 'MFA_REQUIRED') { setCode(''); setStep('verify') }
      else { beginEnrol() }
      return
    }
    if (status === 423)
      setError('Account locked after repeated failures. Contact your administrator.')
    else
      setError('Invalid username or password.')
  }

  async function beginEnrol() {
    setError(''); setBusy(true)
    const { ok, data } = await postJSON('/v1/auth/mfa/enrol/begin')
    setBusy(false)
    if (ok && data) { setEnrol(data); setCode(''); setStep('enrol') }
    else setError('Could not start MFA setup. Please try again.')
  }

  async function submitVerify(e) {
    e.preventDefault()
    setError(''); setBusy(true)
    const { ok, data } = await postJSON('/v1/auth/mfa/verify', { code })
    setBusy(false)
    if (ok) finish(data)
    else setError('Invalid code. Try the current 6-digit code from your app.')
  }

  async function submitEnrolConfirm(e) {
    e.preventDefault()
    setError(''); setBusy(true)
    const { ok, data } = await postJSON('/v1/auth/mfa/enrol/confirm', { code })
    setBusy(false)
    if (ok) finish(data)
    else setError('That code did not match. Scan the key again and enter the current code.')
  }

  async function finish(data) {
    if (data?.csrf_token) sessionStorage.setItem('astra-csrf', data.csrf_token)
    await refresh()
    navigate('/cts/ops-dashboard')
  }

  /* ── Stat fade style ──────────────────────────────────── */

  const numStyle = {
    fontFamily: "'Syne', sans-serif",
    fontSize: 76, fontWeight: 800, lineHeight: 0.92,
    color: '#f5c842', letterSpacing: '-0.045em',
    fontVariantNumeric: 'tabular-nums',
    transition: 'opacity 0.38s ease, transform 0.38s ease',
    opacity: statVisible ? 1 : 0,
    transform: statVisible ? 'translateY(0)' : 'translateY(-10px)',
  }

  const descStyle = {
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 12, color: 'rgba(255,255,255,0.38)',
    letterSpacing: '0.025em', marginTop: 14, lineHeight: 1.5,
    transition: 'opacity 0.38s ease',
    opacity: statVisible ? 1 : 0,
  }

  /* ── Step eyebrow / title / subtitle ─────────────────── */

  const EYE   = { password: 'Operator Access',   verify: 'Two-Factor Auth',        enrol: 'First Login Setup' }
  const TITLE = { password: 'Sign in',            verify: 'Enter your code',        enrol: 'Set up authenticator' }
  const SUB   = {
    password: 'Use your ASTRA credentials issued by your bank IT admin.',
    verify:   'Open your authenticator and enter the current 6-digit code.',
    enrol:    'MFA is mandatory for all ASTRA operators. Scan the QR code with Authy or Google Authenticator.',
  }

  /* ── Render ───────────────────────────────────────────── */

  return (
    <div style={{ minHeight: '100vh', background: '#03061a' }}>

      {/* Fixed animated canvas */}
      <div className="lp-canvas">
        <div style={S.hud}>
          <div className="lp-hud-glow" style={S.hudGlow} />
          <div className="lp-hud-sweep" style={S.hudSweep} />
          <svg style={{ position:'absolute', inset:0, width:'100%', height:'100%' }}
               viewBox="0 0 680 680" xmlns="http://www.w3.org/2000/svg">
            {/* Concentric rings */}
            <circle className="lp-ring-1" cx="340" cy="340" r="326" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="1"/>
            <circle className="lp-ring-2" cx="340" cy="340" r="258" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="1"/>
            <circle className="lp-ring-3" cx="340" cy="340" r="182" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="1"/>
            <circle className="lp-ring-4" cx="340" cy="340"  r="96" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="1"/>
            {/* Crosshairs */}
            <line x1="0" y1="340" x2="680" y2="340" stroke="rgba(255,255,255,0.038)" strokeWidth="1"/>
            <line x1="340" y1="0" x2="340" y2="680" stroke="rgba(255,255,255,0.038)" strokeWidth="1"/>
            <line x1="80" y1="80" x2="600" y2="600"  stroke="rgba(255,255,255,0.018)" strokeWidth="1"/>
            <line x1="600" y1="80" x2="80" y2="600"  stroke="rgba(255,255,255,0.018)" strokeWidth="1"/>
            {/* Tick marks */}
            <line x1="340" y1="5"   x2="340" y2="24"  stroke="rgba(245,200,66,0.4)" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="656" y1="340" x2="675" y2="340" stroke="rgba(245,200,66,0.4)" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="340" y1="656" x2="340" y2="675" stroke="rgba(245,200,66,0.4)" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="5"   y1="340" x2="24"  y2="340" stroke="rgba(245,200,66,0.4)" strokeWidth="1.5" strokeLinecap="round"/>
            {/* Scan dots */}
            <circle className="lp-sdot-1" cx="340" cy="14"  r="3.5" fill="#f5c842"/>
            <circle className="lp-sdot-2" cx="666" cy="340" r="3.5" fill="#f5c842"/>
            <circle className="lp-sdot-3" cx="340" cy="666" r="3.5" fill="#f5c842"/>
            <circle className="lp-sdot-4" cx="14"  cy="340" r="3.5" fill="#f5c842"/>
            {/* Centre */}
            <circle cx="340" cy="340" r="5.5" fill="#f5c842" opacity="0.9"/>
          </svg>
        </div>
      </div>

      {/* Page content layer */}
      <div className="lp-page">

        {/* ── Left: product info ───────────────────── */}
        <div className="lp-info">

          {/* Logo */}
          <div className="lp-anim-logo" style={{ display:'flex', alignItems:'center', gap:11 }}>
            <div style={{
              width:38, height:38, background:'#f5c842',
              display:'grid', placeItems:'center', flexShrink:0,
            }}>
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                <path d="M10 2L18 17H2L10 2Z" stroke="#03061a" strokeWidth="2.5"/>
                <line x1="6.5" y1="13" x2="13.5" y2="13" stroke="#03061a" strokeWidth="2" strokeLinecap="round"/>
              </svg>
            </div>
            <div>
              <div style={{ fontFamily:"'Syne',sans-serif", fontSize:20, fontWeight:800, color:'#fff', letterSpacing:'-0.02em' }}>
                ASTRA
              </div>
              <div style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:9.5, color:'rgba(255,255,255,0.28)', letterSpacing:'0.05em', marginTop:2 }}>
                Precision Banking. Zero Compromise.
              </div>
            </div>
          </div>

          {/* Hero area */}
          <div style={{ marginTop:'auto', paddingBottom:4 }}>

            <div className="lp-anim-tag" style={{
              fontFamily:"'JetBrains Mono',monospace", fontSize:10,
              letterSpacing:'0.14em', textTransform:'uppercase', color:'#f5c842', marginBottom:18,
            }}>
              AI-Native Cheque Clearing
            </div>

            {/* Cycling stat number */}
            <div className="lp-anim-num" style={numStyle}>
              {STATS[statIdx].num}
            </div>

            {/* Cycling stat description */}
            <div style={descStyle}>
              {STATS[statIdx].desc}
            </div>

            {/* Pillars */}
            <div className="lp-anim-pillars lp-pillars-block" style={{ marginTop:40, display:'flex', flexDirection:'column', gap:16 }}>
              {[
                { title:'500 parallel agents per batch',   body:'One AI agent per inward cheque · OCR · Signature · Fraud · SHAP' },
                { title:'Zero cloud. 100% on-premises.',   body:'Data localisation enforced · No vendor access · Air-gapped DC3 backup' },
                { title:'Cryptographic audit trail',       body:'Immudb Merkle tree · HSM-signed · WORM · 10-year legal hold' },
              ].map(p => (
                <div key={p.title} style={{ display:'flex', gap:12, alignItems:'flex-start' }}>
                  <div style={{
                    width:2, height:30, flexShrink:0, marginTop:3,
                    background:'linear-gradient(to bottom, #f5c842, transparent)',
                    opacity:0.3,
                  }}/>
                  <div>
                    <div style={{ fontSize:12, fontWeight:600, color:'rgba(255,255,255,0.65)', lineHeight:1.3 }}>{p.title}</div>
                    <div style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:10, color:'rgba(255,255,255,0.25)', letterSpacing:'0.02em', lineHeight:1.5, marginTop:1 }}>{p.body}</div>
                  </div>
                </div>
              ))}
            </div>

            {/* RBI mandate badge */}
            <div className="lp-anim-mandate" style={{ marginTop:32, display:'inline-flex', alignItems:'center', gap:9 }}>
              <div className="lp-anim-pulse" style={{ width:7, height:7, borderRadius:'50%', background:'#f5c842', flexShrink:0 }}/>
              <div style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:10, color:'rgba(245,200,66,0.5)', letterSpacing:'0.05em' }}>
                RBI T+3 IET Mandate · Jan 2026 · Enforced by architecture
              </div>
            </div>

          </div>
        </div>

        {/* ── Right: 3D embossed glass panel ──────── */}
        <div className="lp-outer">

          {/* Depth shadows — siblings of frame, so backdrop-filter on glass still works */}
          <div style={S.shadow1} />
          <div style={S.shadow2} />

          {/* Chamfered border frame */}
          <div style={S.frame}>

            {/* Glass interior */}
            <div style={S.glass}>

              {/* Bevel highlights — complete the 3D raised-surface illusion */}
              <span style={S.edgeTop} />
              <span style={S.edgeLeft} />

              {/* Step eyebrow / title / subtitle */}
              <div style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:9.5, textTransform:'uppercase', letterSpacing:'0.14em', color:'rgba(245,200,66,0.55)', marginBottom:10 }}>
                {EYE[step]}
              </div>
              <h2 style={{ fontFamily:"'Syne',sans-serif", fontSize:26, fontWeight:700, color:'#fff', letterSpacing:'-0.025em', lineHeight:1.1, marginBottom:8, margin:'0 0 8px' }}>
                {TITLE[step]}
              </h2>
              <div style={{ fontSize:13, color:'rgba(255,255,255,0.35)', lineHeight:1.55, marginBottom:28 }}>
                {SUB[step]}
              </div>

              {/* Error banner */}
              {error && <div style={S.errBanner}>{error}</div>}

              {/* ── Step: password ─────────────────────── */}
              {step === 'password' && (
                <form onSubmit={submitPassword} style={{ display:'flex', flexDirection:'column', gap:0 }}>
                  <div style={{ marginBottom:16 }}>
                    <label style={{ display:'block', fontSize:11.5, fontWeight:500, color:'rgba(255,255,255,0.38)', marginBottom:7, letterSpacing:'0.01em' }}>
                      Username
                    </label>
                    <input
                      className="lp-input"
                      autoFocus
                      type="text"
                      value={username}
                      onChange={e => setUsername(e.target.value)}
                      autoComplete="username"
                      required
                      placeholder="operator.name"
                    />
                  </div>
                  <div style={{ marginBottom:20 }}>
                    <label style={{ display:'block', fontSize:11.5, fontWeight:500, color:'rgba(255,255,255,0.38)', marginBottom:7, letterSpacing:'0.01em' }}>
                      Password
                    </label>
                    <input
                      className="lp-input"
                      type="password"
                      value={password}
                      onChange={e => setPassword(e.target.value)}
                      autoComplete="current-password"
                      required
                      placeholder="••••••••"
                    />
                  </div>
                  <button type="submit" className="lp-btn" disabled={busy}>
                    {busy ? 'Signing in…' : 'Sign in →'}
                  </button>
                </form>
              )}

              {/* ── Step: verify MFA ───────────────────── */}
              {step === 'verify' && (
                <form onSubmit={submitVerify}>
                  <div style={{ marginBottom:20 }}>
                    <input
                      className="lp-input lp-totp"
                      autoFocus
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={6}
                      value={code}
                      onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="000000"
                    />
                  </div>
                  <button
                    type="submit"
                    className="lp-btn"
                    disabled={busy || code.length !== 6}
                  >
                    {busy ? 'Verifying…' : 'Verify →'}
                  </button>
                  <button
                    type="button"
                    className="lp-btn-ghost"
                    onClick={() => { setStep('password'); setError('') }}
                  >
                    ← Back to sign in
                  </button>
                </form>
              )}

              {/* ── Step: enrol (first login) ───────────── */}
              {step === 'enrol' && enrol && (
                <form onSubmit={submitEnrolConfirm}>

                  {/* QR code — white background is required for scanner apps */}
                  <div style={S.qrWrap}>
                    <div style={S.qrInner}>
                      <QRCodeSVG value={enrol.otpauth_uri} size={156} />
                    </div>
                    <div style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:10, color:'rgba(255,255,255,0.22)', textAlign:'center' }}>
                      Google Authenticator · Authy · 1Password
                    </div>
                  </div>

                  {/* Manual key */}
                  <div style={{ fontSize:11, fontWeight:500, color:'rgba(255,255,255,0.35)', marginBottom:6 }}>
                    Can't scan? Enter this key manually
                  </div>
                  <div style={S.secretBox}>{groupSecret(enrol.secret)}</div>
                  <div style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:9.5, color:'rgba(255,255,255,0.2)', marginBottom:20 }}>
                    Issuer: ASTRA · TOTP · 6 digits · 30 s
                  </div>

                  {/* Confirm code */}
                  <div style={{ borderTop:'1px solid rgba(255,255,255,0.07)', paddingTop:18, marginBottom:16 }}>
                    <label style={{ display:'block', fontSize:11.5, fontWeight:500, color:'rgba(255,255,255,0.38)', marginBottom:7 }}>
                      Confirm the current 6-digit code
                    </label>
                    <input
                      className="lp-input lp-totp"
                      autoFocus
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={6}
                      value={code}
                      onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                      placeholder="000000"
                    />
                  </div>

                  <button
                    type="submit"
                    className="lp-btn"
                    disabled={busy || code.length !== 6}
                  >
                    {busy ? 'Confirming…' : 'Confirm & finish →'}
                  </button>
                </form>
              )}

              {/* Footer */}
              <div style={S.panelFoot}>
                Authorised access only · All activity is audited<br/>
                mTLS enforced · httpOnly session cookie
              </div>

            </div>{/* /glass */}

            {/* Corner brackets + chamfer dots — after glass in DOM so they paint on top */}
            <span className="lp-brk lp-brk-tl" />
            <span className="lp-brk lp-brk-br" />
            <span className="lp-chf" style={S.chfA} />
            <span className="lp-chf" style={S.chfB} />
            <span className="lp-chf-lbl">Auth.Node</span>

          </div>{/* /frame */}
        </div>{/* /outer */}

      </div>{/* /page */}
    </div>
  )
}
