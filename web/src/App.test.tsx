import { act, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test } from 'vitest'
import { expireSession, getSession, resetSession } from './api/session'
import App from './App'
import { fakeApi } from './test/fakeApi'
import { renderWithApp } from './test/render'

const ME = { status: 200, body: { id: 1, email: 'ana@example.com', created_at: '2026-03-15T12:00:00Z' } }
const NO_SESSION = { status: 401, body: { detail: { code: 'NOT_AUTHENTICATED', message: 'x' } } }
const SESSION = { status: 200, body: { expires_at: '2026-12-14T00:00:00Z' } }

beforeEach(() => resetSession())

test('a cookie that is still valid goes straight to the app', async () => {
  fakeApi({ 'GET /auth/me': ME })
  renderWithApp(<App />)
  expect(await screen.findByRole('button', { name: 'Sair' })).toBeInTheDocument()
  expect(getSession().status).toBe('in')
})

test('without a session a visitor sees the product page, with the ways in', async () => {
  fakeApi({ 'GET /auth/me': NO_SESSION })
  renderWithApp(<App />)
  expect(await screen.findByRole('heading', { level: 1, name: /numa carteira só/ })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Entrar' })).toHaveAttribute('href', '/entrar')
  expect(screen.queryByText(/sessão expirou/)).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('link', { name: 'Entrar' }))
  expect(await screen.findByRole('button', { name: 'Entrar' })).toBeInTheDocument()
})

test('the sign-up link opens the form on the Criar conta tab', async () => {
  fakeApi({ 'GET /auth/me': NO_SESSION })
  renderWithApp(<App />, { path: '/criar-conta' })
  expect(await screen.findByRole('tab', { name: 'Criar conta' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.getByLabelText('Repita a senha')).toBeInTheDocument()
})

test('an unknown address without a session goes to the product page', async () => {
  fakeApi({ 'GET /auth/me': NO_SESSION })
  renderWithApp(<App />, { path: '/rentabilidade' })
  expect(await screen.findByRole('heading', { level: 1, name: /numa carteira só/ })).toBeInTheDocument()
})

test('an unreachable API is said plainly, with a retry', async () => {
  let up = false
  fakeApi({ 'GET /auth/me': () => (up ? ME : { status: 502 }) })
  renderWithApp(<App />)
  expect(await screen.findByText(/Não foi possível falar com a API/)).toBeInTheDocument()

  up = true
  await userEvent.click(screen.getByRole('button', { name: 'Tentar de novo' }))
  expect(await screen.findByRole('button', { name: 'Sair' })).toBeInTheDocument()
})

test('logging in opens the app', async () => {
  let loggedIn = false
  const api = fakeApi({
    'GET /auth/me': () => (loggedIn ? ME : NO_SESSION),
    'POST /auth/login': () => {
      loggedIn = true
      return SESSION
    },
  })
  renderWithApp(<App />, { path: '/entrar' })
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('E-mail'), ' ana@example.com ')
  await user.type(screen.getByLabelText('Senha'), 'segredo123')
  await user.click(screen.getByRole('button', { name: 'Entrar' }))

  expect(await screen.findByText('ana@example.com')).toBeInTheDocument()
  expect(await api.sent('POST /auth/login')).toEqual([{ email: 'ana@example.com', password: 'segredo123' }])
})

test('a wrong password says so and clears the password field', async () => {
  fakeApi({
    'GET /auth/me': NO_SESSION,
    'POST /auth/login': { status: 401, body: { detail: { code: 'INVALID_CREDENTIALS', message: 'x' } } },
  })
  renderWithApp(<App />, { path: '/entrar' })
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('E-mail'), 'ana@example.com')
  await user.type(screen.getByLabelText('Senha'), 'errada123')
  await user.click(screen.getByRole('button', { name: 'Entrar' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('E-mail ou senha incorretos.')
  expect(screen.getByLabelText('Senha')).toHaveValue('')
  expect(getSession().status).toBe('out')
})

test('creating an account logs straight in', async () => {
  fakeApi({ 'GET /auth/me': NO_SESSION })
  renderWithApp(<App />, { path: '/entrar' })
  await screen.findByRole('button', { name: 'Entrar' })
  const api = fakeApi({
    'POST /auth/register': { status: 201, body: ME.body },
    'POST /auth/login': SESSION,
    'GET /auth/me': ME,
  })
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
  fakeApi({ 'GET /auth/me': NO_SESSION })
  renderWithApp(<App />, { path: '/entrar' })
  await screen.findByRole('button', { name: 'Entrar' })
  const api = fakeApi({})
  const user = userEvent.setup()
  await user.click(screen.getByRole('tab', { name: 'Criar conta' }))
  await user.type(screen.getByLabelText('E-mail'), 'ana@example.com')
  await user.type(screen.getByLabelText(/^Senha/), 'segredo123')
  await user.type(screen.getByLabelText('Repita a senha'), 'segredo124')
  await user.click(screen.getByRole('button', { name: 'Criar conta' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('As senhas não são iguais.')
  expect(api.requests).toHaveLength(0)
})

test('logging out ends the session on the server and empties the cache', async () => {
  const api = fakeApi({ 'GET /auth/me': ME, 'POST /auth/logout': { status: 204 } })
  const { client } = renderWithApp(<App />)
  await screen.findByText('ana@example.com')

  await userEvent.click(screen.getByRole('button', { name: 'Sair' }))

  expect(await screen.findByRole('link', { name: 'Entrar' })).toBeInTheDocument()
  expect(api.requests.some((r) => new URL(r.url).pathname === '/api/auth/logout')).toBe(true)
  expect(client.getQueryCache().getAll()).toHaveLength(0)
})

test('an expired session goes back to the login screen with a notice', async () => {
  fakeApi({ 'GET /auth/me': ME })
  renderWithApp(<App />)
  await screen.findByRole('button', { name: 'Sair' })

  act(() => expireSession()) // what a 401 from any call does
  expect(await screen.findByText('Sua sessão expirou. Entre de novo.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Entrar' })).toBeInTheDocument()
})

test('the account button in the bar opens the profile', async () => {
  fakeApi({ 'GET /auth/me': ME })
  renderWithApp(<App />)
  await userEvent.click(await screen.findByRole('link', { name: 'Perfil de ana@example.com' }))
  expect(await screen.findByRole('heading', { name: 'Perfil' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Trocar senha' })).toBeInTheDocument()
})
