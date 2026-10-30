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

  it('shows a dash for the policy rule on the passport tab when opa_rule is absent', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /passport/i }))
    expect(screen.getByText('OPA Rule').nextSibling).toHaveTextContent('—')
  })

  it('shows the policy rule on the passport tab when opa_rule is set', () => {
    const item = { ...baseItem, opa_rule: 'cts_routing.rego · rule: high_value_dual_approval' }
    render(<ReviewPanel item={item} onDecision={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /passport/i }))
    expect(screen.getByText('cts_routing.rego · rule: high_value_dual_approval')).toBeInTheDocument()
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
    expect(screen.getAllByText('N/A')[0]).toBeInTheDocument()
  })
})

describe('ReviewPanel — action footer', () => {
  // The reviewer is the maker: Approve sends the cheque on to validation, Return files a URRBCH reason code.
  const pickReason = (label) => {
    fireEvent.click(screen.getByText('Select Return Reason…'))
    fireEvent.mouseDown(screen.getByText(label))
  }

  it('Return button is disabled when no reason selected', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByRole('button', { name: /✕ return/i })).toBeDisabled()
  })

  it('Return button enables after selecting a reason', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    pickReason('Insufficient funds')
    expect(screen.getByRole('button', { name: /✕ return/i })).not.toBeDisabled()
  })

  it('Approve button is always enabled', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByRole('button', { name: /approve → validation iq/i })).not.toBeDisabled()
  })

  it('calls onDecision with APPROVE_TO_VALIDATION when approved', () => {
    const onDecision = vi.fn()
    render(<ReviewPanel item={baseItem} onDecision={onDecision} />)
    fireEvent.click(screen.getByRole('button', { name: /approve → validation iq/i }))
    expect(onDecision).toHaveBeenCalledWith('CHQ-2026-001847', 'APPROVE_TO_VALIDATION', {})
  })

  it('calls onDecision with RETURN, the reason and its URRBCH code', () => {
    const onDecision = vi.fn()
    render(<ReviewPanel item={baseItem} onDecision={onDecision} />)
    pickReason('Insufficient funds')
    fireEvent.click(screen.getByRole('button', { name: /✕ return/i }))
    expect(onDecision).toHaveBeenCalledWith('CHQ-2026-001847', 'RETURN', expect.objectContaining({ label: 'Insufficient funds', urrbch_code: '01' }))
  })

  it('does NOT call onDecision for RETURN when reason is empty', () => {
    const onDecision = vi.fn()
    render(<ReviewPanel item={baseItem} onDecision={onDecision} />)
    // Force click even though button is disabled
    fireEvent.click(screen.getByRole('button', { name: /✕ return/i }))
    expect(onDecision).not.toHaveBeenCalled()
  })
})

describe('ReviewPanel — tabs', () => {
  it('renders overview tab by default', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    expect(screen.getByText('OCR Fields · click ⓘ for AI detail')).toBeInTheDocument()
  })

  it('switches to cheque tab and renders specimen watermark', () => {
    render(<ReviewPanel item={baseItem} onDecision={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /^cheque$/i }))
    expect(screen.getAllByText('Front B/W')[0]).toBeInTheDocument()
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
