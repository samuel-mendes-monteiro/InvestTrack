import { useState, type FormEvent } from 'react'
import { useCreateFixedIncome, type FixedIncomeInput, type Schemas } from '../api/queries'
import { Modal } from '../components/Modal'
import { decimalField, todayIso } from '../format'
import { FI_INDEXERS, FI_PRODUCTS } from '../labels'

const RATE_HELP: Record<Schemas['Indexer'], string> = {
  CDI: 'Percentual do CDI, por exemplo 110.',
  PRE: 'Taxa ao ano, por exemplo 12,5.',
  IPCA: 'Taxa ao ano acima da inflação, por exemplo 6,5.',
}

/** One year after `iso`, as a sensible default maturity. */
function nextYear(iso: string): string {
  return `${Number(iso.slice(0, 4)) + 1}${iso.slice(4)}`.replace('-02-29', '-02-28')
}

export function FixedIncomeForm({ onClose }: { onClose: () => void }) {
  const today = todayIso()
  const [name, setName] = useState('')
  const [product, setProduct] = useState<Schemas['Product']>('CDB')
  const [indexer, setIndexer] = useState<Schemas['Indexer']>('CDI')
  const [rate, setRate] = useState('')
  const [start, setStart] = useState(today)
  const [maturity, setMaturity] = useState(nextYear(today))
  const [amount, setAmount] = useState('')
  const [invalid, setInvalid] = useState<string | null>(null)
  const create = useCreateFixedIncome()

  function submit(event: FormEvent) {
    event.preventDefault()
    let body: FixedIncomeInput
    try {
      if (!name.trim()) throw new Error('Informe o nome.')
      body = {
        name: name.trim(),
        product,
        indexer,
        rate: decimalField('Taxa', rate),
        start,
        maturity,
        amount: decimalField('Valor aplicado', amount),
      }
    } catch (e) {
      setInvalid((e as Error).message)
      return
    }
    setInvalid(null)
    create.mutate(body, { onSuccess: onClose })
  }

  const error = invalid ?? (create.isError ? create.error.message : null)

  return (
    <Modal title="Nova aplicação" onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <div className="grid2">
          <label>
            Nome
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="CDB Banco X" />
          </label>
          <label>
            Produto
            <select value={product} onChange={(e) => setProduct(e.target.value as Schemas['Product'])}>
              {FI_PRODUCTS.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
            {product !== 'CDB' && <small>{product} é isenta de IR e IOF.</small>}
          </label>
        </div>
        <fieldset className="segmented">
          <legend>Indexador</legend>
          {(Object.keys(FI_INDEXERS) as Schemas['Indexer'][]).map((i) => (
            <label key={i}>
              <input type="radio" name="indexer" checked={indexer === i} onChange={() => setIndexer(i)} />
              {FI_INDEXERS[i]}
            </label>
          ))}
        </fieldset>
        <div className="grid2">
          <label>
            Taxa (%)
            <input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="110" />
            <small>{RATE_HELP[indexer]}</small>
          </label>
          <label>
            Valor aplicado (R$)
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5.000,00" />
          </label>
          <label>
            Data da aplicação
            <input type="date" required max={today} value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label>
            Vencimento
            <input type="date" required min={start} value={maturity} onChange={(e) => setMaturity(e.target.value)} />
          </label>
        </div>
        {error && (
          <p className="alert error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="button" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" className="primary" disabled={create.isPending}>
            Registrar
          </button>
        </div>
      </form>
    </Modal>
  )
}
