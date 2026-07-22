import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useDebouncedValue } from './useDebouncedValue'

describe('useDebouncedValue', () => {
  afterEach(() => vi.useRealTimers())

  it('waits for typing to settle before exposing a food query', () => {
    vi.useFakeTimers()
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 350),
      { initialProps: { value: 'gr' } },
    )

    rerender({ value: 'greek yogurt' })
    expect(result.current).toBe('gr')
    act(() => vi.advanceTimersByTime(349))
    expect(result.current).toBe('gr')
    act(() => vi.advanceTimersByTime(1))
    expect(result.current).toBe('greek yogurt')
  })
})
