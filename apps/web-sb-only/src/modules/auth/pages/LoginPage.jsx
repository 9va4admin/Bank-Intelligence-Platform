/**
 * LoginPage — ASTRA local authentication (password + mandatory TOTP MFA).
 *
 * Pre-auth page: no AppShell (no sidebar/topbar). Drives the real backend flow:
 *   POST /v1/auth/login            -> half-session cookie + outcome
 *   POST /v1/auth/mfa/verify       -> full session (enrolled users)
 *   POST /v1/auth/mfa/enrol/begin  -> QR secret (first login)
 *   POST /v1/auth/mfa/enrol/confirm-> full session (first login)
 *
 * The session token rides in an httpOnly cookie set by the server, so this code
 * never sees or stores it. The CSRF token from the body is stashed for the app's
 * state-changing calls. Dual-themed per .claude/rules/frontend.md.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useAuth } from '../../../shared/context/AuthContext'
import { msg } from '../../../shared/messages'

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'include', // send/receive the httpOnly session cookie
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

export default function LoginPage() {
  const { isDark, toggle } = useTheme()
  const { refresh } = useAuth()
  const navigate = useNavigate()

  const [step, setStep] = useState('password') // 'password' | 'verify' | 'enrol'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [enrol, setEnrol] = useState(null) // { secret, otpauth_uri }
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const th = {
    page:    isDark ? 'bg-[#020817]'          : 'bg-slate-100',
    card:    isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'            : 'text-slate-900',
    body:    isDark ? 'text-slate-300'        : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'        : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'        : 'text-slate-400',
    label:   isDark ? 'text-slate-400'        : 'text-slate-600',
    input:   isDark ? 'bg-navy-950 border-white/10 text-white placeholder-slate-600 focus:border-violet-500'
                    : 'bg-white border-slate-300 text-slate-900 placeholder-slate-400 focus:border-violet-500',
    key:     isDark ? 'bg-navy-950 border-white/10 text-violet-300' : 'bg-slate-50 border-slate-200 text-violet-700',
    divider: isDark ? 'border-white/10'       : 'border-slate-200',
    toggle:  isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600',
  }

  const btn = busy
    ? 'bg-violet-600/50 cursor-not-allowed'
    : 'bg-violet-600 hover:bg-violet-500'

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
    if (status === 423) setError(msg('UI_LOGINPAGE_ACCOUNT_LOCKED_AFTER_REPEATED_FAILED'))
    else setError(msg('UI_LOGINPAGE_INVALID_USERNAME_OR_PASSWORD_2'))
  }

  async function beginEnrol() {
    setError(''); setBusy(true)
    const { ok, data } = await postJSON('/v1/auth/mfa/enrol/begin')
    setBusy(false)
    if (ok && data) { setEnrol(data); setCode(''); setStep('enrol') }
    else setError(msg('UI_LOGINPAGE_COULD_NOT_START_MFA_SETUP_2'))
  }

  async function submitVerify(e) {
    e.preventDefault()
    setError(''); setBusy(true)
    const { ok, data } = await postJSON('/v1/auth/mfa/verify', { code })
    setBusy(false)
    if (ok) { finish(data) } else setError(msg('UI_LOGINPAGE_INVALID_CODE_TRY_THE_CURRENT_2'))
  }

  async function submitEnrolConfirm(e) {
    e.preventDefault()
    setError(''); setBusy(true)
    const { ok, data } = await postJSON('/v1/auth/mfa/enrol/confirm', { code })
    setBusy(false)
    if (ok) { finish(data) } else setError(msg('UI_LOGINPAGE_THAT_CODE_DID_NOT_MATCH_2'))
  }

  async function finish(data) {
    if (data && data.csrf_token) sessionStorage.setItem('astra-csrf', data.csrf_token)
    await refresh()          // re-resolve session so RequireAuth lets us in
    navigate('/cts/ops-dashboard')
  }

  return (
    <div className={`min-h-screen w-full flex items-center justify-center px-4 ${th.page}`}>
      <button onClick={toggle} className={`fixed top-5 right-5 text-lg ${th.toggle}`} aria-label={msg('UI_LOGINPAGE_TOGGLE_THEME')}>
        {isDark ? '◑' : '◐'}
      </button>

      <div className={`w-full max-w-[420px] rounded-2xl border shadow-xl ${th.card}`}>
        <div className="px-8 pt-8 pb-6">
          {/* Brand */}
          <div className="flex items-center gap-3 mb-1">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 grid place-items-center text-white font-bold text-lg">A</div>
            <div>
              <div className={`font-semibold tracking-tight leading-none ${th.heading}`}>{msg('UI_LOGINPAGE_ASTRA')}</div>
              <div className={`text-[11px] ${th.faint}`}>{msg('UI_LOGINPAGE_PRECISION_BANKING_ZERO_COMPROMISE_2')}</div>
            </div>
          </div>

          <h1 className={`mt-6 text-xl font-semibold ${th.heading}`}>
            {step === 'password' && msg('UI_LOGINPAGE_SIGN_IN_2')}
            {step === 'verify' && msg('UI_LOGINPAGE_TWO_FACTOR_AUTHENTICATION')}
            {step === 'enrol' && msg('UI_LOGINPAGE_SET_UP_TWO_FACTOR_AUTHENTICATION')}
          </h1>
          <p className={`mt-1 text-sm ${th.muted}`}>
            {step === 'password' && msg('UI_LOGINPAGE_USE_YOUR_ASTRA_OPERATOR_CREDENTIALS')}
            {step === 'verify' && msg('UI_LOGINPAGE_ENTER_THE_6_DIGIT_CODE')}
            {step === 'enrol' && msg('UI_LOGINPAGE_MFA_IS_REQUIRED_ADD_THIS')}
          </p>

          {error && (
            <div className="mt-4 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              {error}
            </div>
          )}

          {/* Step: password */}
          {step === 'password' && (
            <form onSubmit={submitPassword} className="mt-5 space-y-4">
              <div>
                <label className={`block text-xs font-medium mb-1.5 ${th.label}`}>{msg('UI_LOGINPAGE_USERNAME_2')}</label>
                <input
                  autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username" required
                  className={`w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors ${th.input}`}
                  placeholder="operator.name"
                />
              </div>
              <div>
                <label className={`block text-xs font-medium mb-1.5 ${th.label}`}>{msg('UI_LOGINPAGE_PASSWORD_2')}</label>
                <input
                  type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password" required
                  className={`w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors ${th.input}`}
                  placeholder="••••••••"
                />
              </div>
              <button type="submit" disabled={busy}
                className={`w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-colors ${btn}`}>
                {busy ? msg('UI_LOGINPAGE_SIGNING_IN_2') : msg('UI_LOGINPAGE_SIGN_IN_2')}
              </button>
            </form>
          )}

          {/* Step: verify */}
          {step === 'verify' && (
            <form onSubmit={submitVerify} className="mt-5 space-y-4">
              <input
                autoFocus inputMode="numeric" pattern="[0-9]*" maxLength={6}
                value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                className={`w-full rounded-lg border px-3 py-3 text-center text-2xl tracking-[0.5em] font-mono outline-none transition-colors ${th.input}`}
                placeholder="000000"
              />
              <button type="submit" disabled={busy || code.length !== 6}
                className={`w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-colors ${code.length === 6 && !busy ? 'bg-violet-600 hover:bg-violet-500' : 'bg-violet-600/40 cursor-not-allowed'}`}>
                {busy ? msg('UI_LOGINPAGE_VERIFYING_2') : msg('UI_LOGINPAGE_VERIFY_2')}
              </button>
              <button type="button" onClick={() => { setStep('password'); setError('') }}
                className={`w-full text-center text-xs ${th.muted} hover:underline`}>
               {msg('UI_LOGINPAGE_BACK_TO_SIGN_IN_2')}
              </button>
            </form>
          )}

          {/* Step: enrol */}
          {step === 'enrol' && enrol && (
            <form onSubmit={submitEnrolConfirm} className="mt-5 space-y-4">
              <div className="flex flex-col items-center gap-2">
                <div className="p-3 bg-white rounded-xl border border-slate-200">
                  <QRCodeSVG value={enrol.otpauth_uri} size={168} />
                </div>
                <div className={`text-[11px] ${th.faint}`}>{msg('UI_LOGINPAGE_SCAN_WITH_GOOGLE_AUTHENTICATOR_OR')}</div>
              </div>
              <div>
                <div className={`text-xs font-medium mb-1.5 ${th.label}`}>{msg('UI_LOGINPAGE_CAN_T_SCAN_ENTER_THIS')}</div>
                <div className={`rounded-lg border px-3 py-3 font-mono text-sm break-all ${th.key}`}>
                  {groupSecret(enrol.secret)}
                </div>
                <div className={`mt-1.5 text-[11px] ${th.faint}`}>
                 {msg('UI_LOGINPAGE_ISSUER_ASTRA_TOTP_6_DIGITS_2')}
                </div>
              </div>
              <div className={`border-t ${th.divider} pt-4`}>
                <label className={`block text-xs font-medium mb-1.5 ${th.label}`}>{msg('UI_LOGINPAGE_CONFIRM_THE_CURRENT_6_DIGIT_2')}</label>
                <input
                  autoFocus inputMode="numeric" pattern="[0-9]*" maxLength={6}
                  value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  className={`w-full rounded-lg border px-3 py-3 text-center text-2xl tracking-[0.5em] font-mono outline-none transition-colors ${th.input}`}
                  placeholder="000000"
                />
              </div>
              <button type="submit" disabled={busy || code.length !== 6}
                className={`w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-colors ${code.length === 6 && !busy ? 'bg-violet-600 hover:bg-violet-500' : 'bg-violet-600/40 cursor-not-allowed'}`}>
                {busy ? msg('UI_LOGINPAGE_CONFIRMING_2') : msg('UI_LOGINPAGE_CONFIRM_FINISH_2')}
              </button>
            </form>
          )}
        </div>

        <div className={`px-8 py-3 border-t ${th.divider}`}>
          <p className={`text-[11px] text-center ${th.faint}`}>
           {msg('UI_LOGINPAGE_AUTHORIZED_ACCESS_ONLY_ALL_ACTIVITY')}
          </p>
        </div>
      </div>
    </div>
  )
}
