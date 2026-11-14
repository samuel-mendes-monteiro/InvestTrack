import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test } from 'vitest'
import { getToken, setToken } from './api/session'
import App from './App'
import { fakeApi } from './test/fakeApi'

const ME = { status: 200, body: { id: 1, email: 'ana@example.com' } }
const SESSION = { status: 200, body: { token: 'tok-1', expires_at: '2026-12-14T00:00:00Z' } }

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
  return client
}

beforeEach(() => setToken(null))

test('logging in shows the user and keeps the token', async () => {
  const api = fakeApi({ 'POST /auth/login': SESSION, 'GET /auth/me': ME })
  renderApp()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('E-mail'), ' ana@example.com ')
  await user.type(screen.getByLabelText('Senha'), 'segredo123')
  await user.click(screen.getByRole('button', { name: 'Entrar' }))

  expect(await screen.findByText('ana@example.com')).toBeInTheDocument()
  expect(getToken()).toBe('tok-1')
  expect(await api.sent('POST /auth/login')).toEqual([{ email: 'ana@example.com', password: 'segredo123' }])
})

test('a wrong password says so and clears the password field', async () => {
  fakeApi({
    'POST /auth/login': { status: 401, body: { detail: { code: 'INVALID_CREDENTIALS', message: 'x' } } },
  })
  renderApp()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('E-mail'), 'ana@example.com')
  await user.type(screen.getByLabelText('Senha'), 'errada123')
  await user.click(screen.getByRole('button', { name: 'Entrar' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('E-mail ou senha incorretos.')
  expect(screen.getByLabelText('Senha')).toHaveValue('')
  expect(getToken()).toBeNull()
})

test('creating an account logs straight in', async () => {
  const api = fakeApi({
    'POST /auth/register': { status: 201, body: ME.body },
    'POST /auth/login': SESSION,
    'GET /auth/me': ME,
  })
  renderApp()
  const user = userEvent.setup()
  await user.click(screen.getByRole('tab', { name: 'Criar conta' }))
  await user.type(screen.getByLabelText('E-mail'), 'ana@example.com')
  await user.type(screen.getByLabelText(/^Senha/), 'segredo123')
  await user.type(screen.getByLabelText('Repita a senha'), 'segredo123')
  await user.click(screen.getByRole('button', { name: 'Criar conta' }))

  expect(await screen.findByText('ana@example.com')).toBeInTheDocument()
  expect(await api.sent('POST /auth/register')).toHaveLength(1)
})

test('different passwords never reach the API', async () => {
  const api = fakeApi({})
  renderApp()
  const user = userEvent.setup()
  await user.click(screen.getByRole('tab', { name: 'Criar conta' }))
  await user.type(screen.getByLabelText('E-mail'), 'ana@example.com')
  await user.type(screen.getByLabelText(/^Senha/), 'segredo123')
  await user.type(screen.getByLabelText('Repita a senha'), 'segredo124')
  await user.click(screen.getByRole('button', { name: 'Criar conta' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('As senhas não são iguais.')
  expect(api.requests).toHaveLength(0)
})

test('logging out revokes the token and empties the cache', async () => {
  setToken('tok-1')
  const api = fakeApi({ 'GET /auth/me': ME, 'POST /auth/logout': { status: 204 } })
  const client = renderApp()
  await screen.findByText('ana@example.com')

  await userEvent.click(screen.getByRole('button', { name: 'Sair' }))

  expect(await screen.findByRole('button', { name: 'Entrar' })).toBeInTheDocument()
  expect(api.requests.at(-1)?.headers.get('Authorization')).toBe('Bearer tok-1')
  expect(getToken()).toBeNull()
  expect(client.getQueryCache().getAll()).toHaveLength(0)
})

test('an expired session goes back to the login screen with a notice', async () => {
  setToken('old')
  fakeApi({ 'GET /auth/me': { status: 401, body: { detail: { code: 'NOT_AUTHENTICATED', message: 'x' } } } })
  renderApp()
  expect(await screen.findByText('Sua sessão expirou. Entre de novo.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Entrar' })).toBeInTheDocument()
})

test('a notice goes away once the user logs in again', async () => {
  setToken('old')
  fakeApi({ 'GET /auth/me': { status: 401, body: { detail: { code: 'NOT_AUTHENTICATED', message: 'x' } } } })
  renderApp()
  await screen.findByText('Sua sessão expirou. Entre de novo.')
  act(() => setToken('new'))
  act(() => setToken(null))
  expect(screen.queryByText('Sua sessão expirou. Entre de novo.')).not.toBeInTheDocument()
})
