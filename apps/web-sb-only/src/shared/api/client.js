import { BANK_CONFIG } from '../config/bank.config'

async function request(path, options = {}) {
  const res = await fetch(`${BANK_CONFIG.api_base}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Bank-Id': BANK_CONFIG.bank_id,
      ...options.headers,
    },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }))
    throw Object.assign(new Error(err.message ?? 'API error'), { status: res.status, body: err })
  }
  return res.json()
}

export const api = {
  get:    (path, opts)         => request(path, { method: 'GET', ...opts }),
  post:   (path, body, opts)   => request(path, { method: 'POST',  body: JSON.stringify(body), ...opts }),
  patch:  (path, body, opts)   => request(path, { method: 'PATCH', body: JSON.stringify(body), ...opts }),
}
