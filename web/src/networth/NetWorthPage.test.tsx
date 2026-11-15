import { screen, within } from '@testing-library/react'
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
  // From the first close (net_worth 3000.00) to now: a sale or redemption made
  // today, after B3's last close, already counts.
  expect(await within(chart).findByText('+R$ 5.500,00')).toBeInTheDocument()
  expect(chart).toHaveTextContent('de 05/01/2026 a hoje')
})

test('without a quote for every ticker, the chart stops at the last close', async () => {
  fakeApi({
    'GET /portfolio': { body: portfolio([position()], { current_value: null }) },
    'GET /performance': { body: performance() },
  })
  renderWithApp(<NetWorthPage />)

  const chart = await screen.findByRole('region', { name: 'Evolução do patrimônio' })
  // net_worth (fixed income after taxes, like the Patrimônio card), not the gross value.
  expect(await within(chart).findByText('+R$ 5.390,15')).toBeInTheDocument()
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
