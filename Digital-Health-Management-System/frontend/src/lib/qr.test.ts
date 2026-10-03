import { afterEach, describe, expect, it, vi } from 'vitest'
import { publicProfileUrl } from './qr'

describe('publicProfileUrl', () => {
  afterEach(() => vi.unstubAllEnvs())

  it('builds the link from VITE_FRONTEND_URL and the uuid token', () => {
    vi.stubEnv('VITE_FRONTEND_URL', 'https://card.example.org/')
    expect(publicProfileUrl('6f1c2a3b-0000-4000-8000-000000000001'))
      .toBe('https://card.example.org/public-profile/6f1c2a3b-0000-4000-8000-000000000001')
  })

  it('falls back to the current address when the variable is not set', () => {
    vi.stubEnv('VITE_FRONTEND_URL', '')
    expect(publicProfileUrl('abc')).toBe(`${window.location.origin}/public-profile/abc`)
  })
})
