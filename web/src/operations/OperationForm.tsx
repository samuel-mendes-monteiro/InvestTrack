import { useEffect, useState, type FormEvent } from 'react'
import {
  useCreateOperation,
  usePriceOn,
  useUpdateOperation,
  type Operation,
  type OperationInput,
  type Schemas,
} from '../api/queries'
import { Modal } from '../components/Modal'
import { brDate, brl, decimalField, quantity, todayIso } from '../format'
import { ASSET_TYPES, OP_TYPES } from '../labels'

type Fields = {
  op_type: Schemas['OpType']
  ticker: string
  asset_type: Schemas['AssetType']
  date: string
  quantity: string
  fees: string
}

const EMPTY: Fields = {
  op_type: 'BUY',
  ticker: '',
  asset_type: 'STOCK',
  date: todayIso(),
  quantity: '',
  fees: '',
}

// Shown as typed in Brazil ("30,5"), not as the API sends it ("30.50000000").
const asTyped = (value: string) => quantity(value).replace(/\./g, '')
// A price with its cents, as someone would type it: "38,00", "1234,56".
const priceTyped = (value: string) => brl(value).slice(3).replace(/\./g, '')

function fromOperation(o: Operation): Fields {
  return {
    op_type: o.op_type,
    ticker: o.ticker,
    asset_type: 'STOCK',
    date: o.date,
    quantity: asTyped(o.quantity),
    fees: asTyped(o.fees),
  }
}

function toInput(f: Fields, price: string): OperationInput {
  if (!f.ticker.trim()) throw new Error('Informe o ticker.')
  return {
    op_type: f.op_type,
    ticker: f.ticker.trim().toUpperCase(),
    asset_type: f.asset_type,
    date: f.date,
    // Strings, so the values reach the API as exact decimals.
    quantity: decimalField('Quantidade', f.quantity),
    price: decimalField('Preço', price),
    fees: decimalField('Taxas', f.fees, '0'),
  }
}

/** `value`, but only after it stopped changing for `ms`: no request per keystroke. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}

/** New operation, or editing `operation` when given, in its own dialog. */
export function OperationForm({ operation, onClose }: { operation?: Operation; onClose: () => void }) {
  return (
    <Modal title={operation ? `Editar operação #${operation.id}` : 'Nova operação'} onClose={onClose}>
      <OperationFields operation={operation} onClose={onClose} />
    </Modal>
  )
}

/** The form itself, for a dialog that already has its frame (see NewOperationDialog). */
export function OperationFields({ operation, onClose }: { operation?: Operation; onClose: () => void }) {
  const [fields, setFields] = useState<Fields>(operation ? fromOperation(operation) : EMPTY)
  // null while the price follows the suggestion; a string otherwise. Editing
  // starts with the price the operation was made at, but that one only holds
  // while its date and ticker do: change either, and the price follows the
  // new day's quote. A price the user typed always stays.
  const [typedPrice, setTypedPrice] = useState<string | null>(operation ? asTyped(operation.price) : null)
  const [userTyped, setUserTyped] = useState(false)
  const [invalid, setInvalid] = useState<string | null>(null)
  const create = useCreateOperation()
  const update = useUpdateOperation()
  const mutation = operation ? update : create

  // The date waits too: typed over in Chrome, it changes once per segment, and
  // the year passes through 0002, 0020 and 0202. Asking for each queued half a
  // dozen requests on the small server, and the price showed up late.
  const ticker = useDebounced(fields.ticker.trim().toUpperCase(), 400)
  const date = useDebounced(fields.date, 400)
  const suggestion = usePriceOn(typedPrice == null ? ticker : '', date)
  const suggested = suggestion.data ? priceTyped(suggestion.data.price) : ''
  const price = typedPrice ?? suggested

  const set =
    <K extends keyof Fields>(key: K) =>
    (e: { target: { value: string } }) =>
      setFields((f) => ({ ...f, [key]: e.target.value as Fields[K] }))

  /** Date and ticker decide the quote: a new one drops a price that wasn't typed by the user. */
  const setPriced =
    (key: 'date' | 'ticker') =>
    (e: { target: { value: string } }) => {
      set(key)(e)
      if (!userTyped) setTypedPrice(null)
    }

  function submit(event: FormEvent) {
    event.preventDefault()
    let body: OperationInput
    try {
      body = toInput(fields, price)
    } catch (e) {
      setInvalid((e as Error).message)
      return
    }
    setInvalid(null)
    const done = { onSuccess: onClose }
    if (operation) update.mutate({ id: operation.id, body }, done)
    else create.mutate(body, done)
  }

  const error = invalid ?? (mutation.isError ? mutation.error.message : null)

  return (
    <form onSubmit={submit} className="stack">
      <fieldset className="segmented">
        <legend>Tipo</legend>
        {(Object.keys(OP_TYPES) as Schemas['OpType'][]).map((t) => (
          <label key={t}>
            <input type="radio" name="op_type" value={t} checked={fields.op_type === t} onChange={set('op_type')} />
            {OP_TYPES[t]}
          </label>
        ))}
      </fieldset>
      <div className="grid2">
        <label>
          Ticker
          <input value={fields.ticker} onChange={setPriced('ticker')} placeholder="PETR4" autoCapitalize="characters" />
        </label>
        <label>
          Classe do ativo
          <select value={fields.asset_type} onChange={set('asset_type')}>
            {Object.entries(ASSET_TYPES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <small>Usada só na primeira vez que o ticker aparece.</small>
        </label>
        <label>
          Data
          <input type="date" required max={todayIso()} value={fields.date} onChange={setPriced('date')} />
        </label>
        <label>
          Quantidade
          <input inputMode="decimal" value={fields.quantity} onChange={set('quantity')} placeholder="100" />
        </label>
        <label>
          Preço unitário (R$)
          <input
            inputMode="decimal"
            value={price}
            onChange={(e) => {
              setTypedPrice(e.target.value)
              setUserTyped(true)
            }}
            placeholder={suggestion.isFetching ? 'Buscando…' : '30,50'}
          />
          <PriceHint
            typed={typedPrice != null}
            suggestion={suggestion}
            onUse={() => {
              setTypedPrice(null)
              setUserTyped(false)
            }}
          />
        </label>
        <label>
          Taxas (R$)
          <input inputMode="decimal" value={fields.fees} onChange={set('fees')} placeholder="0,00" />
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
          {operation ? 'Salvar alterações' : 'Registrar'}
        </button>
      </div>
    </form>
  )
}

/** Where the suggested price came from, or a way back to it after typing over it. */
function PriceHint({
  typed,
  suggestion,
  onUse,
}: {
  typed: boolean
  suggestion: ReturnType<typeof usePriceOn>
  onUse: () => void
}) {
  if (typed) {
    return (
      <small>
        <button type="button" className="link" onClick={onUse}>
          Usar a cotação da data
        </button>
      </small>
    )
  }
  if (suggestion.isError) return <small>Sem cotação para essa data: digite o preço.</small>
  if (!suggestion.data) return null
  const { source, date } = suggestion.data
  return <small>{source === 'QUOTE' ? 'Cotação atual. Confira o preço pago.' : `Fechamento de ${brDate(date)}.`}</small>
}
