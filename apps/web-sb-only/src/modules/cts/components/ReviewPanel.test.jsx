import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import ReviewPanel from './ReviewPanel'

const baseItem = {
  instrument_id: 'CHQ-2026-001847',
  account_display: '****7234',
  payee_display: 'S***',
  amount_range: '₹[10L-1Cr]',
  amount_label: 'HIGH VALUE',
  clearing_zone: 'MUMBAI',
  iet_deadline: new Date(Date.now() + 30 * 60000).toISOString(),
  reason: 'SIGNATURE_LOW_CONFIDENCE',
  reason_label: 'Signature mismatch',
  fraud_score: 0.81,
  ocr_confidence: 0.97,
  sig_match_score: 0.61,
  sig_specimen_available: true,
  sig_specimen_label: 'Last updated: 14-Feb-2026',
  ocr_fields: {
    date: '18-Jun-2026',
    payee: 'S*** Enterprises',
    amount_figures: '₹45,00,000',
    amount_words: 'Forty five lakhs only',
    micr: '400160002',
    alterations: false,
  },
  shap_values: [
    { feature: 'Signature match score', value: -0.31, direction: 'risk' },
  ],
}

describe('ReviewPanel — empty state', () => {
  it('shows select prompt when no item provided', () => {
    render(<ReviewPanel item={null} onDecision={() => {}} />)
    expect(screen.getByText(/select a cheque/i)).toBeInTheDocument()
  })
})

describe('ReviewPanel — header', () => {
  it('shows instrument ID and account display', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByText(/CHQ-2026-001847/)).toBeInTheDocument()
    expect(screen.getByText(/\*\*\*\*7234/)).toBeInTheDocument()
  })

  it('shows reason label badge', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByText('Signature mismatch')).toBeInTheDocument()
  })

  it('does NOT show OPA badge when opa_rule is absent', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.queryByText('OPA')).not.toBeInTheDocument()
  })

  it('shows OPA badge when opa_rule is set', () => {
    const item = { ...baseItem, opa_rule: 'cts_routing.rego · rule: high_value_dual_approval' }
    render(<ReviewPanel item={item} onDecision={() => {}} />)
    expect(screen.getByText('OPA')).toBeInTheDocument()
  })
})

describe('ReviewPanel — SigPanel (specimen available)', () => {
  it('shows match score percentage', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    // 61% appears in both the score tile and SigPanel — use getAllBy
    const matches = screen.getAllByText('61%')
    expect(matches.length).toBeGreaterThanOrEqual(1)
  })

  it('shows specimen label', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByText(/Last updated: 14-Feb-2026/)).toBeInTheDocument()
  })
})

describe('ReviewPanel — SigPanel (vault miss)', () => {
  const vaultMissItem = {
    ...baseItem,
    sig_match_score: null,
    sig_specimen_available: false,
    sig_specimen_label: 'No specimen — account opened 22-Jan-2026',
    reason: 'VAULT_MISS',
    reason_label: 'No signature specimen on file',
  }

  it('shows No Specimen On File heading', () => {
    render(<ReviewPanel item={vaultMissItem} onDecision={() => {}} />)
    expect(screen.getByText('No Specimen On File')).toBeInTheDocument()
  })

  it('shows vault miss account reference', () => {
    render(<ReviewPanel item={vaultMissItem} onDecision={() => {}} />)
    expect(screen.getByText(/no specimen — account opened/i)).toBeInTheDocument()
  })

  it('displays N/A in sig score tile', () => {
    render(<ReviewPanel item={vaultMissItem} onDecision={() => {}} />)
    expect(screen.getByText('N/A')).toBeInTheDocument()
  })
})

describe('ReviewPanel — action footer', () => {
  it('Return button is disabled when no reason selected', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    const returnBtn = screen.getByRole('button', { name: /return cheque/i })
    expect(returnBtn).toBeDisabled()
  })

  it('Return button enables after selecting a reason', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'Signature mismatch confirmed' } })
    const returnBtn = screen.getByRole('button', { name: /return cheque/i })
    expect(returnBtn).not.toBeDisabled()
  })

  it('Confirm button is always enabled', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByRole('button', { name: /confirm cheque/i })).not.toBeDisabled()
  })

  it('calls onDecision with CONFIRM action after timeout', async () => {
    vi.useFakeTimers()
    const onDecision = vi.fn()
    render(<ReviewPanel item={baseItem} onDecision={onDecision} />)
    fireEvent.click(screen.getByRole('button', { name: /confirm cheque/i }))
    await act(async () => { vi.advanceTimersByTime(900) })
    expect(onDecision).toHaveBeenCalledWith('CHQ-2026-001847', 'CONFIRM', '')
    vi.useRealTimers()
  })

  it('calls onDecision with RETURN action and reason after timeout', async () => {
    vi.useFakeTimers()
    const onDecision = vi.fn()
    render(<ReviewPanel item={baseItem} onDecision={onDecision} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Signature mismatch confirmed' } })
    fireEvent.click(screen.getByRole('button', { name: /return cheque/i }))
    await act(async () => { vi.advanceTimersByTime(900) })
    expect(onDecision).toHaveBeenCalledWith('CHQ-2026-001847', 'RETURN', 'Signature mismatch confirmed')
    vi.useRealTimers()
  })

  it('does NOT call onDecision for RETURN when reason is empty', () => {
    const onDecision = vi.fn()
    render(<ReviewPanel item={baseItem} onDecision={onDecision} />)
    // Force click even though button is disabled
    const returnBtn = screen.getByRole('button', { name: /return cheque/i })
    fireEvent.click(returnBtn)
    expect(onDecision).not.toHaveBeenCalled()
  })
})

describe('ReviewPanel — tabs', () => {
  it('renders overview tab by default', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByText('OCR Extracted Fields · GOT-OCR2.0')).toBeInTheDocument()
  })

  it('switches to cheque tab and renders specimen watermark', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /^cheque$/i }))
    expect(screen.getByText('SPECIMEN')).toBeInTheDocument()
  })

  it('switches to AI analysis tab', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /ai analysis/i }))
    expect(screen.getByText('Model Stack')).toBeInTheDocument()
    expect(screen.getByText('GOT-OCR2.0')).toBeInTheDocument()
    expect(screen.getByText('XGBoost')).toBeInTheDocument()
  })
})

describe('ReviewPanel — OCR fields', () => {
  it('shows alteration warning when alterations detected', () => {
    const item = { ...baseItem, ocr_fields: { ...baseItem.ocr_fields, alterations: true } }
    render(<ReviewPanel item={item} onDecision={() => {}} />)
    expect(screen.getByText('⚠ DETECTED')).toBeInTheDocument()
  })

  it('shows no alteration when clean', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByText('✓ None')).toBeInTheDocument()
  })
})
