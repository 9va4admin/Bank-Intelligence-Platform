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

  it('shows a card for each sample sub-member bank', () => {
    renderSMB()
    expect(screen.queryAllByText('Sample Sub-Member Bank 1').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Sample Sub-Member Bank 2').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Sample Sub-Member Bank 3').length).toBeGreaterThan(0)
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
    // WARN badge on the bank with the high return rate
    expect(screen.queryAllByText(/WARN/).length).toBeGreaterThan(0)
    // SAFE on low-return cards
    expect(screen.queryAllByText(/SAFE/).length).toBeGreaterThan(0)
  })

  it('clicking a card opens detail panel', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Sample Sub-Member Bank 1')[0])
    expect(screen.getByText('Sample Sub-Member Bank 1 — Detail')).toBeTruthy()
  })

  it('detail panel shows bucket breakdown', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Sample Sub-Member Bank 1')[0])
    expect(screen.queryAllByText('STP Pass').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('STP Return').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Eyeball').length).toBeGreaterThan(0)
  })

  it('detail panel shows BM email', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Sample Sub-Member Bank 1')[0])
    expect(screen.queryAllByText(/^bm\..+@.+\.coop$/).length).toBeGreaterThan(0)
  })

  it('closing detail panel hides it', () => {
    renderSMB()
    fireEvent.click(screen.queryAllByText('Sample Sub-Member Bank 1')[0])
    fireEvent.click(screen.getByText('✕'))
    expect(screen.queryByText('Sample Sub-Member Bank 1 — Detail')).toBeFalsy()
  })

  it('shows notification log with return events', () => {
    renderSMB()
    expect(screen.getByText('Notification Log — Today')).toBeTruthy()
    expect(screen.queryAllByText('SIGNATURE_MISMATCH').length).toBeGreaterThan(0)
    expect(screen.queryAllByText(/Tier 1/).length).toBeGreaterThan(0)
  })

  it('shows no soft hold while every sample bank is under its threshold', () => {
    renderSMB()
    expect(screen.queryAllByText(/Soft Hold Active/).length).toBe(0)
  })

  it('notification log shows bucketed amounts not exact amounts', () => {
    renderSMB()
    // Check for range brackets, not exact rupee amounts
    expect(screen.queryAllByText(/₹\[/).length).toBeGreaterThan(0)
  })
})
