import { useState, type FormEvent } from 'react'
import { useCreateIncome, type IncomeInput, type Schemas } from '../api/queries'
import { Modal } from '../components/Modal'
import { decimalField, todayIso } from '../format'
import { INCOME_TYPES } from '../labels'

/** Manual income: only for what B3 doesn't publish (BDRs, older than a year). */
export function IncomeForm({ tickers, onClose }: { tickers: string[]; onClose: () => void }) {
  const [type, setType] = useState<Schemas['IncomeType']>('DIVIDEND')
  const [ticker, setTicker] = useState(tickers[0] ?? '')
  const [date, setDate] = useState(todayIso())
  const [amount, setAmount] = useState('')
  const [tax, setTax] = useState('')
  const [invalid, setInvalid] = useState<string | null>(null)
  const create = useCreateIncome()

  function submit(event: FormEvent) {
    event.preventDefault()
    let body: IncomeInput
    try {
      body = {
        ticker,
        income_type: type,
        date,
        amount: decimalField('Valor bruto', amount),
        tax: decimalField('IR retido', tax, '0'),
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
    <Modal title="Registrar provento" onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <p className="muted">
          Só para o que a B3 não publica, como BDRs ou proventos com mais de um ano. Um provento que já aparece na
          lista seria contado duas vezes.
        </p>
        <fieldset className="segmented">
          <legend>Tipo</legend>
          {(Object.keys(INCOME_TYPES) as Schemas['IncomeType'][]).map((t) => (
            <label key={t}>
              <input type="radio" name="income_type" checked={type === t} onChange={() => setType(t)} />
              {INCOME_TYPES[t]}
            </label>
          ))}
        </fieldset>
        <div className="grid2">
          <label>
            Ticker
            {/* A list, not free text: a typo in the ticker is the most likely mistake. */}
            <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
              {tickers.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <label>
            Data de pagamento
            <input type="date" required max={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label>
            Valor bruto (R$)
            <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="120,50" />
          </label>
          <label>
            IR retido (R$)
            <input inputMode="decimal" value={tax} onChange={(e) => setTax(e.target.value)} placeholder="0,00" />
            <small>Use o valor do extrato da corretora.</small>
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
            Registrar provento
          </button>
        </div>
      </form>
    </Modal>
  )
}
