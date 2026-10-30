import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import UserManagement from './UserManagement'

vi.mock('../../../shared/theme/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggle: vi.fn() }),
}))
vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <UserManagement />
    </MemoryRouter>
  )
}

describe('UserManagement', () => {
  it('renders the page heading', () => {
    renderPage()
    expect(screen.getByText('User Management')).toBeTruthy()
  })

  it('shows summary card counts', () => {
    renderPage()
    // one summary line: "<n> active · <n> with TOTP · <n> in this tab"
    expect(screen.getByText(/\d+ active · \d+ with TOTP · \d+ in this tab/)).toBeTruthy()
  })

  it('renders a row for each mock user', () => {
    renderPage()
    expect(screen.getByText('Priya Mehta')).toBeTruthy()
    expect(screen.getByText('Rahul Singh')).toBeTruthy()
    expect(screen.getByText('Vikram Kapoor')).toBeTruthy()
  })

  it('shows role badges', () => {
    renderPage()
    expect(screen.getAllByText('Ops Reviewer').length).toBeGreaterThan(0)
    expect(screen.getByText('IT Admin')).toBeTruthy()
  })

  it('search filters by name', () => {
    renderPage()
    const input = screen.getByPlaceholderText('Search name or email…')
    fireEvent.change(input, { target: { value: 'priya' } })
    expect(screen.getByText('Priya Mehta')).toBeTruthy()
    expect(screen.queryByText('Rahul Singh')).toBeFalsy()
  })


  it('opens create user modal on + New User click', () => {
    renderPage()
    fireEvent.click(screen.getByText('+ New User'))
    expect(screen.getAllByText('Create User')[0]).toBeTruthy()
  })

  it('opens edit modal when Edit is clicked', () => {
    renderPage()
    const editBtns = screen.getAllByRole('button', { name: 'Edit' })
    fireEvent.click(editBtns[0])
    expect(screen.getByText('Edit User')).toBeTruthy()
  })

  it('opens the TOTP set-up dialog for a user without TOTP', () => {
    renderPage()
    fireEvent.click(screen.getAllByRole('button', { name: 'Setup TOTP' })[0])
    expect(screen.getByText('Set Up TOTP Authenticator')).toBeTruthy()
  })

  it('inactive users show Inactive badge', () => {
    renderPage()
    expect(screen.getByText('Inactive')).toBeTruthy()
  })
})
