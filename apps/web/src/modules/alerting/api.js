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
