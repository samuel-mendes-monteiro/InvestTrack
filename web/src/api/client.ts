import createClient, { type Middleware } from 'openapi-fetch'
import { ApiError, toApiError } from './errors'
import type { paths } from './schema'
import { expireSession } from './session'

// Where a 401 means "wrong password", not "your session ended".
const LOGIN_PATHS = ['/api/auth/login', '/api/auth/register']

// No header to add: the browser sends the session cookie by itself.
const auth: Middleware = {
  onResponse({ response, schemaPath }) {
    // An expired or revoked session: the app (which watches the session
    // through useSession) goes back to the login screen by itself.
    if (response.status === 401 && !LOGIN_PATHS.includes(schemaPath)) expireSession()
    return response
  },
}

// Every call is typed from the API's OpenAPI schema: a wrong path, a missing
// field or a misread response is a compile error, not a bug found in the browser.
// Paths include /api, where the API lives; the page is on the same origin
// (Vite forwards /api to uvicorn in development).
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Looked up on every call (not captured once) so tests can stub fetch.
  fetch: (request) => globalThis.fetch(request),
})
api.use(auth)

type Result<T> = { data?: T; error?: unknown; response: Response }

/**
 * Await an api.GET/POST/... call and return its data, or throw an ApiError
 * with a Portuguese message. TanStack Query shows whatever a query throws.
 *
 *   const portfolio = await call(api.GET('/api/portfolio'))
 */
export async function call<T>(request: Promise<Result<T>>): Promise<T> {
  let result: Result<T>
  try {
    result = await request
  } catch {
    throw new ApiError('Não foi possível falar com a API. Ela está rodando?', 0, 'NETWORK')
  }
  const { data, error, response } = result
  if (!response.ok) {
    // The dev proxy answers 502 with an empty body when uvicorn is down.
    if (response.status === 502 || response.status === 504) {
      throw new ApiError('Não foi possível falar com a API. Ela está rodando?', response.status, 'NETWORK')
    }
    throw toApiError(response.status, error)
  }
  return data as T // undefined for 204 No Content
}
