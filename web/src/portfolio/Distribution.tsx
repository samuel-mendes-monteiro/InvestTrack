import { Cell, Pie, PieChart, Tooltip } from 'recharts'
import { brl, sumDecimals } from '../format'

// Categorical palette, ordered so neighbours in the donut stay distinguishable.
const COLORS = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#76b7b2', '#edc948', '#b07aa1', '#ff9da7', '#9c755f']
const OTHERS = '#8b949e'
const MAX_SLICES = COLORS.length

export type Slice = { name: string; value: string }

/**
 * Donut of where the money is, with a legend that carries the exact values.
 * The biggest slices get their own color; the rest are grouped as "Outros",
 * since 20 thin slices can't be told apart.
 */
export function Distribution({ slices }: { slices: Slice[] }) {
  // Number() only to draw and to show shares: a pixel or a rounded 12,3% can't
  // be wrong by a cent. Every amount shown is still the API's exact string.
  const sorted = [...slices].sort((a, b) => Number(b.value) - Number(a.value))
  const total = sorted.reduce((sum, s) => sum + Number(s.value), 0)
  if (total <= 0) return <p className="muted">Sem cotações para montar o gráfico.</p>

  const shown = sorted.slice(0, sorted.length > MAX_SLICES ? MAX_SLICES - 1 : MAX_SLICES)
  const rest = sorted.slice(shown.length)
  const data = shown.map((s, i) => ({ name: s.name, amount: brl(s.value), size: Number(s.value), color: COLORS[i] }))
  if (rest.length) {
    const amount = sumDecimals(rest.map((s) => s.value))
    data.push({ name: `Outros (${rest.length})`, amount: brl(amount), size: Number(amount), color: OTHERS })
  }
  const share = (size: number) => `${((size / total) * 100).toFixed(1).replace('.', ',')}%`

  return (
    <div className="distribution">
      <div className="donut">
        <PieChart width={200} height={200} aria-hidden="true">
          <Pie data={data} dataKey="size" nameKey="name" innerRadius={64} outerRadius={96} paddingAngle={1} stroke="var(--surface)" strokeWidth={2} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.color} />
            ))}
          </Pie>
          <Tooltip
            formatter={(_value, _name, item) => [item.payload.amount, item.payload.name]}
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
            itemStyle={{ color: 'var(--text)' }}
          />
        </PieChart>
        {/* Exact sum of the API strings, not of the Numbers drawn above. */}
        <div className="donut-center" aria-hidden="true">
          <span className="muted">Total</span>
          <strong>{brl(sumDecimals(slices.map((s) => s.value)))}</strong>
        </div>
      </div>
      <table className="legend" aria-label="Distribuição">
        <tbody>
          {data.map((d) => (
            <tr key={d.name}>
              <td className="legend-name">
                <span className="swatch" style={{ background: d.color }} />
                {d.name}
              </td>
              <td className="num">{share(d.size)}</td>
              <td className="num muted">{d.amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
