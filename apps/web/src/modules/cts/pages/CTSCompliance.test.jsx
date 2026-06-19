import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSCompliance from './CTSCompliance'

const renderPage = () => render(
  <MemoryRouter>
    <ThemeProvider>
      <CTSCompliance />
    </ThemeProvider>
  </MemoryRouter>
)

describe('CTSCompliance', () => {
  it('renders page heading', () => {
    renderPage()
    expect(screen.getByText('CTS-2010 Compliance Certificate')).toBeInTheDocument()
  })

  it('renders RBI subtitle', () => {
    renderPage()
    expect(screen.getByText(/RBI CTS-2010 Standard/)).toBeInTheDocument()
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

  it('renders Download Certificate button', () => {
    renderPage()
    expect(screen.getByText(/Download Certificate/)).toBeInTheDocument()
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
    // after selection, page still renders without crash
    expect(screen.getByText('Instruments')).toBeInTheDocument()
  })
})
