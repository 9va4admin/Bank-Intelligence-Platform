// Guard: wording lives in shared/messages/locales/messages.yaml and reaches a screen through msg('KEY').
// This scans every screen and component for wording typed straight into the code (text between tags, placeholder / title / aria-label
// attributes, label / title / description ... properties, error and notice texts, header lists). The detector is the one the
// converter uses (scripts/i18n/wording.mjs), so "what counts as wording" is defined in one place.
// To fix a failure: node scripts/i18n/convert.mjs --write   (then: python -m shared.messages.build)
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { findWording } from '../../scripts/i18n/wording.mjs'
import { sourceFiles } from '../../scripts/i18n/scan.mjs'

describe('no literal wording in screens', () => {
  it('every screen and component takes its wording from the message taxonomy', () => {
    const root = join(process.cwd(), 'src')
    const offenders = []
    for (const f of sourceFiles(root)) {
      const { sites } = findWording(readFileSync(f, 'utf8'), f)
      sites.forEach(s => offenders.push(`${relative(root, f)}:${s.line} ${JSON.stringify(s.text).slice(0, 60)}`))
    }
    expect(offenders).toEqual([])
  })
})
