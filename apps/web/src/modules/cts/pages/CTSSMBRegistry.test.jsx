import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSSMBRegistry from './CTSSMBRegistry'

function Wrapper({ children }) {
  return (
    <MemoryRouter>
      <ThemeProvider>{children}</ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSSMBRegistry', () => {

  it('shows register SMB button', () => {
    render(<CTSSMBRegistry />, { wrapper: Wrapper })
    expect(screen.getByText(/Onboard \/ Manage/)).toBeTruthy()
  })
})
