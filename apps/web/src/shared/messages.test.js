import { describe, it, expect, afterEach, vi } from 'vitest'
import { initMessages, msg, setLocale, activeLocale } from './messages'

afterEach(async () => { localStorage.clear(); await initMessages('en') })

describe('message helper', () => {
  it('shows English for a message the active language does not have yet', async () => {
    const english = msg('CTS_OUT_CUSTODY_TITLE')
    await initMessages('hi')                       // the Hindi bundle has no translations yet
    expect(activeLocale()).toBe('hi')
    expect(msg('CTS_OUT_CUSTODY_TITLE')).toBe(english)   // never a blank label
  })

  it('shows the key itself only when no language has the message', () => {
    expect(msg('NO_SUCH_MESSAGE_KEY')).toBe('NO_SUCH_MESSAGE_KEY')
  })

  it('remembers the chosen language and reloads so every screen is rebuilt in it', () => {
    const reload = vi.fn()
    setLocale('hi', reload)
    expect(localStorage.getItem('astra-locale')).toBe('hi')
    expect(reload).toHaveBeenCalledOnce()
  })

  it('starts in the remembered language', async () => {
    localStorage.setItem('astra-locale', 'hi')
    await initMessages()
    expect(activeLocale()).toBe('hi')
  })
})
