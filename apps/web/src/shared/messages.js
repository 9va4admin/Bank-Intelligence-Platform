/**
 * Lightweight message helper — loads the JSON bundle for the active locale
 * and formats messages by substituting {variable} placeholders.
 *
 * Usage:
 *   import { msg } from '../shared/messages'
 *   msg('CTS_WF_VAULT_MISS', { account_display: '****4521', instrument_id: 'CTS-001' })
 *
 * Bundle files live at src/shared/locales/messages.{locale}.json.
 * To add a locale: add YAML under shared/messages/locales/{locale}/ and run the build.
 */

const _bundles = {}

async function _loadBundle(locale) {
  if (_bundles[locale]) return _bundles[locale]
  try {
    const mod = await import(`./locales/messages.${locale}.json`)
    _bundles[locale] = mod.default ?? mod
  } catch {
    if (locale !== 'en') {
      await _loadBundle('en')
      _bundles[locale] = _bundles['en']
    } else {
      _bundles['en'] = {}
    }
  }
  return _bundles[locale]
}

// Synchronous get — only works after the bundle has been pre-loaded via init().
function _get(key, variables, locale) {
  // The active language first, then English: a message nobody has translated yet shows in English, never as a blank or a raw key.
  const own = (_bundles[locale] ?? {})[key]
  const entry = own?.text ? own : (_bundles['en'] ?? {})[key]      // an empty translation counts as missing
  if (!entry) return key

  let text = entry.text ?? ''
  if (!text) return ''

  if (variables) {
    text = text.replace(/\{(\w+)\}/g, (_, name) =>
      Object.prototype.hasOwnProperty.call(variables, name) ? variables[name] : `{${name}}`
    )
  }
  return text
}

// ── Public API ─────────────────────────────────────────────────────────────────

let _activeLocale = 'en'
let _ready = false

const LOCALE_KEY = 'astra-locale'

function storedLocale() {
  try { return localStorage.getItem(LOCALE_KEY) || 'en' } catch { return 'en' }
}

/** The language the screens are currently in. */
export function activeLocale() {
  return _activeLocale
}

/**
 * Choose a language. Screens read their wording when they load, so the app is reloaded to rebuild every screen in the new language.
 * `reload` is injectable for tests.
 */
export function setLocale(locale, reload = () => window.location.reload()) {
  try { localStorage.setItem(LOCALE_KEY, locale) } catch { /* private mode: the choice lasts until reload only */ }
  reload()
}

/**
 * Pre-load the bundle for the given locale (and 'en' as fallback).
 * Call once at app startup before rendering any message strings.
 */
export async function initMessages(locale = storedLocale()) {
  _activeLocale = locale
  await _loadBundle('en')
  if (locale !== 'en') await _loadBundle(locale)
  _ready = true
}

/**
 * Format a message key with optional variable substitution.
 * Falls back to the key string itself if the bundle is not yet loaded.
 *
 * @param {string}  key        Message key, e.g. 'CTS_WF_VAULT_MISS'
 * @param {object}  [vars]     Variable map, e.g. { account_display: '****4521' }
 * @param {string}  [locale]   Override locale for this call; defaults to active locale
 * @returns {string}
 */
export function msg(key, vars, locale) {
  return _get(key, vars, locale ?? _activeLocale)
}

/**
 * Return the full entry object (text, severity, surface, variables) for a key.
 * Useful for determining severity-based styling in UI components.
 *
 * @param {string} key
 * @returns {{ text: string, severity: string, surface: string[], variables: string[] } | null}
 */
export function msgEntry(key) {
  const bundle = _bundles['en'] ?? {}
  return bundle[key] ?? null
}

/**
 * True once initMessages() has resolved.
 */
export function messagesReady() {
  return _ready
}
