import { useState } from 'react'
import { useDeleteOperation, useOperations, type Operation } from '../api/queries'
import { brDate, brl, quantity } from '../format'
import { OP_TYPES } from '../labels'
import { OperationForm } from './OperationForm'

export function OperationsPage() {
  const operations = useOperations()
  const remove = useDeleteOperation()
  const [ticker, setTicker] = useState('')
  const [editing, setEditing] = useState<Operation | null>(null)

  if (operations.isPending) return <p className="muted">Carregando operações…</p>
  if (operations.isError) return <p className="alert error">{operations.error.message}</p>
  if (!operations.data.length) return <p className="muted">Nenhuma operação registrada.</p>

  const tickers = [...new Set(operations.data.map((o) => o.ticker))].sort()
  const shown = operations.data.filter((o) => !ticker || o.ticker === ticker)

  function confirmDelete(o: Operation) {
    const what = `${OP_TYPES[o.op_type]} de ${quantity(o.quantity)} ${o.ticker} em ${brDate(o.date)}`
    if (window.confirm(`Apagar a operação #${o.id} (${what})?`)) remove.mutate(o.id)
  }

  return (
    <>
      <div className="toolbar">
        <label className="inline">
          Ticker
          <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
            <option value="">Todos</option>
            {tickers.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </div>
      {remove.isError && (
        <p className="alert error" role="alert">
          Não foi possível apagar: {remove.error.message}
        </p>
      )}
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Data</th>
              <th>Tipo</th>
              <th>Ticker</th>
              <th className="num">Qtd</th>
              <th className="num">Preço</th>
              <th className="num">Taxas</th>
              <th>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((o) => (
              <tr key={o.id}>
                <td className="num muted">{o.id}</td>
                <td>{brDate(o.date)}</td>
                <td>{OP_TYPES[o.op_type]}</td>
                <td>{o.ticker}</td>
                <td className="num">{quantity(o.quantity)}</td>
                <td className="num">{brl(o.price)}</td>
                <td className="num">{brl(o.fees)}</td>
                <td className="row-actions">
                  <button onClick={() => setEditing(o)} aria-label={`Editar operação #${o.id}`}>
                    Editar
                  </button>
                  <button
                    onClick={() => confirmDelete(o)}
                    disabled={remove.isPending}
                    aria-label={`Apagar operação #${o.id}`}
                  >
                    Apagar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <OperationForm key={editing.id} operation={editing} onClose={() => setEditing(null)} />}
    </>
  )
}
