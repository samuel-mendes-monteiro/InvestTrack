import { beforeEach, expect, test, vi } from 'vitest'
import { api, call } from './client'
import { ApiError } from './errors'
import { getSession, markLoggedIn, resetSession } from './session'

function stubFetch(status: number, body?: unknown) {
  const fetch = vi.fn(async (_request: Request) =>
    body === undefined ? new Response(null, { status }) : Response.json(body, { status }),
  )
  vi.stubGlobal('fetch', fetch)
  return fetch
}

beforeEach(() => {
  resetSession()
  markLoggedIn()
})

test('calls go to /api on the same origin, with no token of their own', async () => {
  const fetch = stubFetch(200, { id: 1, email: 'ana@example.com' })
  await call(api.GET('/api/auth/me'))
  const request = fetch.mock.calls[0][0]
  expect(request.url).toBe(`${window.location.origin}/api/auth/me`)
  expect(request.headers.has('Authorization')).toBe(false) // the cookie travels by itself
})

test('a 401 ends the session', async () => {
  stubFetch(401, { detail: { code: 'NOT_AUTHENTICATED', message: 'Not authenticated' } })
  await expect(call(api.GET('/api/portfolio'))).rejects.toThrow('Sua sessão expirou. Entre de novo.')
  expect(getSession()).toMatchObject({ status: 'out', notice: 'Sua sessão expirou. Entre de novo.' })
})

test('a 401 from the login itself is a wrong password, not a lost session', async () => {
  stubFetch(401, { detail: { code: 'INVALID_CREDENTIALS', message: 'Invalid' } })
  const login = call(api.POST('/api/auth/login', { body: { email: 'a@b.com', password: 'x' } }))
  await expect(login).rejects.toThrow('E-mail ou senha incorretos.')
  expect(getSession().status).toBe('in')
})

test('domain errors are translated from their code, with their fields', async () => {
  stubFetch(409, {
    detail: {
      code: 'INSUFFICIENT_POSITION',
      message: 'english fallback',
      ticker: 'PETR4',
      available: '100.00000000',
      requested: '150',
    },
  })
  const error = await call(api.GET('/api/portfolio')).catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  expect(error).toMatchObject({
    status: 409,
    code: 'INSUFFICIENT_POSITION',
    message: 'Você tem 100 PETR4 nessa data e tentou vender 150.',
  })
})

test('the login lockout says how long to wait, rounded up to minutes', async () => {
  stubFetch(429, { detail: { code: 'TOO_MANY_ATTEMPTS', message: '', retry_after: 61 } })
  const login = call(api.POST('/api/auth/login', { body: { email: 'a@b.com', password: 'x' } }))
  await expect(login).rejects.toThrow('Tente de novo em 2 minutos.')
})

test('validation errors name the field in Portuguese', async () => {
  stubFetch(422, {
    detail: [
      { loc: ['body', 'price'], type: 'greater_than_equal', msg: '', ctx: { ge: 0 } },
      { loc: ['body', 'ticker'], type: 'missing', msg: 'Field required' },
    ],
  })
  await expect(call(api.GET('/api/portfolio'))).rejects.toThrow(
    'Preço não pode ser negativo; Ticker é obrigatório.',
  )
})

test('an unknown code falls back to the English message', async () => {
  stubFetch(400, { detail: { code: 'SOMETHING_NEW', message: 'Something new happened' } })
  await expect(call(api.GET('/api/portfolio'))).rejects.toThrow('Something new happened')
})

test('an unreachable API is a NETWORK error', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
  await expect(call(api.GET('/api/health'))).rejects.toMatchObject({ code: 'NETWORK' })
})

test('204 No Content returns undefined', async () => {
  stubFetch(204)
  await expect(call(api.POST('/api/auth/logout'))).resolves.toBeUndefined()
})
