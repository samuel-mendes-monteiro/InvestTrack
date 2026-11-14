import { useSyncExternalStore } from 'react'

// The session token, kept where the whole app can see it change.
//
// localStorage survives reloads, which is what a "stay logged in" token needs,
// but any script running on the page can read it (XSS). That is acceptable
// while the app only runs locally; with the same-origin deploy (v1.0b) it moves
// to an HttpOnly cookie, which scripts can't read at all.

const KEY = 'investtrack.token'
const listeners = new Set<() => void>()

function read(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null // storage blocked (private mode): the session lasts until reload
  }
}

let current = read()

export function getToken(): string | null {
  return current
}

export function setToken(token: string | null): void {
  current = token
  try {
    if (token) localStorage.setItem(KEY, token)
    else localStorage.removeItem(KEY)
  } catch {
    // keep it in memory only
  }
  listeners.forEach((notify) => notify())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Re-renders the component when the user logs in or the session ends. */
export function useToken(): string | null {
  return useSyncExternalStore(subscribe, getToken)
}
