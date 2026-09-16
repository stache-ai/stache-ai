import { describe, it, expect } from 'vitest'
import { fileFraction, overallPercent } from './progress.js'

describe('fileFraction', () => {
  it('maps uploading to the first half (0 -> 0.5)', () => {
    expect(fileFraction('uploading', 0)).toBe(0)
    expect(fileFraction('uploading', 50)).toBe(0.25)
    expect(fileFraction('uploading', 100)).toBe(0.5)
  })

  it('maps processing to the second half (0.5 -> 1)', () => {
    expect(fileFraction('processing', 0)).toBe(0.5)
    expect(fileFraction('processing', 80)).toBeCloseTo(0.9)
    expect(fileFraction('processing', 100)).toBe(1)
  })

  it('clamps out-of-range and non-numeric percents', () => {
    expect(fileFraction('uploading', -10)).toBe(0)
    expect(fileFraction('uploading', 150)).toBe(0.5)
    expect(fileFraction('uploading', undefined)).toBe(0)
    expect(fileFraction('processing', null)).toBe(0.5)
  })
})

describe('overallPercent', () => {
  it('is the running total across all files', () => {
    // file 2 of 5 (index 1) at 80% processing -> fraction 0.9 -> round((1+0.9)/5*100)
    expect(overallPercent(1, fileFraction('processing', 80), 5)).toBe(38)
    // single file uploading at 50% -> round((0+0.25)/1*100)
    expect(overallPercent(0, fileFraction('uploading', 50), 1)).toBe(25)
    // last file fully done -> 100
    expect(overallPercent(4, 1, 5)).toBe(100)
  })

  it('never goes backwards as a file advances upload -> process', () => {
    const seq = [
      overallPercent(0, fileFraction('uploading', 100), 1),
      overallPercent(0, fileFraction('processing', 0), 1),
      overallPercent(0, fileFraction('processing', 80), 1),
      overallPercent(0, fileFraction('processing', 100), 1),
    ]
    for (let i = 1; i < seq.length; i++) {
      expect(seq[i]).toBeGreaterThanOrEqual(seq[i - 1])
    }
  })

  it('returns 0 when there are no files', () => {
    expect(overallPercent(0, 0.5, 0)).toBe(0)
  })
})
