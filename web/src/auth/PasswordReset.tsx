import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'
import { api, call } from '../api/client'
import { BrandTitle } from './LoginPage'

/** /esqueci-senha: asks for the email that gets the link. */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const mutation = useMutation({
    mutationFn: () => call(api.POST('/api/auth/password-reset', { body: { email: email.trim() } })),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  return (
    <main className="narrow">
      <BrandTitle />
      <h2>Esqueci minha senha</h2>
      {mutation.isSuccess ? (
        // The API answers the same whether the email has an account or not,
        // so this can't say "sent" for sure either.
        <div className="stack">
          <p className="alert success" role="status">
            Se houver uma conta com {email.trim()}, enviamos um link para criar uma senha nova. Ele vale por 30
            minutos. Confira também a caixa de spam.
          </p>
          <Link to="/entrar">Voltar para o login</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="stack">
          <p className="muted">Digite o e-mail da sua conta e enviaremos um link para criar uma senha nova.</p>
          <label>
            E-mail
            <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          {mutation.isError && <p className="alert error" role="alert">{mutation.error.message}</p>}
          <button type="submit" className="primary" disabled={mutation.isPending}>
            {mutation.isPending ? 'Enviando…' : 'Enviar link'}
          </button>
          <Link to="/entrar" className="center">
            Voltar para o login
          </Link>
        </form>
      )}
    </main>
  )
}

/** The token comes in the fragment (#token=…), which the browser never sends to a server. */
function tokenFrom(hash: string): string | null {
  return new URLSearchParams(hash.replace(/^#/, '')).get('token')
}

/** /redefinir-senha#token=…: the page the email links to. */
export function ResetPasswordPage() {
  const token = tokenFrom(useLocation().hash)
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const mutation = useMutation({
    mutationFn: async () => {
      if (password !== repeat) throw new Error('As senhas não são iguais.')
      await call(api.POST('/api/auth/password-reset/confirm', { body: { token: token ?? '', new_password: password } }))
    },
    onSettled: () => {
      setPassword('')
      setRepeat('')
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  let content
  if (!token) {
    content = (
      <div className="stack">
        <p className="alert error">Link incompleto. Abra o link do e-mail de novo, ou peça um novo.</p>
        <Link to="/esqueci-senha">Pedir um novo link</Link>
      </div>
    )
  } else if (mutation.isSuccess) {
    content = (
      <div className="stack">
        <p className="alert success" role="status">
          Senha alterada. Por segurança, todas as sessões abertas foram encerradas: entre de novo com a senha nova.
        </p>
        <Link to="/entrar" className="button primary">
          Entrar
        </Link>
      </div>
    )
  } else {
    const expired = mutation.error && 'code' in mutation.error && mutation.error.code === 'INVALID_RESET_TOKEN'
    content = (
      <form onSubmit={submit} className="stack">
        <label>
          Nova senha
          <input
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
        {mutation.isError && <p className="alert error" role="alert">{mutation.error.message}</p>}
        {expired && <Link to="/esqueci-senha">Pedir um novo link</Link>}
        <button type="submit" className="primary" disabled={mutation.isPending}>
          {mutation.isPending ? 'Salvando…' : 'Salvar senha nova'}
        </button>
      </form>
    )
  }

  return (
    <main className="narrow">
      <BrandTitle />
      <h2>Criar uma senha nova</h2>
      {content}
    </main>
  )
}
