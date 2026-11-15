import type { Schemas } from '../api/queries'
import { sumDecimals } from '../format'

/**
 * Stocks, FIIs and ETFs at the current quotes, plus fixed income net of taxes:
 * the Patrimônio card's number. Added exactly; null (some position without a
 * quote) stays unknown instead of becoming a smaller, wrong total.
 */
export function netWorth(totals: Schemas['PortfolioTotals']): string | null {
  return totals.current_value == null ? null : sumDecimals([totals.current_value, totals.fixed_income])
}
