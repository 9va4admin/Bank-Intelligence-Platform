// Finds visible wording in a React source file. Shared by the codemod (scripts/i18n/convert.mjs) and the guard test
// (src/shared/noLiteralWording.test.js), so "what counts as wording" is defined in exactly one place.
//
// A *site* is a range of source text that holds words a person reads: text between tags, a placeholder / title / aria-label /
// label ... attribute, the label / title / description ... property of an object, the text of a thrown or displayed error.
// Each site becomes a message in shared/messages/locales/messages.yaml and the code asks for it with msg('KEY', {vars}).
import { parse } from '@babel/parser'
import traverseModule from '@babel/traverse'

const traverse = traverseModule.default ?? traverseModule

// Attributes whose string value is shown to people.
export const WORDING_ATTRS = new Set([
  'placeholder', 'title', 'aria-label', 'aria-description', 'alt', 'label', 'hint', 'description', 'tooltip', 'text',
  'subtitle', 'heading', 'caption', 'emptyText', 'helperText', 'confirmLabel', 'cancelLabel', 'message', 'header',
  'emptyMessage', 'loadingText', 'errorText', 'successText', 'noun', 'unit',
])

// Object properties whose string value is shown to people.
export const WORDING_PROPS = new Set([
  'label', 'title', 'description', 'hint', 'subtitle', 'heading', 'placeholder', 'tooltip', 'message', 'text', 'header',
  'desc', 'summary', 'caption', 'emptyText', 'helper', 'note', 'cta', 'error', 'errorMessage', 'successMessage',
  'confirmText', 'question', 'answer', 'blurb', 'tagline', 'detail', 'details', 'body', 'intro', 'empty', 'loading',
  'noData', 'reason_label', 'outcome_label', 'status_label', 'tab', 'tabLabel', 'sublabel', 'short', 'long', 'prompt',
  'instructions', 'warning', 'info', 'success', 'failure', 'badge', 'button', 'buttonLabel', 'cta_label', 'name_label',
])

// Functions whose first string argument is shown to people.
const DISPLAY_CALLS = /^(alert|confirm|toast|showToast|notify|showMessage|showError|showSuccess|setError|setNotice|setStatus|setMessage|setToast|setErr|setBanner|setFeedback|setInfo|setWarning|setSuccess|setActionError|setSubmitError|setLoadError|setResultMessage|setErrorMsg|setMsg|setNote)$/

// Demo content is wording too (a demo screen is still a screen). Sample records use keys such as payee / name, which are not wording keys.
const DEMO_VAR = /(?!)/

const HAS_WORD = /[A-Za-z]{2,}/

// Not every string under a `label` or `text` key is wording: Tailwind classes, enum codes, URLs and existing message keys are not.
function plausible(text) {
  const t = text.trim()
  if (!/[A-Za-z]/.test(t)) return false
  if (/^[A-Z0-9_]+$/.test(t) && (t.includes('_') || t.length <= 3)) return false          // CTS_WF_X, SB, IET
  if (!/\s/.test(t) && /^[a-z0-9_:\/\-\[\]\.#%@!]+$/.test(t)) return false              // dark, text-red-400, w-1/2
  if (/^(https?:|\/|#|\.\/|mailto:)/.test(t)) return false
  if (/^[a-z]+(-[a-z0-9\[\]\/.%]+)+$/.test(t)) return false
  return true
}
const HAS_LETTER = /[A-Za-z]/

export function cleanJsxText(value) {
  const lines = value.split(/\r\n|\n|\r/)
  let lastNonEmpty = 0
  lines.forEach((l, i) => { if (/[^ \t]/.test(l)) lastNonEmpty = i })
  let out = ''
  lines.forEach((line, i) => {
    let t = line.replace(/\t/g, ' ')
    if (i !== 0) t = t.replace(/^ +/, '')
    if (i !== lines.length - 1) t = t.replace(/ +$/, '')
    if (t) { if (i !== lastNonEmpty) t += ' '; out += t }
  })
  return out
}

function containsJsx(node) {
  let found = false
  const visit = (n) => {
    if (!n || found || typeof n.type !== 'string') return
    if (n.type === 'JSXElement' || n.type === 'JSXFragment') { found = true; return }
    for (const k of Object.keys(n)) {
      if (k === 'loc' || k === 'start' || k === 'end') continue
      const v = n[k]
      if (Array.isArray(v)) v.forEach(visit); else if (v && typeof v === 'object') visit(v)
    }
  }
  visit(node)
  return found
}

function isFunctionish(n) {
  return n && (n.type === 'ArrowFunctionExpression' || n.type === 'FunctionExpression' || n.type === 'ObjectExpression' || n.type === 'ArrayExpression')
}

export function nameOf(node) {
  switch (node.type) {
    case 'Identifier': return node.name
    case 'MemberExpression': case 'OptionalMemberExpression':
      return !node.computed && node.property.type === 'Identifier' ? node.property.name : nameOf(node.object)
    case 'CallExpression': case 'OptionalCallExpression':
      return /^Member|^OptionalMember/.test(node.callee.type) ? nameOf(node.callee.object) : nameOf(node.callee)
    case 'TSNonNullExpression': return nameOf(node.expression)
    default: return 'value'
  }
}

function placeholderName(base, used) {
  let n = /^\w+$/.test(base) && !/^\d/.test(base) ? base : 'value'
  if (n === 'length') n = 'count'
  let name = n, i = 2
  while (used.has(name)) name = `${n}${i++}`
  used.add(name)
  return name
}

/**
 * @returns {{sites: Array, skippedDemo: number}}
 *  site = { kind, start, end, text, vars: [{name, code}], line, context }
 *  `code` is the original source of each placeholder expression, so the codemod can pass it to msg().
 */
export function findWording(source, filename = 'file.jsx') {
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'], errorRecovery: true })
  const sites = []
  let skippedDemo = 0
  const src = (n) => source.slice(n.start, n.end)

  const inDemo = (path) => {
    for (let p = path; p; p = p.parentPath) {
      if (p.node.type === 'VariableDeclarator' && p.node.id.type === 'Identifier' && DEMO_VAR.test(p.node.id.name)) return true
    }
    return false
  }

  const addLiteralSite = (path, node, kind, extra = {}) => {
    if (inDemo(path)) { skippedDemo++; return }
    if (node.type === 'StringLiteral') {
      if (!HAS_LETTER.test(node.value) || (kind !== 'text' && !plausible(node.value))) return
      sites.push({ kind, start: node.start, end: node.end, text: node.value, vars: [], line: node.loc.start.line, ...extra })
    } else if (node.type === 'TemplateLiteral') {
      const used = new Set(); const vars = []; let text = ''
      node.quasis.forEach((q, i) => {
        text += q.value.cooked ?? q.value.raw
        if (i < node.expressions.length) {
          const e = node.expressions[i]
          if (containsJsx(e) || isFunctionish(e)) { text = null; return }
          const name = placeholderName(nameOf(e), used)
          vars.push({ name, code: src(e) }); text += `{${name}}`
        }
      })
      if (text === null || !HAS_LETTER.test(node.quasis.map(q => q.value.cooked ?? q.value.raw).join('')) || !plausible(text)) return
      sites.push({ kind, start: node.start, end: node.end, text, vars, line: node.loc.start.line, ...extra })
    }
  }

  traverse(ast, {
    // ---- text between tags, merged with simple {expressions} into one sentence -----------------------------------------------------
    JSXElement: { enter(path) { handleChildren(path, path.node.children) } },
    JSXFragment: { enter(path) { handleChildren(path, path.node.children) } },

    // ---- attributes ---------------------------------------------------------------------------------------------------------------------
    JSXAttribute(path) {
      const { name, value } = path.node
      const attr = name.type === 'JSXIdentifier' ? name.name : `${name.namespace.name}:${name.name.name}`
      if (!WORDING_ATTRS.has(attr) || !value) return
      if (path.parentPath.parent && /^(code|pre|kbd|style|script)$/.test(path.parentPath.parent.openingElement?.name?.name ?? '')) return
      if (value.type === 'StringLiteral') addLiteralSite(path, value, 'attr', { attr, wrap: 'jsx' })
      else if (value.type === 'JSXExpressionContainer' && (value.expression.type === 'StringLiteral' || value.expression.type === 'TemplateLiteral')) {
        addLiteralSite(path, value.expression, 'attr', { attr, wrap: 'expr' })
      }
    },

    // ---- label: 'Text' properties --------------------------------------------------------------------------------------------------------
    ObjectProperty(path) {
      const { key, value, computed } = path.node
      if (computed) return
      const k = key.type === 'Identifier' ? key.name : key.type === 'StringLiteral' ? key.value : null
      if (!k || !WORDING_PROPS.has(k)) return
      if (value.type === 'StringLiteral' || value.type === 'TemplateLiteral') addLiteralSite(path, value, 'prop', { prop: k })
    },

    // ---- throw new Error('...'), alert('...'), setError('...') ----------------------------------------------------------------------------
    NewExpression(path) {
      const n = path.node
      if (n.callee.type === 'Identifier' && n.callee.name === 'Error' && n.arguments[0] && /^(StringLiteral|TemplateLiteral)$/.test(n.arguments[0].type)) {
        addLiteralSite(path, n.arguments[0], 'error')
      }
    },
    CallExpression(path) {
      const n = path.node
      const callee = n.callee.type === 'Identifier' ? n.callee.name : n.callee.type === 'MemberExpression' && !n.callee.computed ? n.callee.property.name : null
      if (callee && DISPLAY_CALLS.test(callee) && n.arguments[0] && /^(StringLiteral|TemplateLiteral)$/.test(n.arguments[0].type)) {
        addLiteralSite(path, n.arguments[0], 'display')
      }
      // ['A', 'B', 'C'].map(...) rendered as headings / options
      if (n.callee.type === 'MemberExpression' && !n.callee.computed && n.callee.property.name === 'map' && n.callee.object.type === 'ArrayExpression') {
        const arr = n.callee.object
        const inJsx = path.findParent(p => p.isJSXExpressionContainer() || p.isJSXAttribute())
        if (inJsx && arr.elements.length && arr.elements.every(e => e && e.type === 'StringLiteral')) {
          arr.elements.forEach(e => { if (HAS_WORD.test(e.value)) addLiteralSite(path, e, 'list') })
        }
      }
    },
    // err.detail || 'Could not ...'
    LogicalExpression(path) {
      const n = path.node
      if ((n.operator === '||' || n.operator === '??') && n.right.type === 'StringLiteral' && HAS_WORD.test(n.right.value) &&
          n.left.type === 'MemberExpression' && !n.left.computed && /^(detail|message|error|msg)$/.test(n.left.property.name) && / /.test(n.right.value)) {
        addLiteralSite(path, n.right, 'fallback')
      }
    },
    // head={['Instrument', 'Branch']} and const COLUMNS = ['A', 'B']
    ArrayExpression(path) {
      const n = path.node
      if (!n.elements.length || !n.elements.every(e => e && e.type === 'StringLiteral')) return
      const parent = path.parent
      const attrName = parent.type === 'JSXExpressionContainer' && path.parentPath.parent.type === 'JSXAttribute' ? path.parentPath.parent.name.name : null
      const varName = parent.type === 'VariableDeclarator' && parent.id.type === 'Identifier' ? parent.id.name : null
      const headerish = (attrName && /^(head|headers|columns|cols|headings|labels|titles)$/i.test(attrName)) ||
                        (varName && /(HEAD|HEADER|COLUMN|HEADING|TITLES|LABELS)S?$/i.test(varName))
      if (headerish) n.elements.forEach(e => { if (HAS_WORD.test(e.value)) addLiteralSite(path, e, 'list') })
    },
  })

  function handleChildren(path, children) {
    const tag = path.node.openingElement?.name?.name
    if (/^(style|script)$/.test(tag)) return
    let run = []
    const flush = () => { if (run.length) { emitRun(path, run); run = [] } }
    for (const child of children) {
      if (child.type === 'JSXText') run.push(child)
      else if (child.type === 'JSXExpressionContainer') {
        const e = child.expression
        if (e.type === 'JSXEmptyExpression') continue
        if (e.type === 'StringLiteral' && /^(\s|[A-Za-z])/.test(e.value)) run.push(child)
        else if (containsJsx(e) || isFunctionish(e)) flush()
        else run.push(child)
      } else flush()                              // a nested element ends the sentence
    }
    flush()
  }

  function emitRun(path, run) {
    // trim whitespace-only text at both ends
    const isBlank = (n) => n.type === 'JSXText' && cleanJsxText(n.value).trim() === ''
    while (run.length && isBlank(run[0])) run.shift()
    while (run.length && isBlank(run[run.length - 1])) run.pop()
    if (!run.length) return
    const used = new Set(); const vars = []; let text = ''; let letters = ''; let exprCount = 0
    for (const n of run) {
      if (n.type === 'JSXText') { const c = cleanJsxText(n.value); text += c; letters += c }
      else if (n.expression.type === 'StringLiteral') { text += n.expression.value; letters += n.expression.value }
      else {
        const e = n.expression
        const name = placeholderName(nameOf(e), used)
        vars.push({ name, code: src(e) }); text += `{${name}}`; exprCount++
      }
    }
    text = text.replace(/^\s+/, '').replace(/\s+$/, '')
    if (!(HAS_WORD.test(letters) || (exprCount > 0 && HAS_LETTER.test(letters)))) return
    if (inDemo(path)) { skippedDemo++; return }
    // the range runs from the first visible character to the last
    const first = run[0], last = run[run.length - 1]
    let start = first.start, end = last.end
    if (first.type === 'JSXText') start = first.start + (first.value.length - first.value.replace(/^\s+/, '').length)
    if (last.type === 'JSXText') end = last.end - (last.value.length - last.value.replace(/\s+$/, '').length)
    sites.push({ kind: 'text', start, end, text, vars, line: first.loc.start.line, wrap: 'child' })
  }

  // drop any site nested inside another site's range (the outer one is converted whole)
  sites.sort((a, b) => a.start - b.start || b.end - a.end)
  const kept = []
  for (const s of sites) { const prev = kept[kept.length - 1]; if (prev && s.start >= prev.start && s.end <= prev.end) continue; kept.push(s) }
  return { sites: kept, skippedDemo }
}
