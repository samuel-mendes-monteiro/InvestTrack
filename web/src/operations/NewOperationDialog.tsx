import { useState } from 'react'
import { Modal } from '../components/Modal'
import { FixedIncomeForm } from '../fixed-income/FixedIncomeForm'
import { OperationFields } from './OperationForm'

type Kind = 'stock' | 'fixed-income'

const KINDS: { value: Kind; label: string }[] = [
  { value: 'stock', label: 'Bolsa' }, // ações, FIIs, ETFs e BDRs
  { value: 'fixed-income', label: 'Renda fixa' },
]

/**
 * The "Nova operação" button's dialog: a trade on the exchange or a fixed
 * income investment. One frame for both, so switching doesn't close and
 * reopen the dialog (focus and scroll stay put).
 */
export function NewOperationDialog({ onClose }: { onClose: () => void }) {
  const [kind, setKind] = useState<Kind>('stock')

  return (
    <Modal title="Nova operação" onClose={onClose}>
      <div className="kind-switch" role="group" aria-label="O que registrar">
        {KINDS.map((k) => (
          <button key={k.value} type="button" aria-pressed={kind === k.value} onClick={() => setKind(k.value)}>
            {k.label}
          </button>
        ))}
      </div>
      {kind === 'stock' ? <OperationFields onClose={onClose} /> : <FixedIncomeForm onClose={onClose} />}
    </Modal>
  )
}
