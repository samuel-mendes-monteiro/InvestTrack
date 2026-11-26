import { useCallback, useRef, useState, type ReactNode } from 'react'
import { Modal } from './Modal'
import { ConfirmContext, type Ask, type ConfirmRequest } from './useConfirm'

/** Holds the one open question, if any. Mount it once, near the root. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<ConfirmRequest | null>(null)
  // The promise's resolve lives in a ref: it is plumbing, not something to render.
  const resolve = useRef<(answer: boolean) => void>(null)

  const ask = useCallback<Ask>((next) => {
    resolve.current?.(false) // a second question cancels the first
    setRequest(next)
    return new Promise((r) => {
      resolve.current = r
    })
  }, [])

  function answer(yes: boolean) {
    resolve.current?.(yes)
    resolve.current = null
    setRequest(null)
  }

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {/* After the children, so it stacks over a form dialog that asked it. */}
      {request && (
        <Modal title={request.title} onClose={() => answer(false)} className="confirm">
          <p>{request.message}</p>
          <div className="actions">
            {/* Cancelar comes first, so it takes the focus: Enter on reflex does not delete. */}
            <button type="button" onClick={() => answer(false)}>
              Cancelar
            </button>
            <button type="button" className="danger-solid" onClick={() => answer(true)}>
              {request.confirmLabel ?? 'Apagar'}
            </button>
          </div>
        </Modal>
      )}
    </ConfirmContext.Provider>
  )
}
