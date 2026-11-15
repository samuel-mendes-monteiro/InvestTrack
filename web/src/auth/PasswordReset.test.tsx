import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test } from 'vitest'
import { resetSession } from '../api/session'
import App from '../App'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'

const NO_SESSION = { status: 401, body: { detail: { code: 'NOT_AUTHENTICATED', message: 'x' } } }

beforeEach(() => resetSession())

test('the login links to the forgot-password form, which sends the email', async () => {
  const api = fakeApi({ 'GET /auth/me': NO_SESSION, 'POST /auth/password-reset': { status: 204 } })
  const user = userEvent.setup()
  renderWithApp(<App />, { path: '/entrar' })

  await user.click(await screen.findByRole('link', { name: 'Esqueci minha senha' }))
  await user.type(screen.getByLabelText('E-mail'), ' ana@example.com ')
  await user.click(screen.getByRole('button', { name: 'Enviar link' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Se houver uma conta com ana@example.com')
  expect(await api.sent('POST /auth/password-reset')).toEqual([{ email: 'ana@example.com' }])
})

test('too many requests are explained', async () => {
  fakeApi({
    'GET /auth/me': NO_SESSION,
    'POST /auth/password-reset': {
      status: 429,
      body: { detail: { code: 'TOO_MANY_RESET_REQUESTS', message: 'x', retry_after: 1800 } },
    },
  })
  const user = userEvent.setup()
  renderWithApp(<App />, { path: '/esqueci-senha' })
  await user.type(await screen.findByLabelText('E-mail'), 'ana@example.com')
  await user.click(screen.getByRole('button', { name: 'Enviar link' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Tente de novo em 30 minutos')
})

test('the link from the email sets the new password', async () => {
  const api = fakeApi({ 'GET /auth/me': NO_SESSION, 'POST /auth/password-reset/confirm': { status: 204 } })
  const user = userEvent.setup()
  renderWithApp(<App />, { path: '/redefinir-senha#token=abc-123' })

  await user.type(await screen.findByLabelText(/^Nova senha/), 'a new one!')
  await user.type(screen.getByLabelText('Repita a nova senha'), 'a new one!')
  await user.click(screen.getByRole('button', { name: 'Salvar senha nova' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Senha alterada')
  expect(await api.sent('POST /auth/password-reset/confirm')).toEqual([{ token: 'abc-123', new_password: 'a new one!' }])
  await user.click(screen.getByRole('link', { name: 'Entrar' }))
  expect(await screen.findByRole('button', { name: 'Entrar' })).toBeInTheDocument()
})

test('different passwords are caught before calling the API', async () => {
  const api = fakeApi({ 'GET /auth/me': NO_SESSION })
  const user = userEvent.setup()
  renderWithApp(<App />, { path: '/redefinir-senha#token=abc-123' })
  await user.type(await screen.findByLabelText(/^Nova senha/), 'a new one!')
  await user.type(screen.getByLabelText('Repita a nova senha'), 'another one')
  await user.click(screen.getByRole('button', { name: 'Salvar senha nova' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('As senhas não são iguais.')
  expect(await api.sent('POST /auth/password-reset/confirm')).toEqual([])
})

test('an expired link offers a new one', async () => {
  fakeApi({
    'GET /auth/me': NO_SESSION,
    'POST /auth/password-reset/confirm': {
      status: 400,
      body: { detail: { code: 'INVALID_RESET_TOKEN', message: 'x' } },
    },
  })
  const user = userEvent.setup()
  renderWithApp(<App />, { path: '/redefinir-senha#token=old' })
  await user.type(await screen.findByLabelText(/^Nova senha/), 'a new one!')
  await user.type(screen.getByLabelText('Repita a nova senha'), 'a new one!')
  await user.click(screen.getByRole('button', { name: 'Salvar senha nova' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Esse link não vale mais')
  expect(screen.getByRole('link', { name: 'Pedir um novo link' })).toHaveAttribute('href', '/esqueci-senha')
})

test('a link without a token says so', async () => {
  fakeApi({ 'GET /auth/me': NO_SESSION })
  renderWithApp(<App />, { path: '/redefinir-senha' })
  expect(await screen.findByText(/Link incompleto/)).toBeInTheDocument()
  expect(screen.queryByLabelText(/^Nova senha/)).not.toBeInTheDocument()
})
