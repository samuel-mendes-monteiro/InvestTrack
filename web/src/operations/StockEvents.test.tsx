import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { stockEvent } from '../test/samples'
import { StockEvents } from './StockEvents'

const EVENTS = [
  stockEvent(),
  stockEvent({ ticker: 'MGLU3', event_type: 'REVERSE_SPLIT', record_date: '2026-05-01', multiplier: '0.1', quantity_before: '1000', quantity_after: '100' }),
  stockEvent({ ticker: 'BBAS3', record_date: '2026-03-01', multiplier: '1.05', unit_cost: '21.4500000' }),
]

test('lists events and warns about a bonus without cost', async () => {
  fakeApi({ 'GET /stock-events': { body: EVENTS } })
  renderWithApp(<StockEvents />)

  const table = await screen.findByRole('table', { name: 'Desdobramentos e bonificações' })
  expect(within(table).getByRole('row', { name: /ITSA4/ })).toHaveTextContent('01/02/2026Bonificação de 10%ITSA4100110não informado')
  expect(within(table).getByRole('row', { name: /MGLU3/ })).toHaveTextContent('01/05/2026GrupamentoMGLU31.000100')
  expect(within(table).getByRole('row', { name: /BBAS3/ })).toHaveTextContent('R$ 21,45')
  expect(screen.getByText(/Há bonificação sem custo atribuído/)).toBeInTheDocument()
  expect(within(table).queryByRole('button', { name: /MGLU3/ })).not.toBeInTheDocument()
})

test('shows nothing when B3 applied no events', async () => {
  const api = fakeApi({ 'GET /stock-events': { body: [] } })
  const { container } = renderWithApp(<StockEvents />)
  await vi.waitFor(() => expect(api.requests).toHaveLength(1))
  expect(container).toBeEmptyDOMElement()
})

test('saves the attributed cost of a bonus', async () => {
  const api = fakeApi({ 'GET /stock-events': { body: EVENTS }, 'PUT /stock-events/ITSA4/2026-02-01/unit-cost': { status: 204 } })
  renderWithApp(<StockEvents />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Custo atribuído de ITSA4 · 10% em 01/02/2026' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).queryByRole('button', { name: 'Remover custo' })).not.toBeInTheDocument()
  await user.type(within(dialog).getByLabelText(/Custo atribuído por ação/), '7,82')
  await user.click(within(dialog).getByRole('button', { name: 'Salvar' }))

  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(await api.sent('PUT /stock-events/ITSA4/2026-02-01/unit-cost')).toEqual([{ unit_cost: '7.82' }])
})

test('an existing cost starts filled in and can be removed', async () => {
  const api = fakeApi({ 'GET /stock-events': { body: EVENTS }, 'DELETE /stock-events/BBAS3/2026-03-01/unit-cost': { status: 204 } })
  renderWithApp(<StockEvents />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Custo atribuído de BBAS3 · 5% em 01/03/2026' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByLabelText(/Custo atribuído por ação/)).toHaveValue('21,45')
  await user.click(within(dialog).getByRole('button', { name: 'Remover custo' }))

  await vi.waitFor(() => expect(api.requests.some((r) => r.method === 'DELETE')).toBe(true))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
