import { useEffect, useId, useRef, type ReactNode } from 'react'

/** A centered dialog over the page. Esc or a click outside closes it. */
export function Modal({
  title,
  onClose,
  children,
  className,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  const titleId = useId()
  const box = useRef<HTMLDivElement>(null)
  // Parents pass a new arrow function on every render. Reading it through a ref
  // lets the effect below run once, on open: if it depended on onClose, any
  // re-render of the parent (a refetch, say) would yank focus back to the
  // first field while the user is typing in another.
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose
  })

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    box.current?.querySelector<HTMLElement>('input, select, button')?.focus()
    // Dialogs can stack (a confirm over a form). Every one listens on document,
    // so only the topmost, the last backdrop in the page, answers to Esc.
    const onKey = (e: KeyboardEvent) => {
      const backdrops = document.querySelectorAll('.backdrop')
      if (e.key === 'Escape' && backdrops[backdrops.length - 1] === box.current?.parentElement) close.current()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus() // back to the button that opened it, for keyboard users
    }
  }, [])

  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} className={className ? `modal ${className}` : 'modal'} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  )
}
