import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { income, month, operation } from '../test/samples'
import { IncomePage } from './IncomePage'

const INCOMES = [
  income({ date: '2026-03-20', net: '45.12' }),
  income({ id: 7, source: 'MANUAL', ticker: 'AAPL34', date: '2026-05-10', amount: '10.00', tax: '3.00', net: '7.00', record_date: null, quantity: null, rate: null }),
  income({ income_type: 'JCP', date: '2025-12-15', amount: '100.00', tax: '15.00', net: '85.00' }),
  income({ date: '2026-12-01', net: '30.00', pending: true }),
  income({ ticker: 'HGLG11', income_type: 'DISTRIBUTION', date: '2026-12-14', net: '11.00', pending: true }),
]

function metric(label: string) {
  return screen.getByText(label, { selector: '.metric-label' }).parentElement!
}

function routes(extra = {}) {
  return fakeApi({
    'GET /income': { body: INCOMES },
    'GET /operations': { body: [operation(), operation({ id: 2, ticker: 'AAPL34' })] },
    'GET /income/monthly': (request) => {
      const year = new URL(request.url).searchParams.get('year')
      return { body: year === '2026' ? [month(2026, 3, { dividend: '45.12' }), month(2026, 5, { dividend: '7.00' })] : [month(2025, 12, { jcp: '85.00' })] }
    },
    ...extra,
  })
}

test('splits pending and received, newest year first, with exact totals', async () => {
  routes()
  renderWithApp(<IncomePage />)

  expect(await screen.findByRole('heading', { name: 'A receber · R$ 41,00' })).toBeInTheDocument()
  expect(within(screen.getByRole('table', { name: 'A receber' })).getAllByRole('row')).toHaveLength(3)

  const received = screen.getByRole('table', { name: 'Recebidos' })
  expect(within(received).getAllByRole('row')).toHaveLength(3) // header + the two from 2026
  expect(metric('Recebido no ano (líquido)')).toHaveTextContent('R$ 52,12')
  expect(metric('IR retido no ano')).toHaveTextContent('R$ 3,00')
  expect(await screen.findByText('R$ 26,06')).toBeInTheDocument() // 52.12 / 2 months
})

test('choosing another year asks the API for its months', async () => {
  const api = routes()
  renderWithApp(<IncomePage />)
  await userEvent.selectOptions(await screen.findByLabelText('Ano'), '2025')

  expect(metric('Recebido no ano (líquido)')).toHaveTextContent('R$ 85,00')
  await vi.waitFor(() =>
    expect(api.requests.map((r) => new URL(r.url).search)).toContain('?year=2025'),
  )
})

test('only manual income can be deleted', async () => {
  const api = routes({ 'DELETE /income/7': { status: 204 } })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderWithApp(<IncomePage />)

  const received = await screen.findByRole('table', { name: 'Recebidos' })
  expect(within(received).getAllByRole('button')).toHaveLength(1)
  await userEvent.click(within(received).getByRole('button', { name: 'Apagar provento #7' }))

  expect(window.confirm).toHaveBeenCalledWith('Apagar o provento #7 (Dividendo de AAPL34 em 10/05/2026, R$ 7,00 líquido)?')
  await vi.waitFor(() => expect(api.requests.some((r) => r.method === 'DELETE')).toBe(true))
  vi.restoreAllMocks()
})

test('registers manual income for a ticker from the portfolio', async () => {
  const api = routes({ 'POST /income': { status: 201, body: INCOMES[1] } })
  renderWithApp(<IncomePage />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Registrar provento manual' }))
  const dialog = screen.getByRole('dialog', { name: 'Registrar provento' })
  await user.click(within(dialog).getByLabelText('JCP'))
  await user.selectOptions(within(dialog).getByLabelText('Ticker'), 'AAPL34')
  await user.clear(within(dialog).getByLabelText('Data de pagamento'))
  await user.type(within(dialog).getByLabelText('Data de pagamento'), '2026-05-10')
  await user.type(within(dialog).getByLabelText('Valor bruto (R$)'), '1.234,56')
  await user.click(within(dialog).getByRole('button', { name: 'Registrar provento' }))

  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(await api.sent('POST /income')).toEqual([
    { ticker: 'AAPL34', income_type: 'JCP', date: '2026-05-10', amount: '1234.56', tax: '0' },
  ])
})

test('with nothing received yet it says so', async () => {
  fakeApi({ 'GET /income': { body: [] }, 'GET /operations': { body: [] } })
  renderWithApp(<IncomePage />)
  expect(await screen.findByText('Nenhum provento recebido ainda.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Registrar provento manual' })).toBeDisabled()
})
