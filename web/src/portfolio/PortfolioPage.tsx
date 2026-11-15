import { usePortfolio } from '../api/queries'
import { Metric } from '../components/Metric'
import { FixedIncomeCard } from '../fixed-income/FixedIncomeCard'
import { brl, isZero, localTime, pct, quantity, toneOf } from '../format'
import { Distribution, type Slice } from './Distribution'
import { netWorth } from './netWorth'
import { ReturnChart } from './ReturnChart'
import { Welcome } from './Welcome'

export function PortfolioPage() {
  const portfolio = usePortfolio()

  if (portfolio.isPending) return <p className="muted">Carregando a carteira…</p>
  if (portfolio.isError) return <p className="alert error">{portfolio.error.message}</p>

  const { positions, totals } = portfolio.data
  const open = positions.filter((p) => !isZero(p.quantity))
  // Unknown (null) while the CDI history downloads: there is fixed income, just no value yet.
  const hasFixedIncome = totals.fixed_income == null || !isZero(totals.fixed_income)

  if (!positions.length && !hasFixedIncome) {
    return <Welcome />
  }

  const total = netWorth(totals)
  const missing = open.filter((p) => p.current_price == null).map((p) => p.ticker)
  const stale = open.filter((p) => p.price_stale)
  const slices: Slice[] = open.flatMap((p) => (p.current_value == null ? [] : [{ name: p.ticker, value: p.current_value }]))
  if (totals.fixed_income != null && !isZero(totals.fixed_income)) {
    slices.push({ name: 'Renda fixa', value: totals.fixed_income })
  }

  return (
    <div className="portfolio">
      {totals.fixed_income == null && (
        <p className="alert warning" role="status">
          Atualizando a renda fixa com o CDI mais recente. O patrimônio aparece sozinho em instantes.
        </p>
      )}
      <div className="portfolio-top">
        <div className="portfolio-summary">
          <Metric
            hero
            label="Patrimônio"
            value={brl(total)}
            detail={`${brl(totals.current_value)} em ações, FIIs e ETFs · ${brl(totals.fixed_income)} em renda fixa`}
            help="Renda fixa pelo valor líquido."
          />
          <div className="metrics">
            <Metric
              label="Investido em ações"
              value={brl(totals.invested)}
              help="Custo das posições abertas de ações, FIIs e ETFs, sem a renda fixa."
            />
            <Metric
              label="Resultado em ações"
              value={brl(totals.result)}
              detail={totals.result_pct != null && pct(totals.result_pct)}
              tone={toneOf(totals.result)}
              help="Valor atual menos o custo das posições abertas, sem a renda fixa."
            />
            <Metric
              label="Lucro realizado"
              value={brl(totals.realized_profit)}
              help="Lucro ou prejuízo de vendas já feitas, inclusive de posições encerradas."
            />
            <Metric
              label="Proventos"
              value={brl(totals.income)}
              detail={!isZero(totals.income_pending) && `${brl(totals.income_pending)} a receber`}
              help="Dividendos, JCP e rendimentos já recebidos, descontado o IR retido."
            />
          </div>
          <ReturnChart />
        </div>

        <section className="card" aria-labelledby="distribution-title">
          <h2 id="distribution-title">Distribuição</h2>
          <Distribution slices={slices} />
        </section>
      </div>

      {missing.length > 0 && (
        <p className="alert warning">Sem cotação para {missing.join(', ')}: os totais ficam incompletos.</p>
      )}
      {stale.length > 0 && (
        <p className="alert warning">
          Fonte de cotações indisponível. Usando o último preço conhecido:{' '}
          {stale.map((p) => `${p.ticker} (${p.price_as_of ? localTime(p.price_as_of) : '?'})`).join(', ')}.
        </p>
      )}

      {open.length > 0 && (
        <section className="card" aria-labelledby="positions-title">
          <div className="card-head">
            <h2 id="positions-title">Posições</h2>
            <span className="muted">{open.length === 1 ? '1 ativo' : `${open.length} ativos`}</span>
          </div>
          {/* data-label names each value when a row turns into a card on phones. */}
          <div className="table-wrap">
            <table className="data positions" aria-label="Posições">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th className="num">Qtd</th>
                  <th className="num">Preço médio</th>
                  <th className="num">Cotação</th>
                  <th className="num">Investido</th>
                  <th className="num">Valor atual</th>
                  <th className="num">Resultado</th>
                  <th className="num">Proventos</th>
                </tr>
              </thead>
              <tbody>
                {open.map((p) => (
                  <tr key={p.ticker}>
                    <th scope="row" className="ticker">{p.ticker}</th>
                    <td className="num qty" data-label="Qtd">{quantity(p.quantity)}</td>
                    <td className="num avg" data-label="Preço médio">{brl(p.avg_price)}</td>
                    <td className="num price" data-label="Cotação">{brl(p.current_price)}</td>
                    <td className="num invested" data-label="Investido">{brl(p.invested)}</td>
                    <td className="num value">{brl(p.current_value)}</td>
                    <td className="num result">
                      {p.result == null ? (
                        '—'
                      ) : (
                        <>
                          <span className={toneOf(p.result)}>{brl(p.result)}</span>{' '}
                          <span className={`chip ${toneOf(p.result) ?? ''}`}>{pct(p.result_pct)}</span>
                        </>
                      )}
                    </td>
                    <td className="num income" data-label="Proventos">{brl(p.income)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <FixedIncomeCard />
    </div>
  )
}
