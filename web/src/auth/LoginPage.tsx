import { useMutation } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { markLoggedIn } from '../api/session'
import { LogoMark } from '../components/Icons'

type Tab = 'login' | 'register'

async function login(email: string, password: string): Promise<void> {
  await call(api.POST('/api/auth/login', { body: { email, password } })) // sets the cookie
  markLoggedIn()
}

/** Entrar / Criar conta. The app swaps to the portfolio as soon as the login succeeds. */
export function LoginPage({ notice, initialTab = 'login' }: { notice: string | null; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab)
  const id = useId()

  return (
    <main className="narrow">
      <BrandTitle />
      {notice && <p className="alert warning">{notice}</p>}
      <div role="tablist" className="tabs">
        {(['login', 'register'] as const).map((t) => (
          <button
            key={t}
            role="tab"
            id={`${id}-${t}`}
            aria-selected={tab === t}
            aria-controls={`${id}-panel`}
            onClick={() => setTab(t)}
          >
            {t === 'login' ? 'Entrar' : 'Criar conta'}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}`}>
        {/* key: switching tabs starts the other form from scratch, passwords included */}
        {tab === 'login' ? <LoginForm key="login" /> : <RegisterForm key="register" />}
      </section>
    </main>
  )
}

/** The logo, back to the product page: the top of every screen before the login. */
export function BrandTitle() {
  return (
    <h1>
      <Link to="/" className="brand-link" title="Voltar à página inicial">
        <LogoMark />
        InvestTrack
      </Link>
    </h1>
  )
}

function LoginForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const mutation = useMutation({
    mutationFn: () => login(email.trim(), password),
    onSettled: () => setPassword(''), // never keep a password around longer than needed
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  return (
    <form onSubmit={submit} className="stack">
      <label>
        E-mail
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Senha
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {mutation.isError && <p className="alert error" role="alert">{mutation.error.message}</p>}
      <button type="submit" className="primary" disabled={mutation.isPending}>
        {mutation.isPending ? 'Entrando…' : 'Entrar'}
      </button>
      <Link to="/esqueci-senha" className="center">
        Esqueci minha senha
      </Link>
    </form>
  )
}

function RegisterForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const mutation = useMutation({
    mutationFn: async () => {
      if (password !== repeat) throw new Error('As senhas não são iguais.')
      await call(api.POST('/api/auth/register', { body: { email: email.trim(), password } }))
      await login(email.trim(), password) // straight in: nobody wants to type it all again
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

  return (
    <form onSubmit={submit} className="stack">
      <label>
        E-mail
        <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        Senha
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
        Repita a senha
        <input
          type="password"
          autoComplete="new-password"
          required
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
        />
      </label>
      {mutation.isError && <p className="alert error" role="alert">{mutation.error.message}</p>}
      <button type="submit" className="primary" disabled={mutation.isPending}>
        {mutation.isPending ? 'Criando…' : 'Criar conta'}
      </button>
      <small>A primeira conta criada fica com os dados que já existiam antes do login.</small>
    </form>
  )
}
