import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Schemas } from '../api/queries'
import { brl } from '../format'
import { INCOME_TYPES, MONTHS } from '../labels'

const SERIES = [
  { key: 'dividend', label: INCOME_TYPES.DIVIDEND, color: '#4e79a7' },
  { key: 'jcp', label: INCOME_TYPES.JCP, color: '#f28e2b' },
  { key: 'distribution', label: INCOME_TYPES.DISTRIBUTION, color: '#59a14f' },
] as const

/** Net income per month, stacked by type. */
export function MonthlyChart({ months }: { months: Schemas['MonthlyIncomeOut'][] }) {
  // Number() only for bar heights; the tooltip shows the API's exact strings.
  const data = months.map((m) => ({
    month: `${MONTHS[m.month - 1]}/${String(m.year % 100).padStart(2, '0')}`,
    ...Object.fromEntries(SERIES.map((s) => [s.key, Number(m[s.key])])),
    exact: m,
  }))

  return (
    <div className="chart" aria-hidden="true">
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="month" tickLine={false} stroke="var(--muted)" />
          <YAxis
            tickLine={false}
            axisLine={false}
            stroke="var(--muted)"
            width={72}
            tickFormatter={(v: number) => brl(String(Math.round(v))).replace(',00', '')}
          />
          <Tooltip
            cursor={{ fill: 'var(--border)', opacity: 0.4 }}
            contentStyle={{ background: 'var(--bg)', border: '1px solid var(--border)' }}
            formatter={(_v, name, item) => {
              const s = SERIES.find((x) => x.label === name)!
              return [brl(item.payload.exact[s.key]), name]
            }}
          />
          <Legend />
          {SERIES.map((s) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} stackId="income" fill={s.color} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
