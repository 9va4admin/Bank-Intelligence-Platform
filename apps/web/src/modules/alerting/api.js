// One way for every alerting screen to talk to the API: session cookie, CSRF on writes, JSON in and out, and an error that carries the server's reason.
import { csrfHeader } from '../../shared/api/csrf'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : (detail?.message ?? String(status)))
    this.status = status
    this.detail = detail
    this.codes = Array.isArray(detail?.codes) ? detail.codes : []     // e.g. the reasons a policy was refused
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(method !== 'GET' ? csrfHeader() : {}) }
  const res = await fetch(`${API_BASE}${path}`, { method, credentials: 'include', headers, body: body !== undefined ? JSON.stringify(body) : undefined })
  let data = null
  try { data = await res.json() } catch { /* an empty body is fine */ }
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? null)
  return data ?? {}
}

export function query(params) {
  const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
  return q.length ? `?${q.join('&')}` : ''
}

// A file download (a CSV report): the same session and error handling, but the answer is a file, not JSON. The browser is asked to save it under the server's file name.
export async function download(path, fallbackName = 'report.csv') {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' })
  if (!res.ok) {
    let data = null
    try { data = await res.json() } catch { /* no body */ }
    throw new ApiError(res.status, data?.detail ?? null)
  }
  const blob = await res.blob()
  const match = /filename="?([^";]+)"?/.exec(res.headers?.get?.('content-disposition') ?? '')
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = match ? match[1] : fallbackName
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
