import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { fixedIncome } from '../test/samples'
import { NewOperationDialog } from '../operations/NewOperationDialog'
import { FixedIncomeCard } from './FixedIncomeCard'

const LCI = fixedIncome({
  id: 2,
  name: 'LCI Banco Y',
  product: 'LCI',
  indexer: 'IPCA',
  rate: '6.5',
  principal: '2000.00',
  amount: '3000.00',
  gross: '2100.05',
  iof: '0.00',
  ir: '0.00',
  net: '2100.05',
  estimated: true,
  partial_redemptions: [{ id: 9, date: '2026-06-01', gross: '1000.00', iof: '0.00', ir: '0.00', net: '1000.00' }],
})
const OLD = fixedIncome({ id: 3, name: 'CDB antigo', status: 'REDEEMED', redeemed_on: '2026-03-01', principal: '999.00' })

function metric(label: string) {
  return screen.getByText(label, { selector: 'dt' }).parentElement!
}

test('totals count only active investments, exactly', async () => {
  fakeApi({ 'GET /fixed-income': { body: [fixedIncome(), LCI, OLD] } })
  renderWithApp(<FixedIncomeCard />)

  expect(await screen.findByRole('table', { name: 'Aplicações' })).toBeInTheDocument()
  expect(metric('Aplicado')).toHaveTextContent('R$ 7.000,00')
  expect(metric('Valor bruto')).toHaveTextContent('R$ 7.500,15')
  expect(metric('Valor líquido')).toHaveTextContent('R$ 7.420,13')
  expect(screen.getByText(/IPCA do mês só sai/)).toBeInTheDocument()

  const lci = screen.getByRole('row', { name: /LCI Banco Y/ })
  expect(lci).toHaveTextContent('IPCA + 6,5% a.a.')
  expect(screen.getByRole('row', { name: /CDB antigo/ })).toHaveTextContent('Resgatado')
})

test('a new investment comes from the "Nova operação" dialog, with exact decimals', async () => {
  const api = fakeApi({ 'POST /fixed-income': { status: 201, body: fixedIncome() } })
  const onClose = vi.fn()
  renderWithApp(<NewOperationDialog onClose={onClose} />)
  const user = userEvent.setup()

  const dialog = screen.getByRole('dialog', { name: 'Nova operação' })
  await user.click(within(dialog).getByRole('button', { name: 'Renda fixa' }))
  await user.type(within(dialog).getByLabelText('Nome'), 'LCA Banco Z')
  await user.selectOptions(within(dialog).getByLabelText(/Produto/), 'LCA')
  expect(within(dialog).getByText('LCA é isenta de IR e IOF.')).toBeInTheDocument()
  await user.click(within(dialog).getByLabelText('Prefixado'))
  await user.type(within(dialog).getByLabelText(/Taxa/), '12,5')
  await user.type(within(dialog).getByLabelText('Valor aplicado (R$)'), '5.000,00')
  for (const [label, value] of [['Data da aplicação', '2026-01-05'], ['Vencimento', '2028-01-05']]) {
    await user.clear(within(dialog).getByLabelText(label))
    await user.type(within(dialog).getByLabelText(label), value)
  }
  await user.click(within(dialog).getByRole('button', { name: 'Registrar' }))

  await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(await api.sent('POST /fixed-income')).toEqual([
    { name: 'LCA Banco Z', product: 'LCA', indexer: 'PRE', rate: '12.5', start: '2026-01-05', maturity: '2028-01-05', amount: '5000.00' },
  ])
})

test('without investments the card shows nothing', async () => {
  const api = fakeApi({ 'GET /fixed-income': { body: [] } })
  const { container } = renderWithApp(<FixedIncomeCard />)
  await vi.waitFor(() => expect(api.requests).toHaveLength(1))
  await vi.waitFor(() => expect(container).toBeEmptyDOMElement())
})

test('a partial redemption too large shows the value on that day', async () => {
  fakeApi({
    'GET /fixed-income': { body: [fixedIncome()] },
    'POST /fixed-income/1/partial-redemptions': {
      status: 422,
      body: { detail: { code: 'REDEMPTION_TOO_LARGE', message: 'x', date: '2026-06-01', available: '5200.50' } },
    },
  })
  renderWithApp(<FixedIncomeCard />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Resgatar ou apagar CDB Banco X' }))
  const dialog = screen.getByRole('dialog', { name: 'CDB Banco X · 110% do CDI' })
  await user.type(within(dialog).getByLabelText(/Valor resgatado/), '9.000')
  await user.click(within(dialog).getByRole('button', { name: 'Resgatar parte' }))

  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'Em 01/06/2026 a aplicação valia R$ 5.200,50: um resgate parcial precisa ser menor.',
  )
})

test('the dialog follows the refetched investment after a change', async () => {
  let redeemed = false
  const api = fakeApi({
    'GET /fixed-income': () => ({
      body: [fixedIncome(redeemed ? { status: 'REDEEMED', redeemed_on: '2026-11-10' } : {})],
    }),
    'PUT /fixed-income/1/redemption': () => {
      redeemed = true
      return { body: fixedIncome() }
    },
  })
  renderWithApp(<FixedIncomeCard />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Resgatar ou apagar CDB Banco X' }))
  const dialog = screen.getByRole('dialog')
  await user.clear(within(dialog).getByLabelText('Data do resgate'))
  await user.type(within(dialog).getByLabelText('Data do resgate'), '2026-11-10')
  await user.click(within(dialog).getByRole('button', { name: 'Resgatar tudo' }))

  expect(await within(dialog).findByRole('button', { name: 'Desfazer o resgate de 10/11/2026' })).toBeInTheDocument()
  expect(within(dialog).queryByRole('button', { name: 'Resgatar parte' })).not.toBeInTheDocument()
  expect(await api.sent('PUT /fixed-income/1/redemption')).toEqual([{ redeemed_on: '2026-11-10' }])
})

test('partial redemptions can be deleted from the dialog', async () => {
  const api = fakeApi({
    'GET /fixed-income': { body: [LCI] },
    'DELETE /fixed-income/2/partial-redemptions/9': { body: LCI },
  })
  renderWithApp(<FixedIncomeCard />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Resgatar ou apagar LCI Banco Y' }))
  await user.click(screen.getByRole('button', { name: 'Apagar resgate parcial de 01/06/2026' }))
  await vi.waitFor(() => expect(api.requests.some((r) => r.method === 'DELETE')).toBe(true))
})

test('deleting an investment asks first and closes the dialog', async () => {
  fakeApi({ 'GET /fixed-income': { body: [fixedIncome()] }, 'DELETE /fixed-income/1': { status: 204 } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  renderWithApp(<FixedIncomeCard />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Resgatar ou apagar CDB Banco X' }))
  await user.click(screen.getByRole('button', { name: 'Apagar aplicação' }))

  expect(confirm).toHaveBeenCalledWith('Apagar a aplicação CDB Banco X, com os resgates dela?')
  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  confirm.mockRestore()
})

test('while the CDI is syncing, totals are unknown and the list refetches by itself', async () => {
  let calls = 0
  fakeApi({
    'GET /fixed-income': () => {
      calls += 1
      return { body: [calls === 1 ? fixedIncome({ as_of: null, gross: null, iof: null, ir: null, net: null, gross_return: null }) : fixedIncome()] }
    },
  })
  renderWithApp(<FixedIncomeCard />)

  expect(await screen.findByText(/Aguardando o histórico do CDI/)).toBeInTheDocument()
  expect(metric('Valor bruto')).toHaveTextContent('—')
  expect(metric('Aplicado')).toHaveTextContent('R$ 5.000,00')

  await vi.waitFor(() => expect(metric('Valor bruto')).toHaveTextContent('R$ 5.400,10'), { timeout: 5000 })
  expect(screen.queryByText(/Aguardando o histórico do CDI/)).not.toBeInTheDocument()
})

test('an investment can be edited from its row', async () => {
  const api = fakeApi({
    'GET /fixed-income': { body: [fixedIncome()] },
    'PUT /fixed-income/1': { body: fixedIncome({ name: 'CDB Banco Y' }) },
  })
  renderWithApp(<FixedIncomeCard />)
  const user = userEvent.setup()

  await user.click(await screen.findByRole('button', { name: 'Editar CDB Banco X' }))
  const dialog = screen.getByRole('dialog', { name: 'Editar CDB Banco X' })
  expect(within(dialog).getByLabelText('Nome')).toHaveValue('CDB Banco X')
  await user.clear(within(dialog).getByLabelText('Nome'))
  await user.type(within(dialog).getByLabelText('Nome'), 'CDB Banco Y')
  await user.click(within(dialog).getByRole('button', { name: 'Salvar alterações' }))

  await vi.waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  const [sent] = await api.sent('PUT /fixed-income/1')
  expect(sent).toMatchObject({ name: 'CDB Banco Y', product: 'CDB', rate: '110', amount: '5000' })
})
