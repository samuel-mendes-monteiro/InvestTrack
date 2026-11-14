import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom has no layout, so it lacks ResizeObserver; Recharts' responsive
// container needs one to exist (it just measures 0 x 0 here).
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Like the Python suite, tests never hit the network: each one stubs fetch.
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
