import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/errors'
import {
  useCreateFixedIncome,
  useUpdateFixedIncome,
  type FixedIncome,
  type FixedIncomeInput,
  type Schemas,
} from '../api/queries'
import { decimalField, quantity, todayIso } from '../format'
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

// Shown as typed in Brazil ("110", "5000,5"), not as the API sends it ("5000.50").
const asTyped = (value: string) => quantity(value).replace(/\./g, '')

/**
 * A fixed income investment: a new one (inside NewOperationDialog), or
 * `investment` edited. Editing keeps its redemption and withdrawals; the API
 * refuses a change they would no longer fit.
 */
export function FixedIncomeForm({ investment, onClose }: { investment?: FixedIncome; onClose: () => void }) {
  const today = todayIso()
  const [name, setName] = useState(investment?.name ?? '')
  const [product, setProduct] = useState<Schemas['Product']>(investment?.product ?? 'CDB')
  const [indexer, setIndexer] = useState<Schemas['Indexer']>(investment?.indexer ?? 'CDI')
  const [rate, setRate] = useState(investment ? asTyped(investment.rate) : '')
  const [start, setStart] = useState(investment?.start ?? today)
  const [maturity, setMaturity] = useState(investment?.maturity ?? nextYear(today))
  const [amount, setAmount] = useState(investment ? asTyped(investment.amount) : '')
  const [invalid, setInvalid] = useState<string | null>(null)
  const create = useCreateFixedIncome()
  const update = useUpdateFixedIncome()
  const mutation = investment ? update : create

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
    if (investment) update.mutate({ id: investment.id, body }, { onSuccess: onClose })
    else create.mutate(body, { onSuccess: onClose })
  }

  const failed = mutation.error
  // When editing, "too large" means a withdrawal already made no longer fits the new numbers.
  const error =
    invalid ??
    (failed instanceof ApiError && failed.code === 'REDEMPTION_TOO_LARGE' && investment
      ? 'Com esses dados, a aplicação valeria menos do que um resgate parcial já feito. Confira o valor e as datas.'
      : (failed?.message ?? null))

  return (
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
        <button type="submit" className="primary" disabled={mutation.isPending}>
          {investment ? 'Salvar alterações' : 'Registrar'}
        </button>
      </div>
    </form>
  )
}
