import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Schemas } from '../api/queries'
import { brl } from '../format'
import { INCOME_TYPES, MONTHS } from '../labels'

const SERIES = [
  { key: 'dividend', label: INCOME_TYPES.DIVIDEND, color: 'var(--accent)' },
  { key: 'jcp', label: INCOME_TYPES.JCP, color: '#f28e2b' },
  { key: 'distribution', label: INCOME_TYPES.DISTRIBUTION, color: '#59a14f' },
] as const

// Axis labels only ("R$ 1,2 mil"): rounded on purpose, the tooltip has the exact value.
const axisMoney = new Intl.NumberFormat('pt-BR', {
  style: 'currency',
  currency: 'BRL',
  notation: 'compact',
  maximumFractionDigits: 1,
})

/** Net income per month, stacked by type, in the same frame as the other charts. */
export function MonthlyChart({ months }: { months: Schemas['MonthlyIncomeOut'][] }) {
  // Number() only for bar heights; the tooltip shows the API's exact strings.
  const data = months.map((m) => ({
    month: `${MONTHS[m.month - 1]}/${String(m.year % 100).padStart(2, '0')}`,
    ...Object.fromEntries(SERIES.map((s) => [s.key, Number(m[s.key])])),
    exact: m,
  }))
  // Only the types that appear get a place in the legend.
  const present = SERIES.filter((s) => months.some((m) => Number(m[s.key]) > 0))

  return (
    <>
      <ul className="chart-legend" aria-hidden="true">
        {present.map((s) => (
          <li key={s.key}>
            <span className="swatch" style={{ background: s.color }} />
            {s.label}
          </li>
        ))}
      </ul>
      <div className="chart" aria-hidden="true">
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="month" tickLine={false} axisLine={false} stroke="var(--muted)" />
            <YAxis
              tickLine={false}
              axisLine={false}
              stroke="var(--muted)"
              width={76}
              tickFormatter={(v: number) => axisMoney.format(v)}
            />
            <Tooltip
              cursor={{ fill: 'var(--border)', opacity: 0.4 }}
              contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
              labelStyle={{ color: 'var(--text)' }}
              formatter={(_v, name, item) => {
                const s = SERIES.find((x) => x.label === name)!
                return [brl(item.payload.exact[s.key]), name]
              }}
            />
            {SERIES.map((s) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stackId="income"
                fill={s.color}
                maxBarSize={44}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}
