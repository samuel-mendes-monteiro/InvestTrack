import { useId, useState, type ReactNode } from 'react'
import type { Period, Schemas } from '../api/queries'
import { brDate, pct, sumDecimals, toneOf } from '../format'
import { PERIODS } from '../labels'
import { PerformanceChart } from './PerformanceChart'

/**
 * The cumulative return chart in its card: title and periods on top, the
 * period's return big, the chart, and how to read it. The same frame as the
 * net worth chart, shown on the Rentabilidade page and on the Carteira.
 */
export function PerformanceCard({
  perf,
  period,
  onPeriod,
  updating = false,
  chartHeight,
  withIncome,
  onWithIncome,
  footer,
}: {
  perf: Schemas['PerformanceOut']
  period: Period
  onPeriod: (period: Period) => void
  /** A new period is loading: the current one stays, faded. */
  updating?: boolean
  /** The chart's height in px; the Carteira matches its net worth chart's. */
  chartHeight?: number
  /** Count income as return. The page that also shows numbers outside the
   *  card controls it; otherwise the card keeps its own. */
  withIncome?: boolean
  onWithIncome?: (withIncome: boolean) => void
  footer?: ReactNode
}) {
  const titleId = useId()
  const [ownWithIncome, setOwnWithIncome] = useState(true)
  const income = withIncome ?? ownWithIncome
  const setIncome = onWithIncome ?? setOwnWithIncome
  const shown = income ? perf.twr : (perf.twr_price ?? null)

  return (
    <section className="card chart-card" aria-labelledby={titleId}>
      <div className="card-head">
        <h2 id={titleId}>Rentabilidade acumulada</h2>
        <div className="segmented-buttons" role="group" aria-label="Período">
          {PERIODS.map((p) => (
            <button key={p.value} aria-pressed={period === p.value} title={p.name} onClick={() => onPeriod(p.value)}>
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {perf.start && perf.as_of && (
        <p className="chart-caption">
          <span className={`chart-figure ${toneOf(shown) ?? ''}`}>{pct(shown)}</span>
          <span className="muted">
            de {brDate(perf.start)} a {brDate(perf.as_of)}
          </span>
        </p>
      )}
      <div className="return-split-row">
        {income ? (
          <ReturnSplit twr={perf.twr} twrPrice={perf.twr_price ?? null} />
        ) : (
          <p className="chart-subcaption muted">Só a cotação, com as taxas; proventos fora da conta</p>
        )}
        <label className="switch">
          <input type="checkbox" role="switch" checked={income} onChange={(e) => setIncome(e.target.checked)} />
          <span className="switch-track" aria-hidden="true" />
          Incluir proventos
        </label>
      </div>
      <div className={updating ? 'chart-updating' : undefined}>
        <PerformanceChart points={perf.points} height={chartHeight} withIncome={income} />
      </div>
      <p className="chart-note">
        Até o último fechamento oficial. Rentabilidade ponderada pelo tempo (TWR): aportes e vendas não distorcem o
        resultado.{' '}
        {income
          ? 'Os proventos contam como retorno, como se fossem reinvestidos; por isso ela é maior que o Resultado da Carteira, que só olha a cotação.'
          : 'Sem os proventos, só a variação da cotação, com as taxas: a mesma base do Resultado da Carteira.'}
      </p>
      {footer}
    </section>
  )
}

/**
 * Where the return came from: prices (fees included) and income. Shown as two
 * parts that add up to the total, so the reader can check it at a glance; the
 * TWR compounds them, so this split is the difference, not a second TWR.
 */
function ReturnSplit({ twr, twrPrice }: { twr: string | null; twrPrice: string | null }) {
  if (twr == null || twrPrice == null) return null
  const income = sumDecimals([twr, twrPrice.startsWith('-') ? twrPrice.slice(1) : `-${twrPrice}`])
  return (
    <p className="chart-subcaption muted">
      Cotação <span className={toneOf(twrPrice)}>{pct(twrPrice)}</span> · Proventos{' '}
      <span className={toneOf(income)}>{pct(income)}</span>
    </p>
  )
}
