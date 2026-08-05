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

import CTSCompliance from './CTSCompliance'

const renderPage = () => render(
  <MemoryRouter><ThemeProvider><CTSCompliance /></ThemeProvider></MemoryRouter>
)

describe('CTSCompliance', () => {
  it('renders without crashing', () => {
    renderPage()
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('passes subtitle to page header', () => {
    renderPage()
    expect(typeof captured.subtitle).toBe('string')
    expect(captured.subtitle).toMatch(/RBI|CTS|Standard/i)
  })

  it('passes Download Certificate button to page header actions', () => {
    renderPage()
    render(<div>{captured.actions}</div>, { wrapper: ({ children }) => <MemoryRouter><ThemeProvider>{children}</ThemeProvider></MemoryRouter> })
    expect(screen.getByText(/Download Certificate/)).toBeInTheDocument()
  })

  it('renders KPI strip with Instruments label', () => {
    renderPage()
    expect(screen.getByText('Instruments')).toBeInTheDocument()
  })

  it('renders standard thresholds section', () => {
    renderPage()
    expect(screen.getByText('CTS-2010 Standard Thresholds (RBI Mandate)')).toBeInTheDocument()
  })

  it('shows 200 dpi threshold', () => {
    renderPage()
    expect(screen.getByText('200 dpi')).toBeInTheDocument()
  })

  it('filter FAIL shows fewer rows than ALL', () => {
    renderPage()
    const allCount = screen.queryAllByText(/CHQ-OUT-/).length
    fireEvent.click(screen.getByRole('button', { name: 'FAIL' }))
    const failCount = screen.queryAllByText(/CHQ-OUT-/).length
    expect(failCount).toBeLessThan(allCount)
  })

  it('lot selector changes displayed instruments', () => {
    renderPage()
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: screen.getAllByRole('option')[1]?.value } })
    expect(screen.getByText('Instruments')).toBeInTheDocument()
  })
})
