import { useSearchParams } from 'react-router'
import { usePerformance, type Period } from '../api/queries'
import { Metric } from '../components/Metric'
import { brDate, pct, toneOf, wholePct } from '../format'
import { PERIODS } from '../labels'
import { PerformanceChart } from './PerformanceChart'

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
          {/* The same frame as the Carteira's net worth chart: title and periods on top, a summary line, the chart. */}
          <section className="card chart-card" aria-labelledby="twr-title">
            <div className="card-head">
              <h2 id="twr-title">Rentabilidade acumulada</h2>
              <div className="segmented-buttons" role="group" aria-label="Período">
                {PERIODS.map((p) => (
                  <button
                    key={p.value}
                    aria-pressed={period === p.value}
                    title={p.name}
                    onClick={() => choose(p.value)}
                  >
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
            <div className={performance.isPlaceholderData ? 'chart-updating' : undefined}>
              <PerformanceChart points={perf.points} />
            </div>
            <p className="chart-note">
              Até o último fechamento oficial. Rentabilidade ponderada pelo tempo (TWR): aportes e vendas não distorcem o
              resultado, e os proventos contam como retorno.
            </p>
          </section>

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
