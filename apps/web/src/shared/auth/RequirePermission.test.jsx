/**
 * RequirePermission — route-level authorisation guard.
 *
 * Simulated scenarios proving that a logged-in user with the wrong role
 * is redirected to /access-denied rather than seeing the page shell.
 *
 * RequireAuth (authentication) always runs first in the route tree, so
 * unauthenticated users never reach RequirePermission.
 *
 * Scenarios tested:
 *   A. /ops/ocr-feedback  (perm: ai:model_metrics)
 *      - fraud_analyst   → /access-denied
 *      - ops_reviewer    → /access-denied
 *      - ml_engineer     → page renders
 *      - ops_manager     → page renders
 *      - bank_it_admin   → page renders
 *
 *   B. /admin/users  (perm: user:manage)
 *      - ops_manager     → /access-denied
 *      - fraud_analyst   → /access-denied
 *      - bank_it_admin   → page renders
 *
 *   C. /cts/config/thresholds  (perm: config:layer3:submit)
 *      - fraud_analyst   → /access-denied
 *      - ops_reviewer    → /access-denied
 *      - ops_manager     → page renders
 *      - bank_it_admin   → /access-denied  (they have approve, not submit)
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import RequirePermission from './RequirePermission'
import { ROLE_PERMISSIONS } from '../context/BankContext'

vi.mock('../theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false }) }))

// Inject a mock BankContext that returns hasPermission based on the given role.
const mockRole = { current: 'ops_manager' }

vi.mock('../context/BankContext', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    useBankContext: () => ({
      hasPermission: (perm) => real.roleHasPermission(mockRole.current, perm),
      userRole: mockRole.current,
    }),
  }
})

function renderWithPermission(permission, role) {
  mockRole.current = role
  return render(
    <MemoryRouter initialEntries={['/protected']}>
      <Routes>
        <Route path="/access-denied" element={<div>ACCESS DENIED</div>} />
        <Route element={<RequirePermission permission={permission} />}>
          <Route path="/protected" element={<div>PROTECTED CONTENT</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

// ── Scenario A: ai:model_metrics (OCR Feedback, Model Health) ─────────────────

describe('Scenario A — /ops/ocr-feedback requires ai:model_metrics', () => {
  const PERM = 'ai:model_metrics'

  it('fraud_analyst is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'fraud_analyst')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
    expect(screen.queryByText('PROTECTED CONTENT')).toBeNull()
  })

  it('ops_reviewer is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'ops_reviewer')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
    expect(screen.queryByText('PROTECTED CONTENT')).toBeNull()
  })

  it('ml_engineer can access the page', () => {
    renderWithPermission(PERM, 'ml_engineer')
    expect(screen.getByText('PROTECTED CONTENT')).toBeTruthy()
    expect(screen.queryByText('ACCESS DENIED')).toBeNull()
  })

  it('ops_manager can access the page', () => {
    renderWithPermission(PERM, 'ops_manager')
    expect(screen.getByText('PROTECTED CONTENT')).toBeTruthy()
    expect(screen.queryByText('ACCESS DENIED')).toBeNull()
  })

  it('bank_it_admin can access the page', () => {
    renderWithPermission(PERM, 'bank_it_admin')
    expect(screen.getByText('PROTECTED CONTENT')).toBeTruthy()
    expect(screen.queryByText('ACCESS DENIED')).toBeNull()
  })

  it('compliance_officer is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'compliance_officer')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('rbi_examiner is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'rbi_examiner')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })
})

// ── Scenario B: user:manage (User Management) ─────────────────────────────────

describe('Scenario B — /admin/users requires user:manage', () => {
  const PERM = 'user:manage'

  it('ops_manager is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'ops_manager')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('fraud_analyst is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'fraud_analyst')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('ops_reviewer is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'ops_reviewer')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('bank_it_admin can access user management', () => {
    renderWithPermission(PERM, 'bank_it_admin')
    expect(screen.getByText('PROTECTED CONTENT')).toBeTruthy()
  })

  it('ml_engineer is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'ml_engineer')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })
})

// ── Scenario C: config:layer3:submit (Thresholds config) ──────────────────────

describe('Scenario C — /cts/config/thresholds requires config:layer3:submit', () => {
  const PERM = 'config:layer3:submit'

  it('fraud_analyst is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'fraud_analyst')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('ops_reviewer is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'ops_reviewer')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('ops_manager can access thresholds config', () => {
    renderWithPermission(PERM, 'ops_manager')
    expect(screen.getByText('PROTECTED CONTENT')).toBeTruthy()
  })

  it('bank_it_admin is redirected — they have approve not submit', () => {
    renderWithPermission(PERM, 'bank_it_admin')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })

  it('ml_engineer is redirected to /access-denied', () => {
    renderWithPermission(PERM, 'ml_engineer')
    expect(screen.getByText('ACCESS DENIED')).toBeTruthy()
  })
})

// ── Verify ROLE_PERMISSIONS mirror is complete ─────────────────────────────────

describe('ROLE_PERMISSIONS mirror matches expected permissions', () => {
  it('ops_manager has ai:model_metrics', () => {
    expect(ROLE_PERMISSIONS['ops_manager']).toContain('ai:model_metrics')
  })

  it('bank_it_admin has ai:model_metrics', () => {
    expect(ROLE_PERMISSIONS['bank_it_admin']).toContain('ai:model_metrics')
  })

  it('ml_engineer has ai:model_metrics', () => {
    expect(ROLE_PERMISSIONS['ml_engineer']).toContain('ai:model_metrics')
  })

  it('fraud_analyst does NOT have ai:model_metrics', () => {
    expect(ROLE_PERMISSIONS['fraud_analyst']).not.toContain('ai:model_metrics')
  })

  it('ops_reviewer does NOT have ai:model_metrics', () => {
    expect(ROLE_PERMISSIONS['ops_reviewer']).not.toContain('ai:model_metrics')
  })

  it('bank_it_admin has user:manage', () => {
    expect(ROLE_PERMISSIONS['bank_it_admin']).toContain('user:manage')
  })

  it('ops_manager does NOT have user:manage', () => {
    expect(ROLE_PERMISSIONS['ops_manager']).not.toContain('user:manage')
  })
})
