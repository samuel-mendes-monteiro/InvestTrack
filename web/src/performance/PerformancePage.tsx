import { useSearchParams } from 'react-router'
import { usePerformance, type Period } from '../api/queries'
import { Metric } from '../components/Metric'
import { pct, toneOf, wholePct } from '../format'
import { PERIODS } from '../labels'
import { PerformanceCard } from './PerformanceCard'

export function PerformancePage() {
  // The period lives in the URL (?periodo=6M): reload, back and links keep it.
  const [params, setParams] = useSearchParams()
  const period: Period = PERIODS.find((p) => p.value === params.get('periodo'))?.value ?? 'ALL'
  const performance = usePerformance(period)

  function choose(value: Period) {
    setParams(value === 'ALL' ? {} : { periodo: value }, { replace: true })
  }

  if (performance.isPending) return <p className="muted">Calculando a rentabilidade…</p>
  if (performance.isError) return <p className="alert error">{performance.error.message}</p>

  const perf = performance.data

  return (
    <div className="page">
      {perf.syncing && (
        <p className="alert warning" role="status">
          Baixando o histórico de cotações da B3, do Ibovespa e do CDI. Na primeira vez leva cerca de um minuto; depois,
          só o dia novo. A página se atualiza sozinha.
        </p>
      )}

      {!perf.points.length ? (
        !perf.syncing && <p className="muted">Registre uma compra para ver a rentabilidade.</p>
      ) : (
        <>
          <PerformanceCard
            perf={perf}
            period={period}
            onPeriod={choose}
            updating={performance.isPlaceholderData}
          />

          {/* Under the chart: the period's final numbers, once the curve shows how they got there. */}
          <div className="metrics">
            <Metric label="Carteira" value={pct(perf.twr)} tone={toneOf(perf.twr)} />
            <Metric label="CDI" value={pct(perf.cdi)} />
            <Metric label="Ibovespa" value={pct(perf.ibovespa)} />
            <Metric label="% do CDI" value={wholePct(perf.pct_of_cdi)} help="Rentabilidade da carteira dividida pela do CDI." />
          </div>
        </>
      )}
    </div>
  )
}
