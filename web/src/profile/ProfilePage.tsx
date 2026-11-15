import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, call } from '../api/client'
import { useMe } from '../api/queries'
import { markLoggedOut } from '../api/session'
import { Modal } from '../components/Modal'

/** The account: who is logged in, and changing the password. */
export function ProfilePage() {
  const me = useMe()

  if (me.isPending) return <p className="muted">Carregando o perfil…</p>
  if (me.isError) return <p className="alert error">{me.error.message}</p>

  const { email, created_at } = me.data
  // A date, not money: the browser's own formatting, in the user's time zone.
  const since = new Date(created_at).toLocaleDateString('pt-BR', { day: 'numeric', month: 'long', year: 'numeric' })

  return (
    <div className="profile">
      <h1>Perfil</h1>
      <section className="card profile-account" aria-label="Conta">
        <span className="avatar large" aria-hidden="true">
          {email[0].toUpperCase()}
        </span>
        <div>
          <div className="profile-email">{email}</div>
          <div className="muted">Membro desde {since}</div>
        </div>
      </section>
      <PasswordForm />
      <DeleteAccount />
    </div>
  )
}

function PasswordForm() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const mutation = useMutation({
    mutationFn: async () => {
      if (next !== repeat) throw new Error('As senhas novas não são iguais.')
      await call(api.POST('/api/auth/password', { body: { current_password: current, new_password: next } }))
    },
    // Never keep passwords around longer than needed, whatever the outcome.
    onSettled: () => {
      setCurrent('')
      setNext('')
      setRepeat('')
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  return (
    <section className="card" aria-labelledby="password-title">
      <h2 id="password-title">Trocar senha</h2>
      <form onSubmit={submit} className="stack">
        <label>
          Senha atual
          <input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <div className="grid2">
          <label>
            Nova senha
            <input
              type="password"
              autoComplete="new-password"
              required
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <small>Mínimo de 8 caracteres.</small>
          </label>
          <label>
            Repita a nova senha
            <input
              type="password"
              autoComplete="new-password"
              required
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </label>
        </div>
        {mutation.isError && (
          <p className="alert error" role="alert">
            {mutation.error.message}
          </p>
        )}
        {mutation.isSuccess && (
          <p className="alert success" role="status">
            Senha alterada. As sessões abertas em outros aparelhos foram encerradas.
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={mutation.isPending}>
            {mutation.isPending ? 'Salvando…' : 'Trocar senha'}
          </button>
        </div>
      </form>
    </section>
  )
}

/** The way out: everything goes, after the password. There is no undo. */
function DeleteAccount() {
  const [confirming, setConfirming] = useState(false)

  return (
    <section className="card danger-zone" aria-labelledby="delete-title">
      <h2 id="delete-title">Excluir conta</h2>
      <p className="muted">
        Apaga a conta e tudo o que está nela: operações, proventos registrados, renda fixa e custos de bonificação. Não
        dá para desfazer.
      </p>
      <div className="actions">
        <button className="danger" onClick={() => setConfirming(true)}>
          Excluir conta…
        </button>
      </div>
      {confirming && <DeleteAccountDialog onClose={() => setConfirming(false)} />}
    </section>
  )
}

function DeleteAccountDialog({ onClose }: { onClose: () => void }) {
  const [password, setPassword] = useState('')
  const mutation = useMutation({
    mutationFn: () => call(api.POST('/api/auth/delete-account', { body: { password } })),
    // The session is gone with the account: back to the product page.
    onSuccess: () => markLoggedOut(),
    onSettled: () => setPassword(''),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  return (
    <Modal title="Excluir a conta?" onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <p className="alert error">
          Todas as suas operações, proventos registrados, aplicações de renda fixa e custos de bonificação serão apagados
          para sempre.
        </p>
        <label>
          Digite sua senha para confirmar
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {mutation.isError && (
          <p className="alert error" role="alert">
            {mutation.error.message}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" className="danger-solid" disabled={mutation.isPending}>
            {mutation.isPending ? 'Excluindo…' : 'Excluir conta definitivamente'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
