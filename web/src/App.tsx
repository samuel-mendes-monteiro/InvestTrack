import { useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router'
import { api, call } from './api/client'
import { useMe } from './api/queries'
import { ApiError } from './api/errors'
import { markLoggedIn, markLoggedOut, useSession } from './api/session'
import { LoginPage } from './auth/LoginPage'
import { BankIcon, ChartIcon, CoinsIcon, ListIcon, LogoMark, PlusIcon, WalletIcon } from './components/Icons'
import { LandingPage } from './landing/LandingPage'
import { OperationForm } from './operations/OperationForm'

// Each page is its own chunk, downloaded the first time it's opened: the login
// screen doesn't wait for the charting library, and a page's code only loads
// for people who visit it.
const PortfolioPage = lazy(() => import('./portfolio/PortfolioPage').then((m) => ({ default: m.PortfolioPage })))
const PerformancePage = lazy(() => import('./performance/PerformancePage').then((m) => ({ default: m.PerformancePage })))
const OperationsPage = lazy(() => import('./operations/OperationsPage').then((m) => ({ default: m.OperationsPage })))
const IncomePage = lazy(() => import('./income/IncomePage').then((m) => ({ default: m.IncomePage })))
const ProfilePage = lazy(() => import('./profile/ProfilePage').then((m) => ({ default: m.ProfilePage })))
const FixedIncomePage = lazy(() => import('./fixed-income/FixedIncomePage').then((m) => ({ default: m.FixedIncomePage })))

export default function App() {
  const { status, notice, generation } = useSession()
  if (status === 'checking') return <SessionCheck />
  // key: each login mounts a fresh shell, so nothing from the last session survives.
  if (status === 'in') return <Shell key={generation} />
  // An expired session goes straight back to the login, with the notice.
  if (notice) return <LoginPage notice={notice} />
  return <Public />
}

/** Before the login: the product page, and the login and sign-up forms. */
function Public() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/entrar" element={<LoginPage key="login" notice={null} />} />
      <Route path="/criar-conta" element={<LoginPage key="register" notice={null} initialTab="register" />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

/**
 * On startup, ask the API whether the browser's cookie is still a session.
 * The cookie is HttpOnly, so this is the only way to know.
 */
function SessionCheck() {
  const [failed, setFailed] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let current = true // ignore the answer if the component is gone (StrictMode runs effects twice)
    call(api.GET('/api/auth/me'))
      .then(() => current && markLoggedIn())
      .catch((e: unknown) => {
        if (!current) return
        if (e instanceof ApiError && e.status === 401) markLoggedOut()
        else setFailed((e as Error).message) // API down: say so instead of showing the login
      })
    return () => {
      current = false
    }
  }, [attempt])

  if (!failed) return <p className="muted center">Carregando…</p>
  return (
    <main className="narrow">
      <h1>InvestTrack</h1>
      <p className="alert error">{failed}</p>
      <button
        onClick={() => {
          setFailed(null)
          setAttempt((n) => n + 1)
        }}
      >
        Tentar de novo
      </button>
    </main>
  )
}

// Each screen has its own URL, so reload, back/forward and bookmarks work.
const PAGES = [
  { path: '/', label: 'Carteira', icon: <WalletIcon />, element: <PortfolioPage /> },
  { path: '/rentabilidade', label: 'Rentabilidade', icon: <ChartIcon />, element: <PerformancePage /> },
  { path: '/operacoes', label: 'Operações', icon: <ListIcon />, element: <OperationsPage /> },
  { path: '/proventos', label: 'Proventos', icon: <CoinsIcon />, element: <IncomePage /> },
  { path: '/renda-fixa', label: 'Renda fixa', icon: <BankIcon />, element: <FixedIncomePage /> },
]

/** Everything behind the login. */
function Shell() {
  const queryClient = useQueryClient()
  const me = useMe()
  const [leaving, setLeaving] = useState(false)
  const [creating, setCreating] = useState(false)

  // Leaving the shell (logout or expired session) empties the cache, so the
  // next person to log in on this browser never sees this one's portfolio.
  useEffect(() => () => queryClient.clear(), [queryClient])

  async function logout() {
    setLeaving(true)
    try {
      await call(api.POST('/api/auth/logout')) // revokes the session and deletes the cookie
    } catch {
      // API unreachable: the screen still goes back to the login. The cookie
      // may then outlive this tab, but the next start asks the API again.
    }
    markLoggedOut()
  }

  return (
    <>
      <header className="topbar">
        <strong className="brand">
          <LogoMark />
          InvestTrack
        </strong>
        {/* On phones this same nav becomes a tab bar fixed to the bottom of the screen. */}
        <nav className="app-nav" aria-label="Áreas">
          {PAGES.map((p) => (
            <NavLink key={p.path} to={p.path} end>
              {p.icon}
              <span>{p.label}</span>
            </NavLink>
          ))}
        </nav>
        <span className="spacer" />
        <button className="primary new-operation" onClick={() => setCreating(true)}>
          <PlusIcon />
          <span>Nova operação</span>
        </button>
        {me.data && (
          <NavLink to="/perfil" className="profile-button" title="Perfil" aria-label={`Perfil de ${me.data.email}`}>
            <span className="avatar" aria-hidden="true">
              {me.data.email[0].toUpperCase()}
            </span>
            <span className="email">{me.data.email}</span>
          </NavLink>
        )}
        <button onClick={logout} disabled={leaving} title={me.data ? `Sair de ${me.data.email}` : undefined}>
          Sair
        </button>
      </header>
      <main>
        <Suspense fallback={<p className="muted">Carregando…</p>}>
          <Routes>
            {PAGES.map((p) => (
              <Route key={p.path} path={p.path} element={p.element} />
            ))}
            <Route path="/perfil" element={<ProfilePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>
      {creating && <OperationForm onClose={() => setCreating(false)} />}
    </>
  )
}
