import { useId } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Schemas } from '../api/queries'
import { brDate, pct } from '../format'

// The portfolio is the accent-colored area, as on the Carteira's net worth
// chart; the benchmarks are thin lines to compare it with.
const SERIES = [
  { key: 'twr', label: 'Carteira', color: 'var(--accent)' },
  { key: 'cdi', label: 'CDI', color: '#f28e2b' },
  { key: 'ibovespa', label: 'Ibovespa', color: '#59a14f' },
] as const

type Point = Schemas['PerformancePoint']

// Axis labels only: whole numbers ("40%") over months, a decimal ("1,5%") over
// a week, where whole numbers would repeat. The tooltip has the exact value.
const axisPct = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 })

/** Cumulative return of the portfolio against CDI and Ibovespa, in %. */
export function PerformanceChart({ points, height = 280 }: { points: Point[]; height?: number }) {
  // useId gives ":r1:", and a colon would end the url(#...) that points at the gradient.
  const gradient = `twr-${useId().replace(/:/g, '')}`
  // Number() only for drawing; the tooltip shows the API's exact strings.
  const data = points.map((p) => ({
    date: p.date,
    twr: Number(p.twr),
    cdi: p.cdi == null ? null : Number(p.cdi),
    ibovespa: p.ibovespa == null ? null : Number(p.ibovespa),
    exact: p,
  }))

  return (
    <>
      <ul className="chart-legend" aria-hidden="true">
        {SERIES.map((s) => (
          <li key={s.key}>
            <span className="swatch" style={{ background: s.color }} />
            {s.label}
          </li>
        ))}
      </ul>
      <div className="chart" aria-hidden="true">
        <ResponsiveContainer width="100%" height={height}>
          <ComposedChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.3} />
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
              width={52}
              tickFormatter={(v: number) => `${axisPct.format(v)}%`}
            />
            <Tooltip
              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
              labelStyle={{ color: 'var(--text)' }}
              labelFormatter={(d) => brDate(String(d))}
              // Carteira, CDI, Ibovespa: the legend's order, not the order they were drawn in.
              itemSorter={(item) => SERIES.findIndex((s) => s.label === item.name)}
              formatter={(_v, name, item) => {
                const s = SERIES.find((x) => x.label === name)!
                return [pct(item.payload.exact[s.key]), name]
              }}
            />
            {/* Drawn first, so the benchmark lines stay visible on top of it. */}
            <Area
              type="monotone"
              dataKey="twr"
              name="Carteira"
              stroke="var(--accent)"
              strokeWidth={2}
              fill={`url(#${gradient})`}
              isAnimationActive={false}
            />
            {SERIES.slice(1).map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                strokeWidth={1.5}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}
