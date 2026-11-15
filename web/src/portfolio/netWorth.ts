import type { Schemas } from '../api/queries'
import { sumDecimals } from '../format'

/**
 * Stocks, FIIs and ETFs at the current quotes, plus fixed income net of taxes:
 * the Patrimônio card's number. Added exactly; null (a position without a
 * quote, or fixed income still being valued) stays unknown instead of becoming
 * a smaller, wrong total.
 */
export function netWorth(totals: Schemas['PortfolioTotals']): string | null {
  if (totals.current_value == null || totals.fixed_income == null) return null
  return sumDecimals([totals.current_value, totals.fixed_income])
}
