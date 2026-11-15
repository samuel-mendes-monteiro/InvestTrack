import { useState, type FormEvent } from 'react'
import { useDeleteBonusCost, useSetBonusCost, useStockEvents, type StockEvent } from '../api/queries'
import { Modal } from '../components/Modal'
import { brDate, decimalField, multiplierToPercent, perShare, quantity } from '../format'
import { STOCK_EVENT_TYPES } from '../labels'

const bonusLabel = (e: StockEvent) => `${e.ticker} · ${multiplierToPercent(e.multiplier)}% em ${brDate(e.record_date)}`

/** Splits, reverse splits and bonus shares B3 applied to the portfolio. */
export function StockEvents() {
  const events = useStockEvents()
  const [editing, setEditing] = useState<StockEvent | null>(null)

  if (events.isError) return <p className="alert error">{events.error.message}</p>
  if (!events.data?.length) return null // nothing to show, or still loading below the trades

  const missingCost = events.data.some((e) => e.event_type === 'BONUS' && e.unit_cost == null)

  return (
    <section className="card" aria-labelledby="stock-events-title">
      <h2 id="stock-events-title">Desdobramentos e bonificações</h2>
      <p className="muted">
        Aplicados automaticamente a partir dos eventos da B3, no fim da data com. Frações de ação são vendidas pela B3
        em leilão e não aparecem aqui.
      </p>
      {missingCost && (
        <p className="alert warning">
          Há bonificação sem custo atribuído: as ações novas entraram com custo zero, o que deixa o preço médio abaixo
          do valor para o IR. Informe o custo na linha da bonificação.
        </p>
      )}
      <div className="table-wrap">
        <table className="data" aria-label="Desdobramentos e bonificações">
          <thead>
            <tr>
              <th>Data com</th>
              <th>Evento</th>
              <th>Ticker</th>
              <th className="num">Antes</th>
              <th className="num">Depois</th>
              <th className="num">Custo atribuído</th>
              <th>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {events.data.map((e) => {
              const bonus = e.event_type === 'BONUS'
              return (
                <tr key={`${e.ticker}-${e.record_date}-${e.event_type}`}>
                  <td>{brDate(e.record_date)}</td>
                  <td>
                    {STOCK_EVENT_TYPES[e.event_type]}
                    {bonus && ` de ${multiplierToPercent(e.multiplier)}%`}
                  </td>
                  <td>{e.ticker}</td>
                  <td className="num">{quantity(e.quantity_before)}</td>
                  <td className="num">{quantity(e.quantity_after)}</td>
                  <td className={`num ${bonus && e.unit_cost == null ? 'negative' : ''}`}>
                    {!bonus ? '' : e.unit_cost == null ? 'não informado' : perShare(e.unit_cost)}
                  </td>
                  <td>
                    <div className="row-actions">
                      {bonus && (
                        <button onClick={() => setEditing(e)} aria-label={`Custo atribuído de ${bonusLabel(e)}`}>
                          {e.unit_cost == null ? 'Informar custo' : 'Alterar custo'}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {editing && <BonusCostForm key={bonusLabel(editing)} event={editing} onClose={() => setEditing(null)} />}
    </section>
  )
}

function BonusCostForm({ event, onClose }: { event: StockEvent; onClose: () => void }) {
  // Prefilled as typed in Brazil when a cost already exists.
  const [cost, setCost] = useState(event.unit_cost == null ? '' : quantity(event.unit_cost).replace(/\./g, ''))
  const [invalid, setInvalid] = useState<string | null>(null)
  const save = useSetBonusCost()
  const remove = useDeleteBonusCost()

  function submit(e: FormEvent) {
    e.preventDefault()
    let unitCost: string
    try {
      unitCost = decimalField('Custo atribuído', cost)
    } catch (err) {
      setInvalid((err as Error).message)
      return
    }
    setInvalid(null)
    save.mutate({ event, unitCost }, { onSuccess: onClose })
  }

  const failed = save.error ?? remove.error
  const error = invalid ?? failed?.message ?? null

  return (
    <Modal title={`Custo atribuído · ${bonusLabel(event)}`} onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <label>
          Custo atribuído por ação (R$)
          <input inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} placeholder="7,82" />
          <small>
            O valor está no aviso aos acionistas da empresa e no informe de rendimentos da corretora. A B3 não publica
            esse dado.
          </small>
        </label>
        {error && (
          <p className="alert error" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          {event.unit_cost != null && (
            <button
              type="button"
              className="push-left"
              disabled={remove.isPending}
              onClick={() => remove.mutate(event, { onSuccess: onClose })}
            >
              Remover custo
            </button>
          )}
          <button type="button" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" className="primary" disabled={save.isPending}>
            Salvar
          </button>
        </div>
      </form>
    </Modal>
  )
}
