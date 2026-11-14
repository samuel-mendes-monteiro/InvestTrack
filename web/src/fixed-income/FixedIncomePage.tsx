import { useState } from 'react'
import { useFixedIncome } from '../api/queries'
import { Metric } from '../components/Metric'
import { brDate, brl, pct, sumDecimals, toneOf } from '../format'
import { FI_STATUS } from '../labels'
import { FixedIncomeForm } from './FixedIncomeForm'
import { InvestmentDialog } from './InvestmentDialog'
import { rateLabel } from './rate'

export function FixedIncomePage() {
  const investments = useFixedIncome()
  const [creating, setCreating] = useState(false)
  // The id, not the object: the dialog must show the refetched numbers after a change.
  const [openId, setOpenId] = useState<number | null>(null)

  if (investments.isPending) return <p className="muted">Carregando renda fixa…</p>
  if (investments.isError) return <p className="alert error">{investments.error.message}</p>

  const all = investments.data
  const active = all.filter((f) => f.status === 'ACTIVE')
  const open = all.find((f) => f.id === openId)
  // Unknown if any value is unknown: a partial sum shown as the total would be wrong.
  const total = (key: 'principal' | 'gross' | 'net') => {
    const values = active.map((f) => f[key])
    return values.every((v) => v != null) ? sumDecimals(values) : null
  }

  return (
    <>
      <div className="page-head">
        <p className="muted">CDB, LCI e LCA a % do CDI, prefixados ou IPCA+, com IOF e IR regressivo.</p>
        <button className="primary" onClick={() => setCreating(true)}>
          Nova aplicação
        </button>
      </div>

      {!all.length ? (
        <p className="muted">Nenhuma aplicação de renda fixa registrada.</p>
      ) : (
        <>
          {all.some((f) => f.as_of == null) && (
            <p className="alert warning">Aguardando o histórico do CDI. Os valores aparecem sozinhos em instantes.</p>
          )}
          {active.some((f) => f.estimated) && (
            <p className="alert warning">
              IPCA+: o IPCA do mês só sai por volta do dia 10 do mês seguinte. Até lá, o valor usa o último IPCA
              publicado e é uma estimativa.
            </p>
          )}

          <div className="metrics">
            <Metric
              label="Aplicado"
              value={brl(total('principal'))}
              help="Dinheiro aplicado que continua investido, descontados os resgates parciais."
            />
            <Metric label="Valor bruto" value={brl(total('gross'))} />
            <Metric
              label="Valor líquido"
              value={brl(total('net'))}
              help="Se resgatasse hoje: já descontados IOF e IR. LCI e LCA são isentas."
            />
          </div>

          <div className="table-wrap">
            <table className="data" aria-label="Aplicações">
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Produto</th>
                  <th>Taxa</th>
                  <th>Aplicação</th>
                  <th>Vencimento</th>
                  <th className="num">Aplicado</th>
                  <th className="num">Resgates parciais</th>
                  <th className="num">Bruto</th>
                  <th className="num">IOF + IR</th>
                  <th className="num">Líquido</th>
                  <th className="num">Rent. bruta</th>
                  <th>Situação</th>
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
                      </button>
                    </th>
                    <td>{f.product}</td>
                    <td>{rateLabel(f)}</td>
                    <td>{brDate(f.start)}</td>
                    <td>{brDate(f.maturity)}</td>
                    <td className="num">{brl(f.amount)}</td>
                    <td className="num">
                      {f.partial_redemptions.length ? brl(sumDecimals(f.partial_redemptions.map((p) => p.gross))) : ''}
                    </td>
                    <td className="num">{brl(f.gross)}</td>
                    <td className="num">{f.iof == null || f.ir == null ? '—' : brl(sumDecimals([f.iof, f.ir]))}</td>
                    <td className="num">{brl(f.net)}</td>
                    <td className={`num ${toneOf(f.gross_return) ?? ''}`}>{pct(f.gross_return)}</td>
                    <td>{FI_STATUS[f.status]}</td>
                    <td className="row-actions">
                      <button onClick={() => setOpenId(f.id)} aria-label={`Resgatar ou apagar ${f.name}`}>
                        Resgatar…
                      </button>
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
        </>
      )}

      {creating && <FixedIncomeForm onClose={() => setCreating(false)} />}
      {open && <InvestmentDialog investment={open} onClose={() => setOpenId(null)} />}
    </>
  )
}
