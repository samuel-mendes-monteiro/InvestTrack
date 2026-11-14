import { useSyncExternalStore } from 'react'

// Whether the user is logged in, kept outside React so the HTTP client (not a
// component) can end the session on a 401, while components re-render.
//
// The session itself is an HttpOnly cookie: the browser sends it, and no
// JavaScript here can read it, so a script injected into the page (XSS)
// can't steal it either. The price is that the app can't look at a token to
// know if it's logged in; it asks the API (/api/auth/me) when it starts.

export type Session = {
  status: 'checking' | 'in' | 'out'
  /** Why the user is at the login screen, e.g. their session expired. */
  notice: string | null
  /** Counts logins, so each one mounts a fresh app with nothing from the last. */
  generation: number
}

const listeners = new Set<() => void>()
// Replaced (never mutated) so useSyncExternalStore sees each change.
let current: Session = { status: 'checking', notice: null, generation: 0 }

function update(next: Partial<Session>): void {
  current = { ...current, ...next }
  listeners.forEach((notify) => notify())
}

export function getSession(): Session {
  return current
}

/** The API accepted a login, or confirmed the cookie at startup. */
export function markLoggedIn(): void {
  update({ status: 'in', notice: null, generation: current.generation + 1 })
}

/** Logged out on purpose, or no session at startup. */
export function markLoggedOut(): void {
  update({ status: 'out', notice: null })
}

/** The API rejected the session while the app was in use: say why. */
export function expireSession(): void {
  if (current.status === 'in') update({ status: 'out', notice: 'Sua sessão expirou. Entre de novo.' })
}

/** Back to the start (tests). */
export function resetSession(): void {
  update({ status: 'checking', notice: null, generation: 0 })
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Re-renders the component when the user logs in or the session ends. */
export function useSession(): Session {
  return useSyncExternalStore(subscribe, () => current)
}
