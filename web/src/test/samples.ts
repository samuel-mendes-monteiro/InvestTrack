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

export function income(overrides: Partial<Schemas['IncomeOut']> = {}): Schemas['IncomeOut'] {
  return {
    id: null,
    ticker: 'PETR4',
    income_type: 'DIVIDEND',
    date: '2026-03-20',
    record_date: '2026-03-05',
    quantity: '100.00000000',
    rate: '0.4512',
    amount: '45.12',
    tax: '0.00',
    net: '45.12',
    source: 'B3',
    pending: false,
    ...overrides,
  }
}

export function month(year: number, m: number, overrides: Partial<Schemas['MonthlyIncomeOut']> = {}) {
  return { year, month: m, dividend: '0.00', jcp: '0.00', distribution: '0.00', tax: '0.00', net: '0.00', ...overrides }
}

export function stockEvent(overrides: Partial<Schemas['StockEventOut']> = {}): Schemas['StockEventOut'] {
  return {
    ticker: 'ITSA4',
    event_type: 'BONUS',
    record_date: '2026-02-01',
    multiplier: '1.1',
    quantity_before: '100.00000000',
    quantity_after: '110.00000000',
    unit_cost: null,
    ...overrides,
  }
}

export function fixedIncome(overrides: Partial<Schemas['FixedIncomeOut']> = {}): Schemas['FixedIncomeOut'] {
  return {
    id: 1,
    name: 'CDB Banco X',
    product: 'CDB',
    indexer: 'CDI',
    rate: '110.00',
    start: '2026-01-05',
    maturity: '2027-01-05',
    amount: '5000.00',
    principal: '5000.00',
    gross: '5400.10',
    iof: '0.00',
    ir: '80.02',
    net: '5320.08',
    gross_return: '8.00',
    as_of: '2026-11-13',
    estimated: false,
    redeemed_on: null,
    status: 'ACTIVE',
    partial_redemptions: [],
    ...overrides,
  }
}
