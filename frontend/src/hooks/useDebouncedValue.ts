import { useEffect, useState } from 'react'

export function useDebouncedValue<T>(value: T, delayMilliseconds = 350): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMilliseconds)
    return () => window.clearTimeout(timer)
  }, [delayMilliseconds, value])

  return debounced
}
