import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { getSession, markLoggedIn, resetSession } from '../api/session'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { ProfilePage } from './ProfilePage'

const ME = { body: { id: 1, email: 'ana@example.com', created_at: '2026-03-15T12:00:00Z' } }

async function fill(current: string, next: string, repeat = next) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('Senha atual'), current)
  await user.type(screen.getByLabelText(/^Nova senha/), next)
  await user.type(screen.getByLabelText('Repita a nova senha'), repeat)
  await user.click(screen.getByRole('button', { name: 'Trocar senha' }))
}

test('shows the account and since when it exists', async () => {
  fakeApi({ 'GET /auth/me': ME })
  renderWithApp(<ProfilePage />)
  expect(await screen.findByText('ana@example.com')).toBeInTheDocument()
  expect(screen.getByText('Membro desde 15 de março de 2026')).toBeInTheDocument()
})

test('changes the password and clears the fields', async () => {
  const api = fakeApi({ 'GET /auth/me': ME, 'POST /auth/password': { status: 204 } })
  renderWithApp(<ProfilePage />)
  await fill('long enough', 'a new one!')

  expect(await screen.findByRole('status')).toHaveTextContent('Senha alterada.')
  expect(await api.sent('POST /auth/password')).toEqual([
    { current_password: 'long enough', new_password: 'a new one!' },
  ])
  expect(screen.getByLabelText('Senha atual')).toHaveValue('')
})

test('a wrong current password says so', async () => {
  fakeApi({
    'GET /auth/me': ME,
    'POST /auth/password': { status: 403, body: { detail: { code: 'WRONG_PASSWORD', message: 'x' } } },
  })
  renderWithApp(<ProfilePage />)
  await fill('wrong one', 'a new one!')
  expect(await screen.findByRole('alert')).toHaveTextContent('A senha atual está incorreta.')
})

test('different new passwords never reach the API', async () => {
  const api = fakeApi({ 'GET /auth/me': ME })
  renderWithApp(<ProfilePage />)
  await fill('long enough', 'a new one!', 'a new one?')
  expect(await screen.findByRole('alert')).toHaveTextContent('As senhas novas não são iguais.')
  expect(api.requests.filter((r) => r.method === 'POST')).toHaveLength(0)
})

test('deleting the account asks for the password, then logs out', async () => {
  resetSession()
  markLoggedIn()
  let wrongOnce = true
  const api = fakeApi({
    'GET /auth/me': ME,
    'POST /auth/delete-account': () => {
      if (wrongOnce) {
        wrongOnce = false
        return { status: 403, body: { detail: { code: 'WRONG_PASSWORD', message: 'x' } } }
      }
      return { status: 204 }
    },
  })
  renderWithApp(<ProfilePage />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Excluir conta…' }))
  const dialog = screen.getByRole('dialog', { name: 'Excluir a conta?' })
  await user.type(within(dialog).getByLabelText(/Digite sua senha/), 'wrong one')
  await user.click(within(dialog).getByRole('button', { name: 'Excluir conta definitivamente' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('A senha atual está incorreta.')
  expect(getSession().status).toBe('in') // a wrong password is not a logout

  await user.type(within(dialog).getByLabelText(/Digite sua senha/), 'long enough')
  await user.click(within(dialog).getByRole('button', { name: 'Excluir conta definitivamente' }))
  await vi.waitFor(() => expect(getSession().status).toBe('out'))
  expect(await api.sent('POST /auth/delete-account')).toEqual([{ password: 'wrong one' }, { password: 'long enough' }])
})
