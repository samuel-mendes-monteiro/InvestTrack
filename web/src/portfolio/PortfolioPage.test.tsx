import { screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { performance, portfolio, position } from '../test/samples'
import { PortfolioPage } from './PortfolioPage'

function metric(label: string) {
  return screen.getByText(label, { selector: '.metric-label' }).parentElement!
}

test('shows the totals, with fixed income added to the net worth exactly', async () => {
  fakeApi({
    'GET /portfolio': {
      body: portfolio([position()], { current_value: '3300.10', fixed_income: '0.20', income_pending: '12.00' }),
    },
  })
  renderWithApp(<PortfolioPage />)

  expect(await screen.findByText('Patrimônio')).toBeInTheDocument()
  expect(metric('Patrimônio')).toHaveTextContent('R$ 3.300,30')
  expect(metric('Resultado em ações')).toHaveTextContent('R$ 300,00+10,00%')
  expect(metric('Proventos')).toHaveTextContent('R$ 12,00 a receber')
})

test('lists open positions only', async () => {
  fakeApi({
    'GET /portfolio': {
      body: portfolio([position(), position({ ticker: 'VALE3', quantity: '0E-8', current_value: '0.00' })]),
    },
  })
  renderWithApp(<PortfolioPage />)

  const table = await screen.findByRole('table', { name: 'Posições' })
  const row = within(table).getByRole('row', { name: /PETR4/ })
  expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual([
    '100',
    'R$ 30,00',
    'R$ 33,00',
    'R$ 3.000,00',
    'R$ 3.300,00',
    'R$ 300,00 +10,00%',
    'R$ 45,10',
  ])
  expect(within(table).queryByRole('row', { name: /VALE3/ })).not.toBeInTheDocument()
})

test('warns when a quote is missing or stale', async () => {
  fakeApi({
    'GET /portfolio': {
      body: portfolio(
        [
          position({ ticker: 'XPTO3', current_price: null, current_value: null, result: null, result_pct: null }),
          position({ price_stale: true }),
        ],
        { current_value: null },
      ),
    },
  })
  renderWithApp(<PortfolioPage />)

  expect(await screen.findByText(/Sem cotação para XPTO3/)).toBeInTheDocument()
  expect(screen.getByText(/último preço conhecido: PETR4/)).toBeInTheDocument()
  expect(metric('Patrimônio')).toHaveTextContent('—')
})

test('groups the smallest slices of the distribution as "Outros"', async () => {
  const many = Array.from({ length: 12 }, (_, i) =>
    position({ ticker: `TICK${i + 10}`, current_value: `${(i + 1) * 100}.10` }),
  )
  fakeApi({ 'GET /portfolio': { body: portfolio(many) } })
  renderWithApp(<PortfolioPage />)

  // 8 biggest with their own color, then the 4 smallest (100.10 + 200.10 + 300.10 + 400.10).
  expect(await screen.findByText('Outros (4)')).toBeInTheDocument()
  const legend = screen.getByRole('table', { name: 'Distribuição' })
  expect(within(legend).getByRole('row', { name: /Outros/ })).toHaveTextContent('R$ 1.000,40')
  expect(within(legend).getAllByRole('row')).toHaveLength(9)
})

test('an empty portfolio says how to start', async () => {
  fakeApi({ 'GET /portfolio': { body: portfolio([]) } })
  renderWithApp(<PortfolioPage />)
  expect(await screen.findByText(/Nenhuma operação ainda/)).toBeInTheDocument()
})

test('also charts the return, linking to the Rentabilidade page', async () => {
  fakeApi({
    'GET /portfolio': { body: portfolio([position()]) },
    'GET /performance': { body: performance() },
  })
  renderWithApp(<PortfolioPage />)

  const chart = await screen.findByRole('region', { name: 'Rentabilidade acumulada' })
  expect(within(chart).getByText('+48,82%', { selector: '.chart-figure' })).toBeInTheDocument()
  expect(within(chart).getByRole('link', { name: /Ver CDI, Ibovespa/ })).toHaveAttribute('href', '/rentabilidade')
})
