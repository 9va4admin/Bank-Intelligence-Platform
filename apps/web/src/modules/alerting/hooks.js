// Loading data for a screen: loads, refreshes on a timer, and reports a failure instead of showing an empty screen.
import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from './api'
import { ALERTING_REFRESH_SECONDS } from './config'

export function useLoad(path, { refreshSeconds = ALERTING_REFRESH_SECONDS } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(Boolean(path))
  const alive = useRef(true)

  const reload = useCallback(async () => {
    if (!path) { setData(null); setLoading(false); return null }
    try {
      const result = await api(path)
      if (alive.current) { setData(result); setError(null) }
      return result
    } catch (e) {
      if (alive.current) setError(e)
      return null
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [path])

  useEffect(() => {
    alive.current = true
    reload()
    const timer = path && refreshSeconds > 0 ? setInterval(reload, refreshSeconds * 1000) : null
    return () => { alive.current = false; if (timer) clearInterval(timer) }
  }, [reload, path, refreshSeconds])

  return { data, error, loading, reload }
}
