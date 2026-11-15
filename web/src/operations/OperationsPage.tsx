import { useState } from 'react'
import { Link } from 'react-router'
import { useDeleteOperation, useOperations, type Operation } from '../api/queries'
import { ListIcon } from '../components/Icons'
import { Metric } from '../components/Metric'
import { brDate, brl, multiplyDecimals, quantity, sumDecimals } from '../format'
import { OP_TYPES } from '../labels'
import { ImportDialog } from './ImportDialog'
import { OperationForm } from './OperationForm'
import { StockEvents } from './StockEvents'

/** Money that went in (a buy, with fees) or came out (a sale, net of fees). */
function total(o: Operation): string {
  const gross = multiplyDecimals(o.quantity, o.price)
  return o.op_type === 'BUY' ? sumDecimals([gross, o.fees]) : sumDecimals([gross, `-${o.fees}`])
}

export function OperationsPage() {
  const operations = useOperations()
  const remove = useDeleteOperation()
  const [ticker, setTicker] = useState('')
  const [editing, setEditing] = useState<Operation | null>(null)
  const [importing, setImporting] = useState(false)

  if (operations.isPending) return <p className="muted">Carregando operações…</p>
  if (operations.isError) return <p className="alert error">{operations.error.message}</p>

  const importButton = (
    <button className={operations.data.length ? '' : 'primary'} onClick={() => setImporting(true)}>
      Importar extrato da B3
    </button>
  )
  const importDialog = importing && <ImportDialog onClose={() => setImporting(false)} />

  if (!operations.data.length) {
    return (
      <div className="page">
        <section className="card empty-card">
          <span className="feature-icon">
            <ListIcon />
          </span>
          <h2>Nenhuma operação registrada</h2>
          <p className="muted">
            Importe o extrato de negociação da B3 para trazer todo o histórico de uma vez, ou registre uma compra em
            “Nova operação”.
          </p>
          {importButton}
          <Link className="card-link" to="/ajuda/importar-b3">
            Como importar o histórico da B3 →
          </Link>
        </section>
        {importDialog}
      </div>
    )
  }

  const all = operations.data
  const tickers = [...new Set(all.map((o) => o.ticker))].sort()
  // Newest first: the last trades are the ones being checked or fixed.
  const shown = all
    .filter((o) => !ticker || o.ticker === ticker)
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id)
  const bought = sumDecimals(shown.filter((o) => o.op_type === 'BUY').map(total))
  const sold = sumDecimals(shown.filter((o) => o.op_type === 'SELL').map(total))
  const fees = sumDecimals(shown.map((o) => o.fees))

  function confirmDelete(o: Operation) {
    const what = `${OP_TYPES[o.op_type]} de ${quantity(o.quantity)} ${o.ticker} em ${brDate(o.date)}`
    if (window.confirm(`Apagar a operação #${o.id} (${what})?`)) remove.mutate(o.id)
  }

  return (
    <div className="page">
      {remove.isError && (
        <p className="alert error" role="alert">
          Não foi possível apagar: {remove.error.message}
        </p>
      )}

      {/* Totals of what the table shows: with a ticker chosen, that ticker's. */}
      <div className="metrics">
        <Metric label="Operações" value={String(shown.length)} detail={ticker || `${tickers.length} ativos`} />
        <Metric label="Total comprado" value={brl(bought)} help="Quantidade × preço, mais as taxas." />
        <Metric label="Total vendido" value={brl(sold)} help="Quantidade × preço, menos as taxas." />
        <Metric
          label="Taxas pagas"
          value={brl(fees)}
          help="Corretagem e emolumentos registrados. O extrato da B3 não traz taxas: as operações importadas entram com zero."
        />
      </div>

      <section className="card" aria-labelledby="ops-title">
        <div className="card-head ops-head">
          <h2 id="ops-title">Histórico</h2>
          <div className="ops-tools">
            <label className="inline year-select">
              Ticker
              <select value={ticker} onChange={(e) => setTicker(e.target.value)}>
                <option value="">Todos</option>
                {tickers.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            {importButton}
          </div>
        </div>
        {/* data-label names each value when a row turns into a card on phones. */}
        <div className="table-wrap">
          <table className="data ops" aria-label="Operações">
            <thead>
              <tr>
                <th>Data</th>
                <th>Tipo</th>
                <th>Ticker</th>
                <th className="num">Qtd</th>
                <th className="num">Preço</th>
                <th className="num">Taxas</th>
                <th className="num">Total</th>
                <th>
                  <span className="sr-only">Ações</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((o) => (
                <tr key={o.id}>
                  <td className="op-date">{brDate(o.date)}</td>
                  <td className="op-type">
                    <span className={`chip ${o.op_type === 'BUY' ? 'buy' : 'sell'}`}>{OP_TYPES[o.op_type]}</span>
                  </td>
                  <th scope="row" className="op-ticker">
                    {o.ticker}
                  </th>
                  <td className="num op-qty" data-label="Qtd">
                    {quantity(o.quantity)}
                  </td>
                  <td className="num op-price" data-label="Preço">
                    {brl(o.price)}
                  </td>
                  <td className="num op-fees" data-label="Taxas">
                    {brl(o.fees)}
                  </td>
                  <td className="num op-total">{brl(total(o))}</td>
                  <td className="op-actions">
                    <div className="row-actions">
                      <button onClick={() => setEditing(o)} aria-label={`Editar operação #${o.id}`}>
                        Editar
                      </button>
                      <button
                        className="danger"
                        onClick={() => confirmDelete(o)}
                        disabled={remove.isPending}
                        aria-label={`Apagar operação #${o.id}`}
                      >
                        Apagar
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <StockEvents />
      {importDialog}
      {editing && <OperationForm key={editing.id} operation={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
