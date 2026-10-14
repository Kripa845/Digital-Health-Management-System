import { describe, expect, it } from 'vitest'
import { fullMatrix, saatyLabel, upperOf } from './admin-utils'

describe('AHP comparison helpers', () => {
  it('fills the lower triangle with reciprocals and the diagonal with 1', () => {
    const m = fullMatrix(3, { '0-1': '3', '0-2': '1/5', '1-2': '1' })
    expect(m).toEqual([
      [1, 3, 1 / 5],
      [1 / 3, 1, 1],
      [5, 1, 1],
    ])
  })

  it('treats unanswered pairs as equal', () => {
    expect(fullMatrix(2, {})).toEqual([[1, 1], [1, 1]])
  })

  it('reads a stored matrix back as scale values, including reciprocals', () => {
    expect(upperOf([[1, 3, 0.2], [1 / 3, 1, 1], [5, 1, 1]])).toEqual({ '0-1': '3', '0-2': '1/5', '1-2': '1' })
    expect(upperOf([[1, 2.9], [1 / 2.9, 1]])).toEqual({ '0-1': '3' })   // nearest value on the scale
  })

  it('names which side a value favours', () => {
    expect(saatyLabel('5', 'Experience', 'Caseload')).toBe('5 · Experience strongly more important')
    expect(saatyLabel('1/3', 'Experience', 'Caseload')).toBe('1/3 · Caseload moderately more important')
    expect(saatyLabel('1', 'Experience', 'Caseload')).toBe('1 · equally important')
  })
})
