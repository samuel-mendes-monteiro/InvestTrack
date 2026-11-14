import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router'
import { api, call } from './api/client'
import { keys } from './api/queries'
import { setToken, useSession } from './api/session'
import { LoginPage } from './auth/LoginPage'
import { IncomePage } from './income/IncomePage'
import { OperationForm } from './operations/OperationForm'
import { OperationsPage } from './operations/OperationsPage'
import { PortfolioPage } from './portfolio/PortfolioPage'

export default function App() {
  const { token, notice } = useSession()
  // key: a new token mounts a fresh shell, so nothing from the last session survives.
  return token ? <Shell key={token} /> : <LoginPage notice={notice} />
}

// Each screen has its own URL, so reload, back/forward and bookmarks work.
const PAGES = [
  { path: '/', label: 'Carteira', element: <PortfolioPage /> },
  { path: '/operacoes', label: 'Operações', element: <OperationsPage /> },
  { path: '/proventos', label: 'Proventos', element: <IncomePage /> },
]

/** Everything behind the login. */
function Shell() {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: keys.me, queryFn: () => call(api.GET('/auth/me')) })
  const [leaving, setLeaving] = useState(false)
  const [creating, setCreating] = useState(false)

  // Leaving the shell (logout or expired session) empties the cache, so the
  // next person to log in on this browser never sees this one's portfolio.
  useEffect(() => () => queryClient.clear(), [queryClient])

  async function logout() {
    setLeaving(true)
    try {
      await call(api.POST('/auth/logout')) // revokes the token on the server
    } catch {
      // logging out locally is what matters
    }
    setToken(null)
  }

  return (
    <>
      <header className="topbar">
        <strong className="brand">InvestTrack</strong>
        <nav>
          {PAGES.map((p) => (
            <NavLink key={p.path} to={p.path} end>
              {p.label}
            </NavLink>
          ))}
        </nav>
        <span className="spacer" />
        <button className="primary" onClick={() => setCreating(true)}>
          Nova operação
        </button>
        {me.data && <span className="muted email">{me.data.email}</span>}
        <button onClick={logout} disabled={leaving}>
          Sair
        </button>
      </header>
      <main>
        <Routes>
          {PAGES.map((p) => (
            <Route key={p.path} path={p.path} element={p.element} />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      {creating && <OperationForm onClose={() => setCreating(false)} />}
    </>
  )
}
