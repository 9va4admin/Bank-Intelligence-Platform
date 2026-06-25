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
    expect(screen.getByText('Total Users')).toBeTruthy()
    expect(screen.getByText('Active')).toBeTruthy()
    expect(screen.getByText('TOTP Enabled')).toBeTruthy()
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

  it('role filter narrows results', () => {
    renderPage()
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'bank_it_admin' } })
    expect(screen.getByText('Vikram Kapoor')).toBeTruthy()
    expect(screen.queryByText('Priya Mehta')).toBeFalsy()
  })

  it('opens create user modal on + New User click', () => {
    renderPage()
    fireEvent.click(screen.getByText('+ New User'))
    expect(screen.getByText('Create User')).toBeTruthy()
  })

  it('opens edit modal when Edit is clicked', () => {
    renderPage()
    const editBtns = screen.getAllByText('Edit')
    fireEvent.click(editBtns[0])
    expect(screen.getByText('Edit User')).toBeTruthy()
  })

  it('shows TOTP info panel', () => {
    renderPage()
    expect(screen.getByText(/RFC 6238/)).toBeTruthy()
  })

  it('inactive users show Inactive badge', () => {
    renderPage()
    expect(screen.getByText('Inactive')).toBeTruthy()
  })
})
