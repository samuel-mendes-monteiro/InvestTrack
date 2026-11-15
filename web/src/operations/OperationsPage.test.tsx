import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { operation } from '../test/samples'
import { OperationForm } from './OperationForm'
import { OperationsPage } from './OperationsPage'

const OPERATIONS = [
  operation(),
  operation({ id: 2, ticker: 'VALE3', op_type: 'SELL', date: '2026-04-01', quantity: '10', price: '60.5', fees: '0' }),
]

test('lists operations and filters by ticker', async () => {
  fakeApi({ 'GET /operations': { body: OPERATIONS }, 'GET /stock-events': { body: [] } })
  renderWithApp(<OperationsPage />)

  expect(await screen.findByRole('row', { name: /VALE3/ })).toHaveTextContent('01/04/2026VendaVALE310R$ 60,50R$ 0,00')
  await userEvent.selectOptions(screen.getByLabelText('Ticker'), 'PETR4')
  expect(screen.queryByRole('row', { name: /VALE3/ })).not.toBeInTheDocument()
  expect(screen.getByRole('row', { name: /PETR4/ })).toBeInTheDocument()
})

test('creating an operation sends exact decimals typed the Brazilian way', async () => {
  const api = fakeApi({ 'POST /operations': { status: 201, body: operation() } })
  const onClose = vi.fn()
  renderWithApp(<OperationForm onClose={onClose} />)
  const user = userEvent.setup()

  await user.type(screen.getByLabelText('Ticker'), 'petr4 ')
  await user.selectOptions(screen.getByLabelText(/Classe do ativo/), 'FII')
  await user.clear(screen.getByLabelText('Data'))
  await user.type(screen.getByLabelText('Data'), '2026-03-10')
  await user.type(screen.getByLabelText('Quantidade'), '1.000')
  await user.type(screen.getByLabelText('Preço unitário (R$)'), '30,5')
  await user.click(screen.getByRole('button', { name: 'Registrar' }))

  await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(await api.sent('POST /operations')).toEqual([
    {
      op_type: 'BUY',
      ticker: 'PETR4',
      asset_type: 'FII',
      date: '2026-03-10',
      quantity: '1.000', // no comma: a dot is the decimal point, as the API reads it
      price: '30.5',
      fees: '0',
    },
  ])
})

test('a missing field is caught before the API', async () => {
  const api = fakeApi({})
  renderWithApp(<OperationForm onClose={() => {}} />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Ticker'), 'PETR4')
  await user.type(screen.getByLabelText('Quantidade'), '100')
  await user.click(screen.getByRole('button', { name: 'Registrar' }))

  expect(screen.getByRole('alert')).toHaveTextContent('Preencha o campo Preço.')
  expect(api.requests).toHaveLength(0)
})

test("the API's refusal is shown in Portuguese and the form stays open", async () => {
  fakeApi({
    'POST /operations': {
      status: 422,
      body: {
        detail: {
          code: 'INSUFFICIENT_POSITION',
          message: 'x',
          ticker: 'PETR4',
          available: '50',
          requested: '100',
        },
      },
    },
  })
  const onClose = vi.fn()
  renderWithApp(<OperationForm onClose={onClose} />)
  const user = userEvent.setup()
  await user.click(screen.getByLabelText('Venda'))
  await user.type(screen.getByLabelText('Ticker'), 'PETR4')
  await user.type(screen.getByLabelText('Quantidade'), '100')
  await user.type(screen.getByLabelText('Preço unitário (R$)'), '30')
  await user.click(screen.getByRole('button', { name: 'Registrar' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Você tem 50 PETR4 nessa data e tentou vender 100.')
  expect(onClose).not.toHaveBeenCalled()
})

test('editing starts from the operation and saves with PUT', async () => {
  const api = fakeApi({
    'GET /operations': { body: OPERATIONS },
    'GET /stock-events': { body: [] },
    'PUT /operations/1': { body: operation({ fees: '9.90' }) },
  })
  renderWithApp(<OperationsPage />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Editar operação #1' }))
  const dialog = screen.getByRole('dialog', { name: 'Editar operação #1' })
  expect(within(dialog).getByLabelText('Quantidade')).toHaveValue('100')
  expect(within(dialog).getByLabelText('Taxas (R$)')).toHaveValue('4,9')

  await user.clear(within(dialog).getByLabelText('Taxas (R$)'))
  await user.type(within(dialog).getByLabelText('Taxas (R$)'), '9,90')
  await user.click(within(dialog).getByRole('button', { name: 'Salvar alterações' }))

  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(await api.sent('PUT /operations/1')).toEqual([
    expect.objectContaining({ ticker: 'PETR4', quantity: '100', price: '30', fees: '9.90' }),
  ])
})

test('deleting asks first, then refetches', async () => {
  const api = fakeApi({
    'GET /operations': { body: OPERATIONS },
    'GET /stock-events': { body: [] },
    'DELETE /operations/2': { status: 204 },
  })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderWithApp(<OperationsPage />)

  await userEvent.click(await screen.findByRole('button', { name: 'Apagar operação #2' }))

  expect(confirm).toHaveBeenCalledWith('Apagar a operação #2 (Venda de 10 VALE3 em 01/04/2026)?')
  await vi.waitFor(() => expect(api.requests.filter((r) => r.method === 'GET' && r.url.endsWith('/operations'))).toHaveLength(2))
  confirm.mockRestore()
})

test('a refused delete explains why', async () => {
  fakeApi({
    'GET /operations': { body: OPERATIONS },
    'GET /stock-events': { body: [] },
    'DELETE /operations/1': {
      status: 409,
      body: { detail: { code: 'DELETE_BREAKS_LATER_SALE', message: 'x', ticker: 'PETR4' } },
    },
  })
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderWithApp(<OperationsPage />)

  await userEvent.click(await screen.findByRole('button', { name: 'Apagar operação #1' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Não foi possível apagar: Apagar essa operação deixaria uma venda posterior de PETR4',
  )
  vi.restoreAllMocks()
})

test("the price fills in with the ticker's close on the operation's day", async () => {
  const api = fakeApi({
    'GET /prices/VALE3': { body: { ticker: 'VALE3', date: '2026-03-06', price: '61.40', source: 'CLOSE' } },
    'POST /operations': { status: 201, body: operation() },
  })
  const onClose = vi.fn()
  renderWithApp(<OperationForm onClose={onClose} />)
  const user = userEvent.setup()

  await user.clear(screen.getByLabelText('Data'))
  await user.type(screen.getByLabelText('Data'), '2026-03-08') // a Sunday: Friday's close
  await user.type(screen.getByLabelText('Ticker'), 'vale3')

  expect(await screen.findByDisplayValue('61,40')).toBe(screen.getByLabelText(/^Preço unitário/))
  expect(screen.getByText('Fechamento de 06/03/2026.')).toBeInTheDocument()
  const asked = api.requests.find((r) => r.url.includes('/prices/'))!
  expect(new URL(asked.url).searchParams.get('date')).toBe('2026-03-08')

  await user.type(screen.getByLabelText('Quantidade'), '10')
  await user.click(screen.getByRole('button', { name: 'Registrar' }))
  await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
  expect((await api.sent('POST /operations'))[0].price).toBe('61.40')
})

test('a typed price wins over the suggestion, which can be brought back', async () => {
  fakeApi({ 'GET /prices/PETR4': { body: { ticker: 'PETR4', date: '2026-11-14', price: '38.00', source: 'QUOTE' } } })
  renderWithApp(<OperationForm onClose={() => {}} />)
  const user = userEvent.setup()

  await user.type(screen.getByLabelText('Ticker'), 'PETR4')
  const price = screen.getByLabelText(/^Preço unitário/)
  await vi.waitFor(() => expect(price).toHaveValue('38,00'))
  expect(screen.getByText('Cotação atual. Confira o preço pago.')).toBeInTheDocument()

  await user.clear(price)
  await user.type(price, '37,9')
  expect(price).toHaveValue('37,9')
  await user.click(screen.getByRole('button', { name: 'Usar a cotação da data' }))
  expect(price).toHaveValue('38,00')
})

test('without a price for that day, the user is asked to type it', async () => {
  fakeApi({ 'GET /prices/XPTO3': { status: 404, body: { detail: { code: 'PRICE_NOT_FOUND', message: 'x' } } } })
  renderWithApp(<OperationForm onClose={() => {}} />)
  await userEvent.type(screen.getByLabelText('Ticker'), 'XPTO3')
  expect(await screen.findByText('Sem cotação para essa data: digite o preço.')).toBeInTheDocument()
  expect(screen.getByLabelText(/^Preço unitário/)).toHaveValue('')
})

test('editing keeps the price the operation was made at', async () => {
  const api = fakeApi({})
  renderWithApp(<OperationForm operation={operation()} onClose={() => {}} />)
  expect(screen.getByLabelText(/^Preço unitário/)).toHaveValue('30')
  await new Promise((r) => setTimeout(r, 500)) // past the debounce
  expect(api.requests).toHaveLength(0)
})
