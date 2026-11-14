import createClient from 'openapi-fetch'
import type { paths } from './schema'

// Every call is typed from the API's OpenAPI schema: a wrong path, a missing
// field or a misread response is a compile error, not a bug found in the browser.
// The /api prefix is the same-origin route set up in vite.config.ts.
export const api = createClient<paths>({
  baseUrl: `${window.location.origin}/api`,
  // Looked up on every call (not captured once) so tests can stub fetch.
  fetch: (request) => globalThis.fetch(request),
})
