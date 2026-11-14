import { useState, type FormEvent } from 'react'
import {
  useCreateOperation,
  useUpdateOperation,
  type Operation,
  type OperationInput,
  type Schemas,
} from '../api/queries'
import { Modal } from '../components/Modal'
import { decimalField, quantity, todayIso } from '../format'
import { ASSET_TYPES, OP_TYPES } from '../labels'

type Fields = {
  op_type: Schemas['OpType']
  ticker: string
  asset_type: Schemas['AssetType']
  date: string
  quantity: string
  price: string
  fees: string
}

const EMPTY: Fields = {
  op_type: 'BUY',
  ticker: '',
  asset_type: 'STOCK',
  date: todayIso(),
  quantity: '',
  price: '',
  fees: '',
}

// Shown as typed in Brazil ("30,5"), not as the API sends it ("30.50000000").
const asTyped = (value: string) => quantity(value).replace(/\./g, '')

function fromOperation(o: Operation): Fields {
  return {
    op_type: o.op_type,
    ticker: o.ticker,
    asset_type: 'STOCK',
    date: o.date,
    quantity: asTyped(o.quantity),
    price: asTyped(o.price),
    fees: asTyped(o.fees),
  }
}

function toInput(f: Fields): OperationInput {
  if (!f.ticker.trim()) throw new Error('Informe o ticker.')
  return {
    op_type: f.op_type,
    ticker: f.ticker.trim().toUpperCase(),
    asset_type: f.asset_type,
    date: f.date,
    // Strings, so the values reach the API as exact decimals.
    quantity: decimalField('Quantidade', f.quantity),
    price: decimalField('Preço', f.price),
    fees: decimalField('Taxas', f.fees, '0'),
  }
}

/** New operation, or editing `operation` when given. */
export function OperationForm({ operation, onClose }: { operation?: Operation; onClose: () => void }) {
  const [fields, setFields] = useState<Fields>(operation ? fromOperation(operation) : EMPTY)
  const [invalid, setInvalid] = useState<string | null>(null)
  const create = useCreateOperation()
  const update = useUpdateOperation()
  const mutation = operation ? update : create

  const set =
    <K extends keyof Fields>(key: K) =>
    (e: { target: { value: string } }) =>
      setFields((f) => ({ ...f, [key]: e.target.value as Fields[K] }))

  function submit(event: FormEvent) {
    event.preventDefault()
    let body: OperationInput
    try {
      body = toInput(fields)
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
    <Modal title={operation ? `Editar operação #${operation.id}` : 'Nova operação'} onClose={onClose}>
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
            <input value={fields.ticker} onChange={set('ticker')} placeholder="PETR4" autoCapitalize="characters" />
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
            <input type="date" required max={todayIso()} value={fields.date} onChange={set('date')} />
          </label>
          <label>
            Quantidade
            <input inputMode="decimal" value={fields.quantity} onChange={set('quantity')} placeholder="100" />
          </label>
          <label>
            Preço unitário (R$)
            <input inputMode="decimal" value={fields.price} onChange={set('price')} placeholder="30,50" />
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
    </Modal>
  )
}
