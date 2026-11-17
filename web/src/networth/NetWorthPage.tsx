import { usePortfolio } from '../api/queries'
import { Metric } from '../components/Metric'
import { usePrivateFormat } from '../privacy'
import { netWorth } from '../portfolio/netWorth'
import { NetWorthChart } from './NetWorthChart'

/** How much there is and how it got here: the net worth over time, and today's split. */
export function NetWorthPage() {
  const { brl } = usePrivateFormat()
  const portfolio = usePortfolio()

  if (portfolio.isPending) return <p className="muted">Carregando o patrimônio…</p>
  if (portfolio.isError) return <p className="alert error">{portfolio.error.message}</p>

  const { totals } = portfolio.data
  const total = netWorth(totals)

  return (
    <div className="page">
      <NetWorthChart current={total} />

      {/* Under the chart, as on Rentabilidade: where the line ends today, and what it is made of. */}
      <div className="metrics">
        <Metric label="Patrimônio hoje" value={brl(total)} help="Com a cotação atual e a renda fixa pelo valor líquido." />
        <Metric label="Ações, FIIs e ETFs" value={brl(totals.current_value)} />
        <Metric label="Renda fixa (líquida)" value={brl(totals.fixed_income)} help="Se resgatasse hoje: já descontados IOF e IR." />
      </div>
    </div>
  )
}
