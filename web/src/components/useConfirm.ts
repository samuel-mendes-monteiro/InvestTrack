import { createContext, useContext, type ReactNode } from 'react'

export type ConfirmRequest = {
  title: string
  message: ReactNode
  confirmLabel?: string
}

export type Ask = (request: ConfirmRequest) => Promise<boolean>

export const ConfirmContext = createContext<Ask | null>(null)

/**
 * A styled stand-in for window.confirm. `const confirm = useConfirm()` then
 * `if (await confirm({...}))` reads like the browser's version, but the dialog
 * is ours: it follows the theme, names the action on its button, and does not
 * freeze the page while it is open. Needs <ConfirmProvider> above it.
 */
export function useConfirm(): Ask {
  const ask = useContext(ConfirmContext)
  if (!ask) throw new Error('useConfirm needs a <ConfirmProvider> above it')
  return ask
}
