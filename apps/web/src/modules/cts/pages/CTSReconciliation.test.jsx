// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

let captured = {}
vi.mock('../../../shared/layout/PageHeaderContext', () => ({
  usePageHeader: (opts = {}) => { captured = opts },
  PageHeaderCtx: {},
  PageHeaderProvider: ({ children }) => <>{children}</>,
}))

import CTSReconciliation from './CTSReconciliation'

const renderPage = () => render(
  <MemoryRouter><ThemeProvider><CTSReconciliation /></ThemeProvider></MemoryRouter>
)

describe('CTSReconciliation', () => {
  it('renders without crashing', () => {
    renderPage()
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('passes subtitle to page header', () => {
    renderPage()
    expect(typeof captured.subtitle).toBe('string')
  })

  it('passes Download CSV button to page header actions', () => {
    renderPage()
    render(<div>{captured.actions}</div>, { wrapper: ({ children }) => <MemoryRouter><ThemeProvider>{children}</ThemeProvider></MemoryRouter> })
    expect(screen.getByText(/Download CSV/)).toBeInTheDocument()
  })

  it('renders KPI strip with Total Items', () => {
    renderPage()
    expect(screen.getByText('Total Items')).toBeInTheDocument()
  })

  it('renders session selector', () => {
    renderPage()
    expect(screen.getByText('Jun 19 — Session 1')).toBeInTheDocument()
  })

  it('renders MATCHED status badge in table', () => {
    renderPage()
    expect(screen.getAllByText(/Matched/).length).toBeGreaterThan(0)
  })

  it('filter by PENDING shows fewer rows than all', () => {
    renderPage()
    const before = screen.queryAllByText(/CHQ-IN-/).length
    const pendingBtn = screen.getByRole('button', { name: 'Pending' })
    fireEvent.click(pendingBtn)
    const after = screen.queryAllByText(/CHQ-IN-/).length
    expect(after).toBeLessThan(before)
  })

  it('renders status reference legend', () => {
    renderPage()
    expect(screen.getByText('Status Reference')).toBeInTheDocument()
  })

  it('session dropdown changes data set', () => {
    renderPage()
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: '1' } })
    expect(screen.getByText('Jun 18 — Session 1')).toBeInTheDocument()
  })
})
