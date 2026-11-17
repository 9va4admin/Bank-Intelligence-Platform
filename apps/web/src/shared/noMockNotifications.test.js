// The bell once showed hard-coded notifications to every user ("IET risk, 22 minutes remaining" ...). In a bank that is dangerous: an invented
// critical alert, and a real one that never appears. This fails the build if fabricated notification data comes back into the shell.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const shell = readFileSync(join(process.cwd(), 'src', 'shared', 'layout', 'AppShell.jsx'), 'utf8')

describe('the notification bell shows only real data', () => {
  it('has no hard-coded notification list', () => {
    expect(shell).not.toMatch(/MOCK_NOTIFICATIONS/)
    expect(shell).not.toMatch(/useState\(\s*\[\s*\{[^}]*severity/)
  })
  it('reads the user\'s own inbox', () => {
    expect(shell).toMatch(/useInbox\(/)
  })
})
