import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Schemas } from '../api/queries'
import { brDate, pct } from '../format'

const SERIES = [
  { key: 'twr', label: 'Carteira', color: '#4e79a7', width: 2.5 },
  { key: 'cdi', label: 'CDI', color: '#f28e2b', width: 1.5 },
  { key: 'ibovespa', label: 'Ibovespa', color: '#59a14f', width: 1.5 },
] as const

type Point = Schemas['PerformancePoint']

/** Cumulative return of the portfolio against CDI and Ibovespa, in %. */
export function PerformanceChart({ points }: { points: Point[] }) {
  // Number() only for drawing; the tooltip shows the API's exact strings.
  const data = points.map((p) => ({
    date: p.date,
    twr: Number(p.twr),
    cdi: p.cdi == null ? null : Number(p.cdi),
    ibovespa: p.ibovespa == null ? null : Number(p.ibovespa),
    exact: p,
  }))

  return (
    <div className="chart" aria-hidden="true">
      <ResponsiveContainer width="100%" height={360}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis
            dataKey="date"
            tickLine={false}
            stroke="var(--muted)"
            minTickGap={48}
            tickFormatter={(d: string) => brDate(d).slice(0, 5)}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            stroke="var(--muted)"
            width={52}
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          />
          <Tooltip
            contentStyle={{ background: 'var(--bg)', border: '1px solid var(--border)' }}
            labelFormatter={(d) => brDate(String(d))}
            formatter={(_v, name, item) => {
              const s = SERIES.find((x) => x.label === name)!
              return [pct(item.payload.exact[s.key]), name]
            }}
          />
          <Legend itemSorter={null} /* keep the series order, not alphabetical */ />
          {SERIES.map((s) => (
            <Line
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={s.width}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
