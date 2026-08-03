import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import RequireAuth from './RequireAuth'

vi.mock('../theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false }) }))

const h = vi.hoisted(() => ({ status: 'loading' }))
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ status: h.status }) }))

function renderAt(status) {
  h.status = status
  return render(
    <MemoryRouter initialEntries={['/secret']}>
      <Routes>
        <Route path="/login" element={<div>LOGIN SCREEN</div>} />
        <Route element={<RequireAuth />}>
          <Route path="/secret" element={<div>SECRET CONTENT</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireAuth', () => {
  it('shows a splash while the session is resolving', () => {
    renderAt('loading')
    expect(screen.getByText(/Checking your session/i)).toBeTruthy()
  })

  it('redirects to /login when unauthenticated', () => {
    renderAt('unauthenticated')
    expect(screen.getByText('LOGIN SCREEN')).toBeTruthy()
  })

  it('renders the protected route when authenticated', () => {
    renderAt('authenticated')
    expect(screen.getByText('SECRET CONTENT')).toBeTruthy()
  })
})
