import type { Schemas } from '../api/queries'

// API responses shaped exactly like the real ones (decimals as strings).

export function position(overrides: Partial<Schemas['PositionOut']> = {}): Schemas['PositionOut'] {
  return {
    ticker: 'PETR4',
    quantity: '100.00000000',
    avg_price: '30.00',
    realized_profit: '0.00',
    current_price: '33.00',
    price_as_of: '2026-11-14T13:44:43Z',
    price_stale: false,
    invested: '3000.00',
    current_value: '3300.00',
    result: '300.00',
    result_pct: '10.00',
    income: '45.10',
    ...overrides,
  }
}

export function portfolio(
  positions: Schemas['PositionOut'][],
  totals: Partial<Schemas['PortfolioTotals']> = {},
): Schemas['PortfolioOut'] {
  return {
    positions,
    totals: {
      invested: '3000.00',
      current_value: '3300.00',
      result: '300.00',
      result_pct: '10.00',
      realized_profit: '0.00',
      income: '45.10',
      income_pending: '0.00',
      fixed_income: '0.00',
      ...totals,
    },
  }
}

export function operation(overrides: Partial<Schemas['OperationOut']> = {}): Schemas['OperationOut'] {
  return {
    id: 1,
    ticker: 'PETR4',
    op_type: 'BUY',
    date: '2026-03-10',
    quantity: '100.00000000',
    price: '30.00',
    fees: '4.90',
    ...overrides,
  }
}
