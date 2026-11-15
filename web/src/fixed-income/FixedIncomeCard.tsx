import { useState } from 'react'
import { useFixedIncome } from '../api/queries'
import { Modal } from '../components/Modal'
import { brDate, brl, pct, sumDecimals, toneOf } from '../format'
import { FI_STATUS } from '../labels'
import { FixedIncomeForm } from './FixedIncomeForm'
import { InvestmentDialog } from './InvestmentDialog'
import { rateLabel } from './rate'

/**
 * Fixed income on the Carteira: each investment with its values, and the
 * dialog to redeem or delete it. New ones come from the "Nova operação" button.
 */
export function FixedIncomeCard() {
  const investments = useFixedIncome()
  // The id, not the object: the dialog must show the refetched numbers after a change.
  const [openId, setOpenId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)

  if (investments.isPending) return null // the rest of the Carteira shows meanwhile
  if (investments.isError) return <p className="alert error">{investments.error.message}</p>

  const all = investments.data
  if (!all.length) return null // nothing to show: the card would be empty
  const active = all.filter((f) => f.status === 'ACTIVE')
  const open = all.find((f) => f.id === openId)
  const editing = all.find((f) => f.id === editingId)
  // Unknown if any value is unknown: a partial sum shown as the total would be wrong.
  const total = (key: 'principal' | 'gross' | 'net') => {
    const values = active.map((f) => f[key])
    return values.every((v) => v != null) ? sumDecimals(values) : null
  }

  return (
    <section className="card fixed-income" aria-labelledby="fixed-income-title">
      <div className="card-head">
        <h2 id="fixed-income-title">Renda fixa</h2>
        <span className="muted">{active.length === 1 ? '1 aplicação ativa' : `${active.length} aplicações ativas`}</span>
      </div>
      {all.some((f) => f.as_of == null) && (
        <p className="alert warning">Aguardando o histórico do CDI. Os valores aparecem sozinhos em instantes.</p>
      )}
      {active.some((f) => f.estimated) && (
        <p className="alert warning">
          IPCA+: o IPCA do mês só sai por volta do dia 10 do mês seguinte. Até lá, o valor usa o último IPCA
          publicado e é uma estimativa.
        </p>
      )}

      {/* The three totals of what is still invested, exact; unknown while the CDI syncs. */}
      <dl className="fi-totals">
        <div>
          <dt>Aplicado</dt>
          <dd>{brl(total('principal'))}</dd>
        </div>
        <div>
          <dt>Valor bruto</dt>
          <dd>{brl(total('gross'))}</dd>
        </div>
        <div title="Se resgatasse hoje: já descontados IOF e IR. LCI e LCA são isentas.">
          <dt>Valor líquido</dt>
          <dd>{brl(total('net'))}</dd>
        </div>
      </dl>

      <div className="table-wrap">
        <table className="data" aria-label="Aplicações">
          <thead>
            <tr>
              <th>Nome</th>
              <th>Taxa</th>
              <th>Vencimento</th>
              <th className="num">Aplicado</th>
              <th className="num">Bruto</th>
              <th className="num">Líquido</th>
              <th className="num">Rent. bruta</th>
              <th>
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {all.map((f) => (
              <tr key={f.id}>
                <th scope="row">
                  {/* Also opens the dialog: on a narrow screen the last column is scrolled away. */}
                  <button className="link" onClick={() => setOpenId(f.id)} tabIndex={-1}>
                    {f.name}
                  </button>{' '}
                  {/* Product, start, IOF and IR and partial redemptions are in the dialog. */}
                  <span className="muted small-tag">{f.product}</span>
                  {f.status !== 'ACTIVE' && <span className="chip">{FI_STATUS[f.status]}</span>}
                </th>
                <td>{rateLabel(f)}</td>
                <td>{brDate(f.maturity)}</td>
                <td className="num">{brl(f.amount)}</td>
                <td className="num">{brl(f.gross)}</td>
                <td className="num">{brl(f.net)}</td>
                <td className={`num ${toneOf(f.gross_return) ?? ''}`}>{pct(f.gross_return)}</td>
                <td>
                  <div className="row-actions">
                    <button onClick={() => setEditingId(f.id)} aria-label={`Editar ${f.name}`}>
                      Editar
                    </button>
                    <button onClick={() => setOpenId(f.id)} aria-label={`Resgatar ${f.name}`}>
                      Resgatar…
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Valores do último dia útil com CDI publicado. O IR é regressivo pelo tempo aplicado (22,5% até 180 dias, 20%
        até 360, 17,5% até 720 e 15% depois), e o IOF incide em resgates com menos de 30 dias.
      </p>

      {open && <InvestmentDialog investment={open} onClose={() => setOpenId(null)} />}
      {editing && (
        <Modal title={`Editar ${editing.name}`} onClose={() => setEditingId(null)}>
          <FixedIncomeForm key={editing.id} investment={editing} onClose={() => setEditingId(null)} />
        </Modal>
      )}
    </section>
  )
}
