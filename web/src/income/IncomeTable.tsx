import type { Income } from '../api/queries'
import { brDate, brl, perShare, quantity } from '../format'
import { INCOME_TYPES } from '../labels'

/** Income items; `onDelete` adds a button to the manual ones (B3's come from the trades). */
export function IncomeTable({
  label,
  items,
  onDelete,
  deleting,
}: {
  label: string
  items: Income[]
  onDelete?: (income: Income) => void
  deleting?: boolean
}) {
  return (
    <div className="table-wrap">
      <table className="data" aria-label={label}>
        <thead>
          <tr>
            <th>Pagamento</th>
            <th>Tipo</th>
            <th>Ticker</th>
            <th>Data com</th>
            <th className="num">Qtd</th>
            <th className="num">Valor/ação</th>
            <th className="num">Bruto</th>
            <th className="num">IR</th>
            <th className="num">Líquido</th>
            <th>Origem</th>
            {onDelete && (
              <th>
                <span className="sr-only">Ações</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {items.map((i, n) => (
            // B3 items have no id (computed, not stored), so the key needs more.
            <tr key={i.id ?? `${i.ticker}-${i.income_type}-${i.date}-${n}`}>
              <td>{brDate(i.date)}</td>
              <td>{INCOME_TYPES[i.income_type]}</td>
              <td>{i.ticker}</td>
              <td>{i.record_date ? brDate(i.record_date) : '—'}</td>
              <td className="num">{i.quantity == null ? '—' : quantity(i.quantity)}</td>
              <td className="num">{perShare(i.rate)}</td>
              <td className="num">{brl(i.amount)}</td>
              <td className="num">{brl(i.tax)}</td>
              <td className="num">{brl(i.net)}</td>
              <td>{i.source === 'B3' ? 'B3' : 'Manual'}</td>
              {onDelete && (
                <td>
                  <div className="row-actions">
                    {i.source === 'MANUAL' && i.id != null && (
                      <button onClick={() => onDelete(i)} disabled={deleting} aria-label={`Apagar provento #${i.id}`}>
                        Apagar
                      </button>
                    )}
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
