import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { performance, portfolio, position } from '../test/samples'
import { NetWorthPage } from './NetWorthPage'

test('charts the net worth over time, ending now at the Patrimônio card', async () => {
  fakeApi({
    // Net worth now: 8000.00 + 500.00, after the last close (13/11) of the history.
    'GET /portfolio': { body: portfolio([position()], { current_value: '8000.00', fixed_income: '500.00' }) },
    'GET /performance': { body: performance() },
  })
  renderWithApp(<NetWorthPage />)

  const chart = await screen.findByRole('region', { name: 'Evolução do patrimônio' })
  // The gain over everything: net worth now (8500.00) minus the money put in
  // until now (6000.00, a buy today included), not minus the first close.
  expect(await within(chart).findByText('+R$ 2.500,00')).toBeInTheDocument()
  expect(chart).toHaveTextContent('de ganho, de 05/01/2026 a hoje')
  expect(chart).toHaveTextContent('Patrimônio R$ 8.500,00 · Aportes no período R$ 6.000,00')
})

test('without a quote for every ticker, the chart stops at the last close', async () => {
  fakeApi({
    'GET /portfolio': { body: portfolio([position()], { current_value: null }) },
    'GET /performance': { body: performance() },
  })
  renderWithApp(<NetWorthPage />)

  const chart = await screen.findByRole('region', { name: 'Evolução do patrimônio' })
  // net_worth (fixed income after taxes, like the Patrimônio card) minus the
  // money put in until that close: 8390.15 - 5000.00.
  expect(await within(chart).findByText('+R$ 3.390,15')).toBeInTheDocument()
  expect(chart).toHaveTextContent('de 05/01/2026 a 13/11/2026')
})

test("today's split is under the chart", async () => {
  fakeApi({
    'GET /portfolio': { body: portfolio([position()], { current_value: '8000.00', fixed_income: '500.10' }) },
    'GET /performance': { body: performance() },
  })
  renderWithApp(<NetWorthPage />)

  const metric = (label: string) => screen.getByText(label, { selector: '.metric-label' }).parentElement!
  expect(await screen.findByText('Patrimônio hoje')).toBeInTheDocument()
  expect(metric('Patrimônio hoje')).toHaveTextContent('R$ 8.500,10')
  expect(metric('Ações, FIIs e ETFs')).toHaveTextContent('R$ 8.000,00')
  expect(metric('Renda fixa (líquida)')).toHaveTextContent('R$ 500,10')
})

test('fees are money put in: the gain matches the position result (the ITUB4 case)', async () => {
  // 50 ITUB4 bought at the close (39.32) plus 7.90 in fees, now at 42.27.
  fakeApi({
    'GET /portfolio': { body: portfolio([position()], { current_value: '2113.50', fixed_income: '0.00' }) },
    'GET /performance': {
      body: performance({
        start: '2026-01-07',
        invested_now: '1973.90',
        points: [
          { date: '2026-01-07', twr: '0', twr_price: '0', cdi: '0', ibovespa: '0', value: '1966.00', net_worth: '1966.00', invested: '1973.90' },
          { date: '2026-11-13', twr: '7', twr_price: '7', cdi: '12', ibovespa: '7', value: '2100.00', net_worth: '2100.00', invested: '1973.90' },
        ],
      }),
    },
  })
  renderWithApp(<NetWorthPage />)

  const chart = await screen.findByRole('region', { name: 'Evolução do patrimônio' })
  // 2113.50 - 1973.90, the same as the position's Resultado; not 2113.50 - 1966.00.
  expect(await within(chart).findByText('+R$ 139,60')).toBeInTheDocument()
})

test('over a period, the gain leaves out what was put in during it', async () => {
  fakeApi({
    'GET /portfolio': { body: portfolio([position()], { current_value: '1600.00', fixed_income: '0.00' }) },
    'GET /performance': (request) => {
      const period = new URL(request.url).searchParams.get('period')
      return {
        body: performance({
          invested_now: '1500.00',
          points:
            period === '1M'
              ? [
                  // 1000 at the period's start, then 600 more put in (900 -> 1500 by now).
                  { date: '2026-10-13', twr: '0', twr_price: '0', cdi: '0', ibovespa: '0', value: '1000.00', net_worth: '1000.00', invested: '900.00' },
                  { date: '2026-11-13', twr: '1', twr_price: '1', cdi: '1', ibovespa: '1', value: '1580.00', net_worth: '1580.00', invested: '1400.00' },
                ]
              : performance().points,
        }),
      }
    },
  })
  renderWithApp(<NetWorthPage />)
  const chart = await screen.findByRole('region', { name: 'Evolução do patrimônio' })
  await userEvent.click(within(chart).getByRole('button', { name: '1M' }))

  // (1600 - 1000) - (1500 - 900): the net worth grew 600, 600 of it was put in.
  expect(await within(chart).findByText('+R$ 0,00')).toBeInTheDocument()
})
