import createClient, { type Middleware } from 'openapi-fetch'
import { ApiError, toApiError } from './errors'
import type { paths } from './schema'
import { expireSession, getToken } from './session'

// Where a 401 means "wrong password", not "your session ended".
const LOGIN_PATHS = ['/auth/login', '/auth/register']

const auth: Middleware = {
  onRequest({ request }) {
    const token = getToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ response, schemaPath }) {
    // An expired or revoked session: forget the token, and the app (which
    // watches it through useSession) goes back to the login screen by itself.
    if (response.status === 401 && !LOGIN_PATHS.includes(schemaPath)) expireSession()
    return response
  },
}

// Every call is typed from the API's OpenAPI schema: a wrong path, a missing
// field or a misread response is a compile error, not a bug found in the browser.
// The /api prefix is the same-origin route set up in vite.config.ts.
export const api = createClient<paths>({
  baseUrl: `${window.location.origin}/api`,
  // Looked up on every call (not captured once) so tests can stub fetch.
  fetch: (request) => globalThis.fetch(request),
})
api.use(auth)

type Result<T> = { data?: T; error?: unknown; response: Response }

/**
 * Await an api.GET/POST/... call and return its data, or throw an ApiError
 * with a Portuguese message. TanStack Query shows whatever a query throws.
 *
 *   const portfolio = await call(api.GET('/portfolio'))
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
