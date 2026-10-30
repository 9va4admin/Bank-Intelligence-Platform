// Dry run: lists the wording sites the detector finds. Usage: node scripts/i18n/scan.mjs [--files] [--sample N] [path...]
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { findWording } from './wording.mjs'

export const SKIP = [/\.test\./, /[\\/]locales[\\/]/, /[\\/]shared[\\/]messages\.js$/, /[\\/]test-setup\.js$/, /[\\/]main\.jsx$/,
  /[\\/]config[\\/]/, /[\\/]demoImages/,
  /[\\/]components[\\/]landing[\\/]/]                       // the landing page is static marketing copy and is exempt

export function sourceFiles(root) {
  const out = []
  const walk = (d) => {
    for (const n of readdirSync(d)) {
      const p = join(d, n)
      if (statSync(p).isDirectory()) { if (n !== 'node_modules') walk(p) } else if (/\.(jsx?|mjs)$/.test(n) && !SKIP.some(r => r.test(p))) out.push(p)
    }
  }
  walk(root)
  return out.sort()
}

if (process.argv[1].endsWith('scan.mjs')) {
  const args = process.argv.slice(2)
  const showFiles = args.includes('--files')
  const sampleIdx = args.indexOf('--sample')
  const sample = sampleIdx >= 0 ? Number(args[sampleIdx + 1]) : 0
  const root = join(process.cwd(), 'src')
  let total = 0, files = 0, demo = 0
  const byKind = {}
  const rows = []
  for (const f of sourceFiles(root)) {
    const { sites, skippedDemo } = findWording(readFileSync(f, 'utf8'), f)
    demo += skippedDemo
    if (sites.length) { files++; total += sites.length; rows.push([relative(root, f), sites.length]) }
    for (const s of sites) byKind[s.kind] = (byKind[s.kind] ?? 0) + 1
    if (sample && sites.length) sites.slice(0, sample).forEach(s => console.log(`${relative(root, f)}:${s.line} [${s.kind}] ${JSON.stringify(s.text).slice(0, 110)}${s.vars.length ? '  vars=' + s.vars.map(v => v.name).join(',') : ''}`))
  }
  console.log(JSON.stringify({ filesWithWording: files, sites: total, byKind, demoSkipped: demo }))
  if (showFiles) rows.sort((a, b) => b[1] - a[1]).slice(0, 25).forEach(r => console.log(r[1], r[0]))
}
