import { useId, type ReactNode } from 'react'
import type { Period, Schemas } from '../api/queries'
import { brDate, pct, toneOf } from '../format'
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
  footer,
}: {
  perf: Schemas['PerformanceOut']
  period: Period
  onPeriod: (period: Period) => void
  /** A new period is loading: the current one stays, faded. */
  updating?: boolean
  /** The chart's height in px; the Carteira matches its net worth chart's. */
  chartHeight?: number
  footer?: ReactNode
}) {
  const titleId = useId()

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
          <span className={`chart-figure ${toneOf(perf.twr) ?? ''}`}>{pct(perf.twr)}</span>
          <span className="muted">
            de {brDate(perf.start)} a {brDate(perf.as_of)}
          </span>
        </p>
      )}
      <div className={updating ? 'chart-updating' : undefined}>
        <PerformanceChart points={perf.points} height={chartHeight} />
      </div>
      <p className="chart-note">
        Até o último fechamento oficial. Rentabilidade ponderada pelo tempo (TWR): aportes e vendas não distorcem o
        resultado, e os proventos contam como retorno.
      </p>
      {footer}
    </section>
  )
}
