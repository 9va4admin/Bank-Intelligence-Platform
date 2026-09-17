/**
 * CTSInwardMonitor — TDD test file
 * Unit tests for pure helpers + smoke tests for the React Flow canvas.
 */

import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import { BankProvider } from '../../../shared/context/BankContext'
// Static import keeps the same React + ThemeContext instance as the providers.
// vi.resetModules() is NOT used in smoke tests to avoid context mismatch.
import CTSInwardMonitorStatic from './CTSInwardMonitor'

function renderWithProviders(ui) {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <BankProvider>
          <PageHeaderProvider>
            {ui}
          </PageHeaderProvider>
        </BankProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

// ── urgency() unit tests (logic mirrored here; single source in component) ───

function urgency(ietDeadline) {
  const mins = Math.max(0, (ietDeadline - Date.now()) / 60000)
  if (mins < 5)  return 'urgent'
  if (mins < 15) return 'critical'
  if (mins < 30) return 'warning'
  if (mins < 60) return 'caution'
  return 'safe'
}

describe('urgency()', () => {
  it('returns safe when > 60 min remaining', () => {
    expect(urgency(Date.now() + 90 * 60000)).toBe('safe')
  })

  it('returns caution when 30–60 min remaining', () => {
    expect(urgency(Date.now() + 45 * 60000)).toBe('caution')
  })

  it('returns warning when 15–30 min remaining', () => {
    expect(urgency(Date.now() + 20 * 60000)).toBe('warning')
  })

  it('returns critical when 5–15 min remaining', () => {
    expect(urgency(Date.now() + 10 * 60000)).toBe('critical')
  })

  it('returns urgent when < 5 min remaining', () => {
    expect(urgency(Date.now() + 3 * 60000)).toBe('urgent')
  })

  it('returns urgent when deadline already passed', () => {
    expect(urgency(Date.now() - 1000)).toBe('urgent')
  })
})

// ── STAGES shape ──────────────────────────────────────────────────────────────

const EXPECTED_STAGE_IDS = ['RECEIVED', 'OCR', 'SIGNATURE', 'FRAUD', 'REVIEW', 'NGCH']

describe('STAGES config', () => {
  let STAGES

  beforeEach(async () => {
    const mod = await import('./CTSInwardMonitor')
    STAGES = mod.STAGES
  })

  afterEach(() => { vi.resetModules() })

  it('has exactly 6 stages', () => {
    expect(STAGES).toHaveLength(6)
  })

  it('stage ids match expected pipeline', () => {
    expect(STAGES.map(s => s.id)).toEqual(EXPECTED_STAGE_IDS)
  })

  it('all stages have id, label, icon, x', () => {
    STAGES.forEach(s => {
      expect(s).toHaveProperty('id')
      expect(s).toHaveProperty('label')
      expect(s).toHaveProperty('icon')
      expect(s).toHaveProperty('x')
    })
  })

  it('x positions are strictly increasing', () => {
    for (let i = 1; i < STAGES.length; i++) {
      expect(STAGES[i].x).toBeGreaterThan(STAGES[i - 1].x)
    }
  })

  it('RECEIVED is first stage', () => {
    expect(STAGES[0].id).toBe('RECEIVED')
  })

  it('NGCH is last stage', () => {
    expect(STAGES[STAGES.length - 1].id).toBe('NGCH')
  })
})

// ── makeMockInstruments() shape ───────────────────────────────────────────────

describe('makeMockInstruments()', () => {
  let makeMockInstruments

  beforeEach(async () => {
    const mod = await import('./CTSInwardMonitor')
    makeMockInstruments = mod.makeMockInstruments
  })

  afterEach(() => { vi.resetModules() })

  it('returns a non-empty array', () => {
    expect(makeMockInstruments().length).toBeGreaterThan(0)
  })

  it('all instruments have required fields', () => {
    makeMockInstruments().forEach(i => {
      expect(i).toHaveProperty('id')
      expect(i).toHaveProperty('stage')
      expect(i).toHaveProperty('ietDeadline')
      expect(i).toHaveProperty('bank')
      expect(i).toHaveProperty('amount')
      expect(i).toHaveProperty('status')
    })
  })

  it('all stage values are in the expected set', () => {
    const valid = new Set(EXPECTED_STAGE_IDS)
    makeMockInstruments().forEach(i => {
      expect(valid.has(i.stage)).toBe(true)
    })
  })

  it('all ietDeadlines are in the future (mock data is live)', () => {
    const now = Date.now()
    makeMockInstruments().forEach(i => {
      expect(i.ietDeadline).toBeGreaterThan(now)
    })
  })

  it('amount fields use the masked range format', () => {
    const validAmounts = new Set(['₹[<1L]', '₹[1L-5L]', '₹[5L-10L]', '₹[10L-1Cr]', '₹[>1Cr]'])
    makeMockInstruments().forEach(i => {
      expect(validAmounts.has(i.amount)).toBe(true)
    })
  })

  it('ids are unique', () => {
    const ids = makeMockInstruments().map(i => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

// ── buildInitialNodes() structure ─────────────────────────────────────────────

describe('buildInitialNodes()', () => {
  let buildInitialNodes, makeMockInstruments

  beforeEach(async () => {
    const mod = await import('./CTSInwardMonitor')
    buildInitialNodes  = mod.buildInitialNodes
    makeMockInstruments = mod.makeMockInstruments
  })

  afterEach(() => { vi.resetModules() })

  it('produces nodes for all 6 stage headers', () => {
    const nodes = buildInitialNodes(makeMockInstruments())
    const headers = nodes.filter(n => n.type === 'stageHeader')
    expect(headers).toHaveLength(6)
  })

  it('stage header ids follow hdr- prefix', () => {
    const nodes = buildInitialNodes(makeMockInstruments())
    nodes.filter(n => n.type === 'stageHeader').forEach(n => {
      expect(n.id.startsWith('hdr-')).toBe(true)
    })
  })

  it('produces cheque nodes for every instrument', () => {
    const instruments = makeMockInstruments()
    const nodes = buildInitialNodes(instruments)
    const cheques = nodes.filter(n => n.type === 'chequeNode')
    expect(cheques).toHaveLength(instruments.length)
  })

  it('cheque node ids match instrument ids', () => {
    const instruments = makeMockInstruments()
    const nodes = buildInitialNodes(instruments)
    const chequeIds = new Set(nodes.filter(n => n.type === 'chequeNode').map(n => n.id))
    instruments.forEach(i => {
      expect(chequeIds.has(i.id)).toBe(true)
    })
  })

  it('all nodes have a position with x and y', () => {
    const nodes = buildInitialNodes(makeMockInstruments())
    nodes.forEach(n => {
      expect(n.position).toHaveProperty('x')
      expect(n.position).toHaveProperty('y')
      expect(typeof n.position.x).toBe('number')
      expect(typeof n.position.y).toBe('number')
    })
  })

  it('stage header nodes are not draggable', () => {
    const nodes = buildInitialNodes(makeMockInstruments())
    nodes.filter(n => n.type === 'stageHeader').forEach(n => {
      expect(n.draggable).toBe(false)
    })
  })

  it('cheque nodes are not draggable (monitor mode)', () => {
    const nodes = buildInitialNodes(makeMockInstruments())
    nodes.filter(n => n.type === 'chequeNode').forEach(n => {
      expect(n.draggable).toBe(false)
    })
  })

  it('cheque nodes within same stage have increasing y positions', () => {
    const instruments = makeMockInstruments()
    const nodes = buildInitialNodes(instruments)
    EXPECTED_STAGE_IDS.forEach(stageId => {
      const stageInstrs = instruments.filter(i => i.stage === stageId)
      if (stageInstrs.length < 2) return
      const stageNodes = stageInstrs.map(i => nodes.find(n => n.id === i.id))
      for (let j = 1; j < stageNodes.length; j++) {
        expect(stageNodes[j].position.y).toBeGreaterThan(stageNodes[j - 1].position.y)
      }
    })
  })
})

// ── Component smoke tests ─────────────────────────────────────────────────────

describe('CTSInwardMonitor smoke tests', () => {
  // React Flow needs these browser APIs in jsdom — set once for the whole suite.
  beforeAll(() => {
    global.ResizeObserver = class {
      observe()    {}
      unobserve()  {}
      disconnect() {}
    }
    Element.prototype.getBoundingClientRect = vi.fn(() => ({
      width: 1200, height: 800, top: 0, left: 0, bottom: 800, right: 1200, x: 0, y: 0,
    }))
    vi.stubGlobal('localStorage', {
      getItem:    vi.fn(() => null),
      setItem:    vi.fn(),
      removeItem: vi.fn(),
      clear:      vi.fn(),
    })
  })

  afterEach(() => {
    // Clean up DOM between tests
    document.body.innerHTML = ''
  })

  // Uses static import (CTSInwardMonitorStatic) so ThemeContext instance
  // matches the ThemeProvider imported at the top of this file.

  it('renders without crashing', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    expect(document.body.innerHTML.length).toBeGreaterThan(100)
  })

  it('shows Inward IET Monitor heading', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    expect(screen.getByText('Inward IET Monitor')).toBeTruthy()
  })

  it('shows In-Flight stat label', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    expect(screen.getByText('In-Flight')).toBeTruthy()
  })

  it('shows IET Critical stat label', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    expect(screen.getByText('IET Critical')).toBeTruthy()
  })

  it('shows Human Review stat label', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    expect(screen.getByText('Human Review')).toBeTruthy()
  })

  it('shows LIVE indicator', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    expect(screen.getByText(/LIVE/)).toBeTruthy()
  })

  it('shows NGCH Filing stat label', async () => {
    await act(async () => renderWithProviders(<CTSInwardMonitorStatic />))
    // Appears in both stats bar and stage header node — getAllByText handles both.
    expect(screen.getAllByText('NGCH Filing').length).toBeGreaterThan(0)
  })
})
