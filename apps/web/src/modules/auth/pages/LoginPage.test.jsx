import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from './LoginPage'

vi.mock('../../../shared/theme/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggle: vi.fn() }),
}))
vi.mock('../../../shared/context/AuthContext', () => ({
  useAuth: () => ({ refresh: vi.fn().mockResolvedValue('authenticated') }),
}))

function renderPage() {
  return render(<MemoryRouter><LoginPage /></MemoryRouter>)
}

function fillCredentials() {
  fireEvent.change(screen.getByPlaceholderText('operator.name'), { target: { value: 'ops1' } })
  fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'pw' } })
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('renders the sign-in step', () => {
    renderPage()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeTruthy()
    expect(screen.getByText('Use your ASTRA operator credentials.')).toBeTruthy()
    expect(screen.getByText('ASTRA')).toBeTruthy()
  })

  it('advances to the MFA verify step on MFA_REQUIRED and stores the CSRF token', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ outcome: 'MFA_REQUIRED', requires: 'mfa_code', csrf_token: 'csrf-1' }),
    })
    renderPage()
    fillCredentials()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByText('Two-factor authentication')).toBeTruthy())
    expect(global.fetch).toHaveBeenCalledWith(
      '/v1/auth/login',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
    expect(sessionStorage.getItem('astra-csrf')).toBe('csrf-1')
  })

  it('shows a uniform error on invalid credentials (401)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) })
    renderPage()
    fillCredentials()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByText('Invalid username or password.')).toBeTruthy())
  })

  it('shows a lockout message on 423', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 423, json: async () => ({}) })
    renderPage()
    fillCredentials()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByText(/Account locked/)).toBeTruthy())
  })

  it('enters the enrolment step and shows the setup key on first login', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true, status: 200,
        json: async () => ({ outcome: 'MFA_ENROLLMENT_REQUIRED', requires: 'mfa_enrollment', csrf_token: 'c' }),
      })
      .mockResolvedValueOnce({
        ok: true, status: 200,
        json: async () => ({ secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/ASTRA:ops1?secret=JBSWY3DPEHPK3PXP' }),
      })
    renderPage()
    fillCredentials()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByText('Set up two-factor authentication')).toBeTruthy())
    expect(screen.getByText(/JBSW Y3DP EHPK 3PXP/)).toBeTruthy()
  })
})
