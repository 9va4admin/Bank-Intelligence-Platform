// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { PageHeaderProvider, PageHeaderCtx, usePageHeader } from './PageHeaderContext'
import { useContext } from 'react'

afterEach(() => cleanup())

// Consumer component that reads context values
function ContextReader() {
  const { subtitle, actions } = useContext(PageHeaderCtx)
  return (
    <div>
      <span data-testid="subtitle">{subtitle ?? 'none'}</span>
      <div data-testid="actions">{actions}</div>
    </div>
  )
}

// Page component that uses the hook
function FakePage({ subtitle, actions }) {
  usePageHeader({ subtitle, actions })
  return <div data-testid="page">content</div>
}

function Tree({ subtitle, actions }) {
  return (
    <PageHeaderProvider>
      <ContextReader />
      <FakePage subtitle={subtitle} actions={actions} />
    </PageHeaderProvider>
  )
}

describe('PageHeaderProvider', () => {
  it('renders children', () => {
    render(<PageHeaderProvider><div data-testid="child">hi</div></PageHeaderProvider>)
    expect(screen.getByTestId('child')).toBeInTheDocument()
  })

  it('provides null subtitle and actions by default', () => {
    render(
      <PageHeaderProvider>
        <ContextReader />
      </PageHeaderProvider>
    )
    expect(screen.getByTestId('subtitle')).toHaveTextContent('none')
    expect(screen.getByTestId('actions')).toBeEmptyDOMElement()
  })
})

describe('usePageHeader', () => {
  it('sets subtitle in context when page mounts', () => {
    render(<Tree subtitle="Saraswat Co-op Bank · Session SES-001 · 2026-06-19" />)
    expect(screen.getByTestId('subtitle')).toHaveTextContent('Saraswat Co-op Bank')
  })

  it('sets actions JSX in context when page mounts', () => {
    render(<Tree actions={<button>Download CSV</button>} />)
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeInTheDocument()
  })

  it('sets both subtitle and actions together', () => {
    render(
      <Tree
        subtitle="Bank · Session · Date"
        actions={<button>Export</button>}
      />
    )
    expect(screen.getByTestId('subtitle')).toHaveTextContent('Bank · Session · Date')
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument()
  })

  it('renders page content alongside context', () => {
    render(<Tree subtitle="test" />)
    expect(screen.getByTestId('page')).toHaveTextContent('content')
  })
})
