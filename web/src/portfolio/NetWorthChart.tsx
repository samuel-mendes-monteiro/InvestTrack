import { useId, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usePerformance, type Period } from '../api/queries'
import { brDate, brl, sumDecimals, toneOf } from '../format'
import { PERIODS } from '../labels'

// Axis labels only ("R$ 12 mil"): rounded on purpose, the tooltip has the exact value.
const axisMoney = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 1,
})

function negate(value: string): string {
  return value.startsWith('-') ? value.slice(1) : `-${value}`
}

/**
 * Net worth (stocks, FIIs, ETFs and fixed income) at each official close, from
 * the same history the Rentabilidade page uses. Unlike the return there, this
 * line goes up with every deposit too: it is how much there is, not how well it did.
 */
export function NetWorthChart() {
  // Its own period, not the URL's: the Carteira has no ?periodo of its own.
  const [period, setPeriod] = useState<Period>('ALL')
  const performance = usePerformance(period)
  // useId gives ":r1:", and a colon would end the url(#...) that points at the gradient.
  const gradient = `networth-${useId().replace(/:/g, '')}`

  return (
    <section className="card chart-card" aria-labelledby={`${gradient}-title`}>
      <div className="card-head">
        <h2 id={`${gradient}-title`}>Evolução do patrimônio</h2>
        <div className="segmented-buttons" role="group" aria-label="Período">
          {PERIODS.map((p) => (
            <button key={p.value} aria-pressed={period === p.value} title={p.name} onClick={() => setPeriod(p.value)}>
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <NetWorthBody performance={performance} gradient={gradient} />
    </section>
  )
}

function NetWorthBody({ performance, gradient }: { performance: ReturnType<typeof usePerformance>; gradient: string }) {
  if (performance.isPending) return <p className="muted">Carregando o histórico…</p>
  if (performance.isError) return <p className="muted">Não foi possível carregar o histórico do patrimônio.</p>

  const { points, syncing } = performance.data
  if (points.length < 2) {
    return (
      <p className="muted">
        {syncing ? 'Baixando o histórico de cotações; o gráfico aparece em instantes.' : 'Ainda não há histórico suficiente.'}
      </p>
    )
  }

  const first = points[0]
  const last = points[points.length - 1]
  // Exact, from the API's strings; only the line itself is drawn with Number().
  const change = sumDecimals([last.net_worth, negate(first.net_worth)])
  // net_worth, not value: fixed income net of taxes, as the Patrimônio card counts it.
  const data = points.map((p) => ({ date: p.date, size: Number(p.net_worth), exact: p.net_worth }))

  return (
    <>
      <p className="chart-caption">
        <span className={`chart-figure ${toneOf(change) ?? ''}`}>
          {change.startsWith('-') ? '' : '+'}
          {brl(change)}
        </span>
        <span className="muted">
          de {brDate(first.date)} a {brDate(last.date)}
        </span>
      </p>
      <div className={`chart ${performance.isPlaceholderData ? 'chart-updating' : ''}`} aria-hidden="true">
        <ResponsiveContainer width="100%" height={210}>
          <AreaChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              stroke="var(--muted)"
              minTickGap={48}
              tickFormatter={(d: string) => brDate(d).slice(0, 5)}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              stroke="var(--muted)"
              width={76}
              domain={['auto', 'auto']}
              tickFormatter={(v: number) => axisMoney.format(v)}
            />
            <Tooltip
              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
              itemStyle={{ color: 'var(--text)' }}
              labelFormatter={(d) => brDate(String(d))}
              formatter={(_v, _name, item) => [brl(item.payload.exact), 'Patrimônio']}
            />
            <Area
              type="monotone"
              dataKey="size"
              stroke="var(--accent)"
              strokeWidth={2}
              fill={`url(#${gradient})`}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="chart-note">Variação do patrimônio no período, com aportes e resgates incluídos.</p>
    </>
  )
}
