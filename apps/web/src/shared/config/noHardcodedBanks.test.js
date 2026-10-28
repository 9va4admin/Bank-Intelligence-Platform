// Guard: a screen must take the current bank's name from bank.config.js, not type another bank's name into its sample data.
// Allowed: the config itself, per-bank keyed tables, screens that deliberately list several banks, and comments.
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = join(process.cwd(), 'src')
const NAMES = /Saraswat|Federal Bank|Union Bank|Vasavi|Thrissur UCB|Ernakulam UCB|Kalyan Janata|Mehsana|smb-mh-vasavi|smb-mh-kjsb|smb-gj-mucb/
const ALLOWED = [
  'shared/config/bank.config.js', 'shared/config/federalBankBranches.js',
  'modules/cts/pages/CTSBranchMaster.jsx',      // per-bank keyed branch tables
  'modules/cts/pages/CTSProcessingUnits.jsx',   // per-bank keyed PU tables
  'modules/cts/pages/CTSDemoLive.jsx',          // deliberately lists several banks
  'modules/admin/pages/SecurityViolations.jsx', // sample security events keyed by bank id
  'modules/cts/pages/CTSPresentment.jsx',       // drawee banks are other banks by definition
]

function files(dir) {
  return readdirSync(dir).flatMap(n => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? files(p) : [p]
  }).filter(p => /\.(jsx?|js)$/.test(p) && !/\.test\./.test(p))
}

describe('no hard-coded bank names in screens', () => {
  it('only the allowed files mention another bank by name (outside comments)', () => {
    const offenders = []
    for (const p of files(ROOT)) {
      const rel = p.slice(ROOT.length + 1).split('\\').join('/')
      if (ALLOWED.includes(rel)) continue
      const code = readFileSync(p, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')
      if (NAMES.test(code)) offenders.push(rel)
    }
    expect(offenders).toEqual([])
  })
})
