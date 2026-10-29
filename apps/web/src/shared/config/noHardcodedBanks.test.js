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

// The zone concept is gone: a branch maps to a processing unit and that is all. The files below still carry NGCH-facing
// "zone" fields (decision-log export, MICR routing rules, NGCH routing) and are tracked as the second slice of the removal.
const ZONE_ALLOWED = [
  'modules/cts/pages/CTSDecisionsLog.jsx',
  'modules/cts/pages/CTSMICRPrefixes.jsx',
  'modules/cts/pages/CTSNGCHRouting.jsx',
]
const stripComments = (code) => code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')

describe('no clearing-zone concept in screens', () => {
  it('no screen outside the tracked second-slice files uses clearing_zone / "Clearing Zone"', () => {
    const offenders = []
    for (const p of files(ROOT)) {
      const rel = p.slice(ROOT.length + 1).split(String.fromCharCode(92)).join('/')
      if (ZONE_ALLOWED.includes(rel) || rel === 'shared/config/bank.config.js' || rel.startsWith('components/landing/')) continue
      if (/clearing_zone|Clearing Zone|clearingZone/i.test(stripComments(readFileSync(p, 'utf8')))) offenders.push(rel)
    }
    expect(offenders).toEqual([])
  })
})
