import { useState } from 'react'
import { Cell, Pie, PieChart, Sector } from 'recharts'
import { brl, sumDecimals } from '../format'

// Categorical palette, ordered so neighbours in the donut stay distinguishable.
const COLORS = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#76b7b2', '#edc948', '#b07aa1', '#ff9da7', '#9c755f']
const OTHERS = '#8b949e'
const MAX_SLICES = COLORS.length

const SIZE = 210
const INNER = 70
const OUTER = 96
const GROW = 6 // how much the slice under the mouse sticks out

export type Slice = { name: string; value: string }

/**
 * Donut of where the money is, with a legend that carries the exact values.
 * The biggest slices get their own color; the rest are grouped as "Outros",
 * since 20 thin slices can't be told apart.
 *
 * Hovering a slice or its legend row puts it in focus: it grows, the others
 * fade, and the center shows its share instead of the total. The center, not
 * a floating tooltip: it never covers the donut, and it is always in the same place.
 */
export function Distribution({ slices }: { slices: Slice[] }) {
  const [active, setActive] = useState<number | null>(null)

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
  const focus = active == null ? null : data[active]
  const faded = (i: number) => active != null && i !== active

  return (
    <div className="distribution" onMouseLeave={() => setActive(null)}>
      <div className="donut">
        <PieChart width={SIZE} height={SIZE} aria-hidden="true">
          <Pie
            data={data}
            dataKey="size"
            nameKey="name"
            innerRadius={INNER}
            outerRadius={OUTER}
            paddingAngle={data.length > 1 ? 2 : 0}
            cornerRadius={4}
            stroke="none"
            isAnimationActive={false}
            onMouseEnter={(_, i) => setActive(i)}
            shape={(props) => (
              <Sector
                {...props}
                outerRadius={props.index === active ? OUTER + GROW : OUTER}
                fillOpacity={faded(props.index) ? 0.35 : 1}
                className="donut-slice"
              />
            )}
          >
            {data.map((d) => (
              <Cell key={d.name} fill={d.color} />
            ))}
          </Pie>
        </PieChart>
        {/* Exact sum of the API strings, not of the Numbers drawn above. */}
        <div className="donut-center" aria-hidden="true">
          {focus ? (
            <>
              <span className="donut-label">
                <span className="swatch" style={{ background: focus.color }} />
                {focus.name}
              </span>
              <strong className="donut-share">{share(focus.size)}</strong>
              <span className="muted">{focus.amount}</span>
            </>
          ) : (
            <>
              <span className="donut-label muted">Total</span>
              <strong>{brl(sumDecimals(slices.map((s) => s.value)))}</strong>
              <span className="muted">
                {slices.length} {slices.length === 1 ? 'item' : 'itens'}
              </span>
            </>
          )}
        </div>
      </div>
      <table className="legend" aria-label="Distribuição">
        <tbody>
          {data.map((d, i) => (
            <tr key={d.name} className={faded(i) ? 'faded' : undefined} onMouseEnter={() => setActive(i)}>
              <td className="legend-name">
                <span className="swatch" style={{ background: d.color }} />
                {d.name}
                <span className="legend-bar" aria-hidden="true">
                  <span style={{ width: share(d.size).replace(',', '.'), background: d.color }} />
                </span>
              </td>
              <td className="num legend-share">{share(d.size)}</td>
              <td className="num muted">{d.amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
