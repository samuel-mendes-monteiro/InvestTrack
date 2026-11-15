import { useId, useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usePerformance, type Period } from '../api/queries'
import { brDate, brl, sumDecimals, todayIso, toneOf } from '../format'
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
 *
 * `current` is the net worth right now, the Patrimônio card's number. The
 * history stops at B3's last official close, so a sale or redemption made
 * today (or on a weekend) wouldn't show yet: it becomes the last point.
 */
export function NetWorthChart({ current, height = 280 }: { current: string | null; height?: number }) {
  // Its own period: unlike Rentabilidade, it isn't kept in the URL.
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
      <NetWorthBody
        performance={performance}
        period={period}
        gradient={gradient}
        current={current}
        height={height}
      />
    </section>
  )
}

function NetWorthBody({
  performance,
  period,
  gradient,
  current,
  height,
}: {
  performance: ReturnType<typeof usePerformance>
  period: Period
  gradient: string
  current: string | null
  height: number
}) {
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

  // net_worth, not value: fixed income net of taxes, as the Patrimônio card counts it.
  // invested: money put in until then (buys with their fees, minus sales).
  const series = points.map((p) => ({ date: p.date, exact: p.net_worth, invested: p.invested, now: false }))
  const today = todayIso()
  const investedNow = performance.data.invested_now
  // Unknown (a ticker without a quote, a redemption not valued yet) adds
  // nothing: better a line that stops at the last close than a wrong end.
  if (current != null && investedNow != null && series[series.length - 1].date < today) {
    series.push({ date: today, exact: current, invested: investedNow, now: true })
  }
  const first = series[0]
  const last = series[series.length - 1]
  // The gain: what net worth grew beyond the money put in. Over the whole
  // history it starts from nothing, so the first purchase (with its fees)
  // counts as money in; over a period, from that period's first close.
  const base = period === 'ALL' ? { exact: '0', invested: '0' } : first
  const deposits = sumDecimals([last.invested, negate(base.invested)])
  // Exact, from the API's strings; only the line itself is drawn with Number().
  const gain = sumDecimals([last.exact, negate(base.exact), negate(deposits)])
  const data = series.map((p) => ({ ...p, size: Number(p.exact) }))

  return (
    <>
      <p className="chart-caption">
        <span className={`chart-figure ${toneOf(gain) ?? ''}`}>
          {gain.startsWith('-') ? '' : '+'}
          {brl(gain)}
        </span>
        <span className="muted">
          de ganho, de {brDate(first.date)} a {last.now ? 'hoje' : brDate(last.date)}
        </span>
      </p>
      <p className="chart-subcaption muted">
        Patrimônio {brl(last.exact)} · {deposits.startsWith('-') ? 'Retiradas' : 'Aportes'} no período{' '}
        {brl(deposits.replace(/^-/, ''))}
      </p>
      <div className={`chart ${performance.isPlaceholderData ? 'chart-updating' : ''}`} aria-hidden="true">
        <ResponsiveContainer width="100%" height={height}>
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
              labelFormatter={(d, payload) =>
                payload[0]?.payload.now ? `Hoje (cotação atual)` : `${brDate(String(d))} (fechamento)`
              }
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
      <p className="chart-note">
        Ganho é quanto o patrimônio cresceu além do dinheiro colocado: compras com as taxas, menos vendas; aplicações,
        menos resgates. Proventos recebidos não entram. Cada ponto é um fechamento da B3; o último é agora.
      </p>
    </>
  )
}
