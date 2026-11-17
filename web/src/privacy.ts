import { useSyncExternalStore } from 'react'
import { brl as exactBrl, quantity as exactQuantity } from './format'

// "Hide values": the eye in the top bar swaps every amount in reais (and every
// share count, since quantity times the public price gives the amount back)
// for dots, while percentages stay. You can open the app on a bus or show a
// friend how it went without showing how much you have.
//
// It's a preference of this browser, not of the account, so it lives in
// localStorage and not in the API: hiding on the phone shouldn't hide on the
// laptop at home. Kept outside React, like session.ts, so every component
// that reads it re-renders the moment it flips.

const KEY = 'investtrack.hideValues'
const listeners = new Set<() => void>()

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false // storage blocked (private mode, some embeds): just start visible
  }
}

let hidden = read()

export function toggleHideValues(): void {
  hidden = !hidden
  try {
    localStorage.setItem(KEY, hidden ? '1' : '0')
  } catch {
    // Not saved: it still works until the page reloads.
  }
  listeners.forEach((notify) => notify())
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useHideValues(): boolean {
  return useSyncExternalStore(subscribe, () => hidden)
}

const DOTS = '•••••'

/**
 * The formatters for showing the user's own numbers. Same names and
 * signatures as format.ts, so a component swaps its import for
 * `const { brl, quantity } = usePrivateFormat()` and nothing else changes.
 *
 * format.ts stays pure on purpose: forms, dialogs and error messages keep the
 * real values (you opened them to type or check a number), and the tests of
 * the rounding rules don't depend on a toggle.
 */
export function usePrivateFormat() {
  const hide = useHideValues()
  return {
    hidden: hide,
    // null stays "—": hiding a value shouldn't pretend there is one.
    brl: (value: string | null | undefined) => (hide && value != null ? `R$ ${DOTS}` : exactBrl(value)),
    quantity: (value: string) => (hide ? DOTS : exactQuantity(value)),
  }
}
