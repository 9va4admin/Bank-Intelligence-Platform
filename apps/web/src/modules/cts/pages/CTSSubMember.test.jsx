import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSSubMember from './CTSSubMember'

function renderSMB() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <CTSSubMember />
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSSubMember', () => {
  it('renders the page heading', () => {
    renderSMB()
    expect(screen.getAllByText(/Sub-Member Bank/i).length).toBeGreaterThan(0)
  })

  it('shows 4 sub-member bank cards', () => {
    renderSMB()
    expect(screen.queryAllByText('Vasavi Co-op Bank').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Kalyan Janata Sahakari Bank').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Mehsana Urban Co-op Bank').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Delhi Mercantile Co-op Bank').length).toBeGreaterThan(0)
  })

  it('shows KPI strip with key metrics', () => {
    renderSMB()
    expect(screen.getByText('Sub-Member Banks')).toBeTruthy()
    expect(screen.getByText('Total Inward')).toBeTruthy()
    expect(screen.getByText('Total Returns')).toBeTruthy()
    expect(screen.getByText('Avg Return Rate')).toBeTruthy()
    expect(screen.getByText('Shield Active')).toBeTruthy()
  })

  it('shows shield badge on cards', () => {
    renderSMB()
    // SOFT_HOLD badge on Kalyan Janata (high return rate)
    expect(screen.queryAllByText(/SOFT-HOLD/).length).toBeGreaterThan(0)
    // SAFE on low-return cards
    expect(screen.queryAllByText(/SAFE/).length).toBeGreaterThan(0)
  })

  it('clicking a card opens detail panel', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Vasavi Co-op Bank')[0])
    expect(screen.getByText('Vasavi Co-op Bank — Detail')).toBeTruthy()
  })

  it('detail panel shows bucket breakdown', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Vasavi Co-op Bank')[0])
    expect(screen.queryAllByText('STP Pass').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('STP Return').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Eyeball').length).toBeGreaterThan(0)
  })

  it('detail panel shows BM email', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Vasavi Co-op Bank')[0])
    expect(screen.queryAllByText('bm.andheri@vasavi.bank').length).toBeGreaterThan(0)
  })

  it('closing detail panel hides it', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Vasavi Co-op Bank')[0])
    fireEvent.click(screen.getByText('✕'))
    expect(screen.queryByText('Vasavi Co-op Bank — Detail')).toBeFalsy()
  })

  it('shows notification log with return events', () => {
    renderSMB()
    expect(screen.getByText('Notification Log — Today')).toBeTruthy()
    expect(screen.queryAllByText('SIGNATURE_MISMATCH').length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/Tier 1/).length).toBeGreaterThan(0)
  })

  it('shows soft hold active on kalyan janata card', () => {
    renderSMB()
    expect(screen.queryAllByText(/Soft Hold Active/).length).toBeGreaterThan(0)
  })

  it('notification log shows bucketed amounts not exact amounts', () => {
    renderSMB()
    // Check for range brackets, not exact rupee amounts
    expect(screen.queryAllByText(/₹\[/).length).toBeGreaterThan(0)
  })
})
