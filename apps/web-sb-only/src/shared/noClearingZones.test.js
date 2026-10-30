// There are no clearing zones (CLAUDE.md §2.12): a bank files to one NGCH grid and its branches map to processing units.
// This fails the build if a screen, sample record or config key brings the idea back.
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(process.cwd(), 'src')
const SKIP_DIR = new Set(['node_modules', 'landing', 'locales'])
const FORBIDDEN = [
  [/clearing[_ ]zones?/i, 'clearing zone'],
  [/['"](MUMBAI|DELHI|CHENNAI|KOLKATA|HYDERABAD|AHMEDABAD)['"]/, 'a city used as a zone name'],
  [/\.zone\b|\bzone:\s*['"]/, 'a zone field'],
  [/\/cts\/rpc\b|rpc\/zones/i, 'the retired RPC route'],
]

function sources(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) { if (!SKIP_DIR.has(name)) sources(p, out) }
    else if (/\.(jsx?|mjs)$/.test(name) && !/\.test\./.test(name)) out.push(p)
  }
  return out
}

describe('no clearing zones in the web source', () => {
  it('finds no zone vocabulary outside the landing page', () => {
    const hits = []
    for (const file of sources(SRC)) {
      readFileSync(file, 'utf8').split(/\r?\n/).forEach((line, i) => {
        for (const [re, what] of FORBIDDEN) if (re.test(line)) hits.push(`${relative(SRC, file)}:${i + 1} ${what}: ${line.trim().slice(0, 80)}`)
      })
    }
    expect(hits).toEqual([])
  })
})
