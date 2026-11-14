import { useSyncExternalStore } from 'react'

// The session token, kept outside React so the HTTP client (not a component)
// can end the session on a 401, while components re-render when it changes.
//
// localStorage survives reloads, which is what a "stay logged in" token needs,
// but any script running on the page can read it (XSS). That is acceptable
// while the app only runs locally; with the same-origin deploy (v1.0b) it moves
// to an HttpOnly cookie, which scripts can't read at all.

export type Session = {
  token: string | null
  /** Why the user is at the login screen, e.g. their session expired. */
  notice: string | null
}

const KEY = 'investtrack.token'
const listeners = new Set<() => void>()

function read(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null // storage blocked (private mode): the session lasts until reload
  }
}

// Replaced (never mutated) so useSyncExternalStore sees each change.
let current: Session = { token: read(), notice: null }

function update(next: Session): void {
  current = next
  try {
    if (next.token) localStorage.setItem(KEY, next.token)
    else localStorage.removeItem(KEY)
  } catch {
    // keep it in memory only
  }
  listeners.forEach((notify) => notify())
}

export function getToken(): string | null {
  return current.token
}

/** Logged in (a token) or logged out on purpose (null). */
export function setToken(token: string | null): void {
  update({ token, notice: null })
}

/** The API rejected the token: back to the login screen, saying why. */
export function expireSession(): void {
  if (current.token) update({ token: null, notice: 'Sua sessão expirou. Entre de novo.' })
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Re-renders the component when the user logs in or the session ends. */
export function useSession(): Session {
  return useSyncExternalStore(subscribe, () => current)
}
