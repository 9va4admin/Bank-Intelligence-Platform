import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSReconciliation from './CTSReconciliation'

const renderPage = () => render(
  <MemoryRouter>
    <ThemeProvider>
      <CTSReconciliation />
    </ThemeProvider>
  </MemoryRouter>
)

describe('CTSReconciliation', () => {
  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText('Reconciliation').length).toBeGreaterThan(0)
  })

  it('renders KPI strip with Total Items', () => {
    renderPage()
    expect(screen.getByText('Total Items')).toBeInTheDocument()
  })

  it('renders session selector', () => {
    renderPage()
    expect(screen.getByText('Jun 19 — Session 1')).toBeInTheDocument()
  })

  it('renders Download CSV button', () => {
    renderPage()
    expect(screen.getByText(/Download CSV/)).toBeInTheDocument()
  })

  it('renders MATCHED status badge in table', () => {
    renderPage()
    expect(screen.getAllByText(/Matched/).length).toBeGreaterThan(0)
  })

  it('filter by PENDING shows fewer rows than all', () => {
    renderPage()
    // Before filter: many instrument IDs shown
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
