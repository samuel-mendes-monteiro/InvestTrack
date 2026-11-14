import { beforeEach, expect, test, vi } from 'vitest'
import { api, call } from './client'
import { ApiError } from './errors'
import { getToken, setToken } from './session'

function stubFetch(status: number, body?: unknown) {
  const fetch = vi.fn(async (_request: Request) =>
    body === undefined ? new Response(null, { status }) : Response.json(body, { status }),
  )
  vi.stubGlobal('fetch', fetch)
  return fetch
}

beforeEach(() => setToken(null))

test('sends the session token as a Bearer header', async () => {
  setToken('abc')
  const fetch = stubFetch(200, { id: 1, email: 'ana@example.com' })
  await call(api.GET('/auth/me'))
  expect(fetch.mock.calls[0][0].headers.get('Authorization')).toBe('Bearer abc')
})

test('sends no header when logged out', async () => {
  const fetch = stubFetch(200, { status: 'ok' })
  await call(api.GET('/health'))
  expect(fetch.mock.calls[0][0].headers.has('Authorization')).toBe(false)
})

test('a 401 ends the session', async () => {
  setToken('expired')
  stubFetch(401, { detail: { code: 'NOT_AUTHENTICATED', message: 'Not authenticated' } })
  await expect(call(api.GET('/portfolio'))).rejects.toThrow('Sua sessão expirou. Entre de novo.')
  expect(getToken()).toBeNull()
})

test('a 401 from the login itself is a wrong password, not a lost session', async () => {
  setToken('still-valid')
  stubFetch(401, { detail: { code: 'INVALID_CREDENTIALS', message: 'Invalid' } })
  const login = call(api.POST('/auth/login', { body: { email: 'a@b.com', password: 'x' } }))
  await expect(login).rejects.toThrow('E-mail ou senha incorretos.')
  expect(getToken()).toBe('still-valid')
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
  const error = await call(api.GET('/portfolio')).catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  expect(error).toMatchObject({
    status: 409,
    code: 'INSUFFICIENT_POSITION',
    message: 'Você tem 100 PETR4 nessa data e tentou vender 150.',
  })
})

test('the login lockout says how long to wait, rounded up to minutes', async () => {
  stubFetch(429, { detail: { code: 'TOO_MANY_ATTEMPTS', message: '', retry_after: 61 } })
  const login = call(api.POST('/auth/login', { body: { email: 'a@b.com', password: 'x' } }))
  await expect(login).rejects.toThrow('Tente de novo em 2 minutos.')
})

test('validation errors name the field in Portuguese', async () => {
  stubFetch(422, {
    detail: [
      { loc: ['body', 'price'], type: 'greater_than_equal', msg: '', ctx: { ge: 0 } },
      { loc: ['body', 'ticker'], type: 'missing', msg: 'Field required' },
    ],
  })
  await expect(call(api.GET('/portfolio'))).rejects.toThrow(
    'Preço não pode ser negativo; Ticker é obrigatório.',
  )
})

test('an unknown code falls back to the English message', async () => {
  stubFetch(400, { detail: { code: 'SOMETHING_NEW', message: 'Something new happened' } })
  await expect(call(api.GET('/portfolio'))).rejects.toThrow('Something new happened')
})

test('an unreachable API is a NETWORK error', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
  await expect(call(api.GET('/health'))).rejects.toMatchObject({ code: 'NETWORK' })
})

test('204 No Content returns undefined', async () => {
  stubFetch(204)
  await expect(call(api.POST('/auth/logout'))).resolves.toBeUndefined()
})
