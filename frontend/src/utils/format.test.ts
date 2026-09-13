import { describe, expect, it } from 'vitest'
import { formatStageDuration } from './format'

describe('formatStageDuration', () => {
  it('keeps sub-second durations precise', () => {
    expect(formatStageDuration(24)).toBe('24 毫秒')
  })

  it('formats seconds without inventing minutes', () => {
    expect(formatStageDuration(12_400)).toBe('12 秒')
    expect(formatStageDuration(60_000)).toBe('1 分 00 秒')
  })
})
