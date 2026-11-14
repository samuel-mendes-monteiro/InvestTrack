import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, call } from './api/client'
import { setToken, useSession } from './api/session'
import { LoginPage } from './auth/LoginPage'

export default function App() {
  const { token, notice } = useSession()
  // key: a new token mounts a fresh shell, so nothing from the last session survives.
  return token ? <Shell key={token} /> : <LoginPage notice={notice} />
}

/** Everything behind the login. */
function Shell() {
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: () => call(api.GET('/auth/me')) })
  const [leaving, setLeaving] = useState(false)

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
        <strong>InvestTrack</strong>
        <span className="spacer" />
        {me.data && <span className="muted">{me.data.email}</span>}
        <button onClick={logout} disabled={leaving}>
          Sair
        </button>
      </header>
      <main>
        <p className="muted">A carteira chega no próximo passo.</p>
      </main>
    </>
  )
}
