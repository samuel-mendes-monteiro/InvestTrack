import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Like the Python suite, tests never hit the network: each one stubs fetch.
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
