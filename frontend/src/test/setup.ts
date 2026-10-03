import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { server } from './server'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => { server.resetHandlers(); cleanup(); localStorage.clear() })
afterAll(() => server.close())

// jsdom lacks these browser APIs used by charts and file previews.
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal('ResizeObserver', ResizeObserverStub)
URL.createObjectURL = vi.fn(() => 'blob:report')
URL.revokeObjectURL = vi.fn()
