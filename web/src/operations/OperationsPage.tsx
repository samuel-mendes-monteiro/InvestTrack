import { useState } from 'react'
import { Link } from 'react-router'
import { useDeleteOperation, useFixedIncome, useOperations, type FixedIncome, type Operation } from '../api/queries'
import { ListIcon } from '../components/Icons'
import { Metric } from '../components/Metric'
import { Modal } from '../components/Modal'
import { FixedIncomeForm } from '../fixed-income/FixedIncomeForm'
import { InvestmentDialog } from '../fixed-income/InvestmentDialog'
import { brDate, multiplyDecimals, sumDecimals } from '../format'
import { usePrivateFormat } from '../privacy'
import { OP_TYPES } from '../labels'
import { ImportDialog } from './ImportDialog'
import { OperationForm } from './OperationForm'
import { StockEvents } from './StockEvents'

/** Money that went in (a buy, with fees) or came out (a sale, net of fees). */
function total(o: Operation): string {
  const gross = multiplyDecimals(o.quantity, o.price)
  return o.op_type === 'BUY' ? sumDecimals([gross, o.fees]) : sumDecimals([gross, `-${o.fees}`])
}

/**
 * One line of the history: a trade, or money into or out of fixed income.
 * Fixed income has no quantity, price or fees: only the amount that moved.
 */
type Row = {
  key: string
  date: string
  type: string
  moneyIn: boolean
  asset: string
  tag?: string
  total: string | null
  op?: Operation
  fi?: { investment: FixedIncome; redemption: boolean }
}

function operationRow(o: Operation): Row {
  return {
    key: `op-${o.id}`,
    date: o.date,
    type: OP_TYPES[o.op_type],
    moneyIn: o.op_type === 'BUY',
    asset: o.ticker,
    total: total(o),
    op: o,
  }
}

/**
 * The application, each partial redemption, and the end: redeemed, or
 * matured. The end is out at its gross value, as the TWR counts it; null
 * while the CDI is still being downloaded.
 */
function fixedIncomeRows(f: FixedIncome): Row[] {
  const base = { asset: f.name, tag: f.product }
  const out = (key: string, date: string, type: string, value: string | null): Row => ({
    ...base,
    key: `fi-${f.id}-${key}`,
    date,
    type,
    moneyIn: false,
    total: value,
    fi: { investment: f, redemption: true },
  })
  const rows: Row[] = [
    {
      ...base,
      key: `fi-${f.id}-start`,
      date: f.start,
      type: 'Aplicação',
      moneyIn: true,
      total: f.amount,
      fi: { investment: f, redemption: false },
    },
    ...f.partial_redemptions.map((p) => out(`partial-${p.id}`, p.date, 'Resgate', p.gross)),
  ]
  if (f.redeemed_on) rows.push(out('end', f.redeemed_on, 'Resgate total', f.gross))
  else if (f.status === 'MATURED') rows.push(out('end', f.maturity, 'Vencimento', f.gross))
  return rows
}

export function OperationsPage() {
  const { brl, quantity } = usePrivateFormat()
  const operations = useOperations()
  // Not waited for: the trades show at once, and fixed income joins them when it arrives.
  const fixedIncome = useFixedIncome()
  const remove = useDeleteOperation()
  const [asset, setAsset] = useState('')
  const [editing, setEditing] = useState<Operation | null>(null)
  // By id: the dialogs read the refetched investment after each change.
  const [editingFi, setEditingFi] = useState<number | null>(null)
  const [redeemingFi, setRedeemingFi] = useState<number | null>(null)
  const [importing, setImporting] = useState(false)

  if (operations.isPending) return <p className="muted">Carregando operações…</p>
  if (operations.isError) return <p className="alert error">{operations.error.message}</p>

  const investments = fixedIncome.data ?? []
  const all = [...operations.data.map(operationRow), ...investments.flatMap(fixedIncomeRows)]

  const importButton = (
    <button className={all.length ? '' : 'primary'} onClick={() => setImporting(true)}>
      Importar extrato da B3
    </button>
  )
  const importDialog = importing && <ImportDialog onClose={() => setImporting(false)} />

  if (!all.length) {
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

  const assets = [...new Set(all.map((r) => r.asset))].sort()
  // Newest first: the last trades are the ones being checked or fixed.
  // Same day: the later id (trades) or key (an investment's own steps) first.
  const shown = all
    .filter((r) => !asset || r.asset === asset)
    .sort((a, b) => b.date.localeCompare(a.date) || (b.op?.id ?? 0) - (a.op?.id ?? 0) || b.key.localeCompare(a.key))
  const amounts = (moneyIn: boolean) =>
    sumDecimals(shown.filter((r) => r.moneyIn === moneyIn && r.total != null).map((r) => r.total!))
  const fees = sumDecimals(shown.flatMap((r) => (r.op ? [r.op.fees] : [])))
  const fiEditing = investments.find((f) => f.id === editingFi)
  const fiRedeeming = investments.find((f) => f.id === redeemingFi)

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
        <Metric label="Operações" value={String(shown.length)} detail={asset || `${assets.length} ativos`} />
        <Metric
          label="Total comprado"
          value={brl(amounts(true))}
          help="Quantidade × preço, mais as taxas. Inclui o que foi aplicado em renda fixa."
        />
        <Metric
          label="Total vendido"
          value={brl(amounts(false))}
          help="Quantidade × preço, menos as taxas. Inclui os resgates e vencimentos da renda fixa, pelo valor bruto."
        />
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
              Ativo
              <select value={asset} onChange={(e) => setAsset(e.target.value)}>
                <option value="">Todos</option>
                {assets.map((t) => (
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
                <th>Ativo</th>
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
              {shown.map((r) => (
                <tr key={r.key}>
                  <td className="op-date">{brDate(r.date)}</td>
                  <td className="op-type">
                    <span className={`chip ${r.moneyIn ? 'buy' : 'sell'}`}>{r.type}</span>
                  </td>
                  <th scope="row" className="op-ticker">
                    {r.asset}
                    {r.tag && <span className="muted small-tag"> {r.tag}</span>}
                  </th>
                  <td className="num op-qty" data-label="Qtd">
                    {r.op ? quantity(r.op.quantity) : '—'}
                  </td>
                  <td className="num op-price" data-label="Preço">
                    {r.op ? brl(r.op.price) : '—'}
                  </td>
                  <td className="num op-fees" data-label="Taxas">
                    {r.op ? brl(r.op.fees) : '—'}
                  </td>
                  <td className="num op-total">{brl(r.total)}</td>
                  <td className="op-actions">
                    <div className="row-actions">
                      {r.op && (
                        <>
                          <button onClick={() => setEditing(r.op!)} aria-label={`Editar operação #${r.op.id}`}>
                            Editar
                          </button>
                          <button
                            className="danger"
                            onClick={() => confirmDelete(r.op!)}
                            disabled={remove.isPending}
                            aria-label={`Apagar operação #${r.op.id}`}
                          >
                            Apagar
                          </button>
                        </>
                      )}
                      {r.fi &&
                        (r.fi.redemption ? (
                          <button
                            onClick={() => setRedeemingFi(r.fi!.investment.id)}
                            aria-label={`Resgates de ${r.asset}`}
                          >
                            Resgates…
                          </button>
                        ) : (
                          <button onClick={() => setEditingFi(r.fi!.investment.id)} aria-label={`Editar ${r.asset}`}>
                            Editar
                          </button>
                        ))}
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
      {fiEditing && (
        <Modal title={`Editar ${fiEditing.name}`} onClose={() => setEditingFi(null)}>
          <FixedIncomeForm key={fiEditing.id} investment={fiEditing} onClose={() => setEditingFi(null)} />
        </Modal>
      )}
      {fiRedeeming && <InvestmentDialog investment={fiRedeeming} onClose={() => setRedeemingFi(null)} />}
    </div>
  )
}
