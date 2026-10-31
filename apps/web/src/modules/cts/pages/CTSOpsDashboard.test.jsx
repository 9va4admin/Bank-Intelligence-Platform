import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSOpsDashboard from './CTSOpsDashboard'

vi.mock('../../../shared/theme/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggle: vi.fn() }),
}))
vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

describe('CTSOpsDashboard', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getByTestId('appshell')).toBeTruthy()
  })

  it('shows KPI labels', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getByText('Total Inward')).toBeTruthy()
    expect(screen.getAllByText('STP Confirmed')[0]).toBeTruthy()
    expect(screen.getByText(/^Net \(/)).toBeTruthy()
  })

  it('shows session cards', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getAllByText(/SES-/).length).toBeGreaterThan(0)
  })

  it('shows download buttons', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getAllByText(/NPCI/i).length).toBeGreaterThan(0)
  })
})


// The API answers a download with the file itself. The page used to expect a JSON link (res.json()) and so could never
// save anything the real endpoint sent.
describe('CTSOpsDashboard downloads', () => {
  it('saves the bytes the API sends under the name it gives', async () => {
    const created = []
    const realCreate = global.URL.createObjectURL
    global.URL.createObjectURL = vi.fn((b) => { created.push(b); return 'blob:test' })
    global.URL.revokeObjectURL = vi.fn()
    // Other requests the page makes on mount (live dashboard data) must not consume the download's response.
    const fetchMock = vi.fn().mockImplementation((url) => Promise.resolve(
      String(url).includes('/download/')
        ? new Response(new Blob(['a,b\n1,2\n'], { type: 'text/csv' }), {
          status: 200, headers: { 'Content-Disposition': 'attachment; filename=MIS_KBL_TODAY.csv' },
        })
        : new Response('{}', { status: 404 }),
    ))
    vi.stubGlobal('fetch', fetchMock)
    const clicked = []
    const realCreateEl = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = realCreateEl(tag)
      if (tag === 'a') el.click = () => clicked.push({ href: el.href, name: el.download })
      return el
    })

    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    fireEvent.click(screen.getAllByText(/MIS CSV/i)[0])
    await waitFor(() => expect(clicked.length).toBe(1))

    const downloadCall = fetchMock.mock.calls.find((c) => String(c[0]).includes('/download/'))
    expect(String(downloadCall[0])).toMatch(/\/v1\/cts\/sessions\/[^/]+\/download\/mis$/)
    expect(created[0]).toBeInstanceOf(Blob)
    expect(clicked[0].name).toBe('MIS_KBL_TODAY.csv')
    document.createElement.mockRestore()
    vi.unstubAllGlobals()
    global.URL.createObjectURL = realCreate
  })
})
