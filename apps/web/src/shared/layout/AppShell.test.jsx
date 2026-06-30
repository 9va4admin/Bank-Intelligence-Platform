import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AppShell from './AppShell'
import { ThemeProvider } from '../theme/ThemeContext'
import { PageHeaderProvider } from './PageHeaderContext'

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual }
})

function renderShell(pathname = '/cts', children = <div>content</div>) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <ThemeProvider>
        <PageHeaderProvider>
          <AppShell>{children}</AppShell>
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('AppShell sidebar navigation', () => {
  it('renders the ASTRA logo', () => {
    renderShell()
    expect(screen.getByText('stra')).toBeTruthy()
  })

  it('renders CTS module section', () => {
    renderShell()
    const ctsBtns = screen.getAllByText('CTS')
    expect(ctsBtns.length).toBeGreaterThan(0)
  })

  it('renders Admin module section', () => {
    renderShell()
    const adminItems = screen.getAllByText('Admin')
    expect(adminItems.length).toBeGreaterThan(0)
  })

  it('shows CTS nav items when CTS module is expanded', () => {
    renderShell('/cts')
    expect(screen.getByText('Inward Queue')).toBeTruthy()
    expect(screen.getByText('Ops Dashboard')).toBeTruthy()
    expect(screen.getByText('Settlement')).toBeTruthy()
  })

  it('shows breadcrumb for /cts route', () => {
    renderShell('/cts')
    expect(screen.getByText('Inward Queue — Human Review')).toBeTruthy()
  })

  it('shows breadcrumb for /cts/settlement route', () => {
    renderShell('/cts/settlement')
    expect(screen.getByText('Settlement Lifecycle')).toBeTruthy()
  })

  it('renders collapse button', () => {
    renderShell()
    const collapseBtn = screen.getByTitle('Collapse sidebar')
    expect(collapseBtn).toBeTruthy()
  })

  it('collapses sidebar when collapse button is clicked', () => {
    renderShell()
    const collapseBtn = screen.getByTitle('Collapse sidebar')
    fireEvent.click(collapseBtn)
    expect(screen.queryByTitle('Expand sidebar')).toBeTruthy()
    expect(screen.queryByText('Inward Queue')).toBeNull()
  })

  it('expands sidebar from collapsed state', () => {
    renderShell()
    fireEvent.click(screen.getByTitle('Collapse sidebar'))
    fireEvent.click(screen.getByTitle('Expand sidebar'))
    expect(screen.getByText('Inward Queue')).toBeTruthy()
  })

  it('renders theme toggle button', () => {
    renderShell()
    const toggleBtns = screen.getAllByTitle(/Switch to/)
    expect(toggleBtns.length).toBeGreaterThan(0)
  })

  it('renders user avatar with initials', () => {
    renderShell()
    expect(screen.getByText('R')).toBeTruthy()
  })

  it('opens profile menu on avatar click', () => {
    renderShell()
    const avatarBtn = screen.getByText('Rahul S.').closest('button')
    fireEvent.click(avatarBtn)
    expect(screen.getByText('Sign Out')).toBeTruthy()
  })

  it('renders children content', () => {
    renderShell('/cts', <div>Hello World Content</div>)
    expect(screen.getByText('Hello World Content')).toBeTruthy()
  })

  it('shows Admin items after clicking Admin module', () => {
    renderShell('/cts')
    const adminBtns = screen.getAllByText('Admin')
    const adminBtn = adminBtns.find((el) => el.closest('button'))
    if (adminBtn) fireEvent.click(adminBtn.closest('button'))
    expect(screen.getByText('User Management')).toBeTruthy()
  })

  it('shows bank name in topbar', () => {
    renderShell()
    const bankNames = screen.getAllByText('Saraswat Co-op Bank')
    expect(bankNames.length).toBeGreaterThan(0)
  })
})
