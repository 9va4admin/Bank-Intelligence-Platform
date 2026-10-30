// Moves every piece of visible wording found by wording.mjs into shared/messages/locales/messages.yaml and rewrites the code to
// ask for it with msg('KEY', {vars}).   Usage (from apps/web):  node scripts/i18n/convert.mjs [--write] [path-fragment ...]
// Without --write nothing is changed: it prints what it would do.
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs'
import { join, relative, dirname, basename, sep } from 'node:path'
import { parse } from '@babel/parser'
import { findWording } from './wording.mjs'
import { sourceFiles } from './scan.mjs'

const WRITE = process.argv.includes('--write')
const FILTERS = process.argv.slice(2).filter(a => !a.startsWith('--'))
const ROOT = process.cwd()                                   // apps/web
const SRC = join(ROOT, 'src')
const YAML = join(ROOT, '..', '..', 'shared', 'messages', 'locales', 'messages.yaml')

// ---- existing messages, so identical wording reuses its key ------------------------------------------------------------------------------
const yamlText = readFileSync(YAML, 'utf8')
const existingKeys = new Set([...yamlText.matchAll(/^([A-Z][A-Z0-9_]+):\s*$/gm)].map(m => m[1]))
const byText = new Map()
for (const m of yamlText.matchAll(/^([A-Z][A-Z0-9_]+):\s*\n\s+severity:[^\n]*\n\s+surface:[^\n]*\n\s+variables: \[([^\]]*)\]\n\s+en: ("(?:[^"\\]|\\.)*")/gm)) {
  let text; try { text = JSON.parse(m[3]) } catch { continue }
  const sig = `${text}|${m[2].split(',').map(s => s.trim()).filter(Boolean).join(',')}`
  if (!byText.has(sig)) byText.set(sig, m[1])
}

const files = sourceFiles(SRC).filter(f => !FILTERS.length || FILTERS.some(x => f.includes(x)))
const analysed = files.map(f => ({ f, src: readFileSync(f, 'utf8') })).map(o => ({ ...o, ...findWording(o.src, o.f) }))

// words that themselves contain {name} (a topic pattern, a URL template) are shown as written: each token is passed through as a placeholder
for (const o of analysed) for (const s of o.sites) {
  if (/\{\w+\}/.test(s.text) && !s.vars.length) {
    s.vars = [...new Set([...s.text.matchAll(/\{(\w+)\}/g)].map(m => m[1]))].map(n => ({ name: n, code: `'{${n}}'` }))
  }
}

// wording that appears in many files becomes one shared message
const filesPerText = new Map()
for (const o of analysed) for (const s of o.sites) {
  const sig = `${s.text}|${s.vars.map(v => v.name).join(',')}`
  if (!filesPerText.has(sig)) filesPerText.set(sig, new Set())
  filesPerText.get(sig).add(o.f)
}

const slug = (text) => {
  const words = text.replace(/\{\w+\}/g, ' ').replace(/[^A-Za-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean).slice(0, 5)
  const s = words.join('_').toUpperCase().slice(0, 36).replace(/_+$/, '')
  return s || 'TEXT'
}
const screenOf = (f) => basename(f).replace(/\.(jsx?|mjs)$/, '').replace(/^CTS(?=[A-Z])/, '').toUpperCase().replace(/[^A-Z0-9]/g, '') || 'APP'
const severityOf = (t) => /fail|error|could not|cannot|unable|invalid|denied|refused|unavailable|not allowed/i.test(t) ? 'ERROR'
  : /warn|overdue|expired|degraded|missing|breach|risk|late/i.test(t) ? 'WARN' : 'INFO'

const newEntries = []                                          // {key, severity, text, vars}
const newKeys = new Set()
const report = { files: 0, sites: 0, reused: 0, created: 0, skipped: [], failed: [] }

for (const o of analysed) {
  if (!o.sites.length) continue
  const used = new Map()                                       // sig -> key (this file)
  const taken = new Set()
  const edits = []
  const screen = screenOf(o.f)
  const uniqueKey = (base) => { let k = base, i = 2; while (existingKeys.has(k) || newKeys.has(k) || taken.has(k)) k = `${base}_${i++}`; taken.add(k); return k }

  // does this file already use the name `msg` for something else?
  const importRe = /import\s*\{[^}]*\bmsg\b[^}]*\}\s*from\s*['"][^'"]*\/messages['"]/
  const hasImport = importRe.test(o.src)
  const existingAlias = hasImport ? (o.src.match(/import\s*\{[^}]*\bmsg\s+as\s+(\w+)[^}]*\}\s*from\s*['"][^'"]*\/messages['"]/) ?? [])[1] : null
  const otherMsg = hasImport ? false : /\bmsg\b/.test(o.src)
  const fn = existingAlias ?? (otherMsg ? 'uiMsg' : 'msg')

  for (const s of o.sites) {
    if (/\{\w+\}/.test(s.text) && !s.vars.length) {
      // the words themselves contain {name} (a topic pattern, a URL template): show them as written by passing each token through
      const names = [...new Set([...s.text.matchAll(/\{(\w+)\}/g)].map(m => m[1]))]
      s.vars = names.map(n => ({ name: n, code: `'{${n}}'` }))
    }
    const sig = `${s.text}|${s.vars.map(v => v.name).join(',')}`
    let key = used.get(sig) ?? byText.get(sig)
    if (key) { if (!used.has(sig)) report.reused++ }
    else {
      const common = filesPerText.get(sig).size >= 3
      key = uniqueKey(`UI_${common ? 'COMMON' : screen}_${slug(s.text)}`)
      newKeys.add(key); newEntries.push({ key, severity: severityOf(s.text), text: s.text, vars: s.vars.map(v => v.name) })
      byText.set(sig, key); report.created++
    }
    used.set(sig, key)
    const args = s.vars.length ? `, { ${s.vars.map(v => v.code === v.name ? v.name : `${v.name}: ${v.code}`).join(', ')} }` : ''
    const call = `${fn}('${key}'${args})`
    const replacement = s.wrap === 'child' ? `{${call}}` : s.wrap === 'jsx' ? `{${call}}` : call
    edits.push({ start: s.start, end: s.end, replacement })
    report.sites++
  }
  if (!edits.length) continue

  let out = o.src
  edits.sort((a, b) => b.start - a.start).forEach(e => { out = out.slice(0, e.start) + e.replacement + out.slice(e.end) })

  if (!hasImport) {
    let rel = relative(dirname(o.f), join(SRC, 'shared', 'messages')).split(sep).join('/')
    if (!rel.startsWith('.')) rel = './' + rel
    const importLine = `import { msg${otherMsg ? ' as uiMsg' : ''} } from '${rel}'\n`
    const ast = parse(o.src, { sourceType: 'module', plugins: ['jsx'], errorRecovery: true })
    const lastImport = [...ast.program.body].filter(n => n.type === 'ImportDeclaration').pop()
    // offsets shift after the edits; insert at the same place in the edited text (imports precede every edit)
    // imports precede every edit, so the offset is unchanged; use the file's own line ending
    const at = lastImport ? lastImport.end : 0
    const eol = (o.src.slice(at).match(/\r\n|\r|\n/) ?? ['\n'])[0]
    out = lastImport ? out.slice(0, at) + eol + importLine.trimEnd() + out.slice(at) : importLine.trimEnd() + eol + out
  }
  try { parse(out, { sourceType: 'module', plugins: ['jsx'] }) }
  catch (e) { report.failed.push(`${relative(SRC, o.f)}: ${e.message}`); continue }

  report.files++
  if (WRITE) writeFileSync(o.f, out, 'utf8')
}

if (WRITE && newEntries.length) {
  const lines = ['', '# ══════════════════════════════════════════════════════════════════', '# SCREEN WORDING — generated from the web app by apps/web/scripts/i18n/convert.mjs', '# ══════════════════════════════════════════════════════════════════', '']
  for (const e of newEntries) lines.push(`${e.key}:`, `  severity: ${e.severity}`, '  surface: [UI]', `  variables: [${e.vars.join(', ')}]`, `  en: ${JSON.stringify(e.text)}`, '  hi: ""', '')
  appendFileSync(YAML, lines.join('\n'), 'utf8')
}
console.log(JSON.stringify({ write: WRITE, ...report, skipped: report.skipped.length, failed: report.failed.length }))
report.skipped.slice(0, 15).forEach(x => console.log('skipped', x))
report.failed.forEach(x => console.log('FAILED', x))
