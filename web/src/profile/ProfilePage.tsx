import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, call } from '../api/client'
import { useMe } from '../api/queries'

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
