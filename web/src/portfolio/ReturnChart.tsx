import { useState } from 'react'
import { Link } from 'react-router'
import { usePerformance, type Period } from '../api/queries'
import { PerformanceCard } from '../performance/PerformanceCard'

// Shorter than on the Rentabilidade page: here it shares the column with the numbers.
const HOME_CHART_HEIGHT = 210

/**
 * The Rentabilidade chart on the Carteira, with its own period and a way to the page with the full numbers.
 */
export function ReturnChart() {
  const [period, setPeriod] = useState<Period>('ALL')
  const performance = usePerformance(period)

  // Nothing while loading, on an error or before there is history: the
  // Carteira's numbers above don't depend on it, and the Rentabilidade page says why.
  if (!performance.data || performance.data.points.length < 2) return null

  return (
    <PerformanceCard
      perf={performance.data}
      period={period}
      onPeriod={setPeriod}
      updating={performance.isPlaceholderData}
      chartHeight={HOME_CHART_HEIGHT}
      footer={
        <p className="card-link">
          <Link to={period === 'ALL' ? '/rentabilidade' : `/rentabilidade?periodo=${period}`}>
            Ver CDI, Ibovespa e % do CDI →
          </Link>
        </p>
      }
    />
  )
}
