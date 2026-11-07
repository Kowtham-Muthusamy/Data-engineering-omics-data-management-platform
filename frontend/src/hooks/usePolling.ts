import { useCallback, useEffect, useRef, useState } from 'react'

/** Fetches on mount and every `intervalMs`; `reload()` forces a refresh. Keeps the last good data on error. */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs = 3000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const reload = useCallback(async () => {
    try {
      setData(await fetcherRef.current())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let alive = true
    const tick = () => {
      if (alive) void reload()
    }
    tick()
    const id = intervalMs > 0 ? window.setInterval(tick, intervalMs) : undefined
    return () => {
      alive = false
      if (id) window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, reload, ...deps])

  return { data, error, loading, reload }
}
