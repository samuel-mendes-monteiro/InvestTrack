import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { ImportResult } from '../api/queries'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { ImportDialog } from './ImportDialog'

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const row = { date: '2026-03-10', op_type: 'BUY' as const, ticker: 'PETR4', quantity: '100', price: '30.50', error: null }

const PREVIEW: ImportResult = {
  imported: false,
  new: 2,
  duplicates: 1,
  rejected: 1,
  skipped: 1,
  rows: [
    { ...row, line: 2, status: 'NEW' },
    { ...row, line: 3, status: 'DUPLICATE' },
    { ...row, line: 4, status: 'NEW', ticker: 'VALE3' },
    {
      ...row,
      line: 5,
      status: 'REJECTED',
      op_type: 'SELL',
      ticker: 'ITSA4',
      error: { code: 'INSUFFICIENT_POSITION', message: 'x', ticker: 'ITSA4', available: '0', requested: '100' },
    },
  ],
  skipped_rows: [{ line: 6, reason: 'UNSUPPORTED_MARKET', detail: 'Opção de Compra' }],
}

const IMPORTED: ImportResult = {
  ...PREVIEW,
  imported: true,
  rows: PREVIEW.rows.map((r) => (r.status === 'NEW' ? { ...r, status: 'IMPORTED' } : r)),
}

function statement(name = 'negociacao.xlsx') {
  return new File([new Uint8Array([0x50, 0x4b, 3, 4])], name, { type: XLSX })
}

test('previews the file, then imports only when asked', async () => {
  const api = fakeApi({ 'POST /imports/b3/preview': { body: PREVIEW }, 'POST /imports/b3': { body: IMPORTED } })
  renderWithApp(<ImportDialog onClose={() => {}} />)
  const user = userEvent.setup()

  await user.upload(screen.getByLabelText('Extrato de Negociação (.xlsx)'), statement())

  const table = await screen.findByRole('table', { name: 'Linhas do extrato' })
  expect(within(table).getByRole('row', { name: /ITSA4/ })).toHaveTextContent(
    '5Recusada10/03/2026VendaITSA4100R$ 30,50Você tem 0 ITSA4 nessa data e tentou vender 100.',
  )
  expect(screen.getByText(/Linha 6 ignorada: mercado não suportado/)).toBeInTheDocument()
  expect(screen.getByText(/As linhas recusadas venderiam mais/)).toBeInTheDocument()
  expect(api.requests.map((r) => new URL(r.url).pathname)).toEqual(['/api/imports/b3/preview'])

  await user.click(screen.getByRole('button', { name: 'Importar 2 operações' }))

  expect(await screen.findByRole('status')).toHaveTextContent('2 operações importadas.')
  expect(within(table).getAllByText('Importada')).toHaveLength(2)
  expect(screen.queryByRole('button', { name: /^Importar/ })).not.toBeInTheDocument()
})

test('the raw spreadsheet is the request body', async () => {
  const api = fakeApi({ 'POST /imports/b3/preview': { body: PREVIEW } })
  renderWithApp(<ImportDialog onClose={() => {}} />)

  await userEvent.upload(screen.getByLabelText('Extrato de Negociação (.xlsx)'), statement())
  await screen.findByRole('table')

  const sent = api.requests[0]
  expect(sent.headers.get('Content-Type')).toBe(XLSX)
  expect(new Uint8Array(await sent.arrayBuffer())).toEqual(new Uint8Array([0x50, 0x4b, 3, 4]))
})

test('nothing new means nothing to import', async () => {
  fakeApi({ 'POST /imports/b3/preview': { body: { ...PREVIEW, new: 0, rows: [{ ...row, line: 2, status: 'DUPLICATE' }] } } })
  renderWithApp(<ImportDialog onClose={() => {}} />)

  await userEvent.upload(screen.getByLabelText('Extrato de Negociação (.xlsx)'), statement())
  await screen.findByRole('table')
  expect(screen.getByRole('button', { name: 'Importar 0 operações' })).toBeDisabled()
})

test('a file that is not the statement is explained', async () => {
  fakeApi({
    'POST /imports/b3/preview': {
      status: 422,
      body: { detail: { code: 'INVALID_STATEMENT', message: 'missing columns: Ticker' } },
    },
  })
  renderWithApp(<ImportDialog onClose={() => {}} />)

  await userEvent.upload(screen.getByLabelText('Extrato de Negociação (.xlsx)'), statement('outra.xlsx'))
  expect(await screen.findByRole('alert')).toHaveTextContent('não parece ser o extrato de Negociação da B3')
})

test('an empty operations page offers the import first', async () => {
  fakeApi({ 'GET /operations': { body: [] }, 'GET /stock-events': { body: [] } })
  const { OperationsPage } = await import('./OperationsPage')
  renderWithApp(<OperationsPage />)

  await userEvent.click(await screen.findByRole('button', { name: 'Importar extrato da B3' }))
  expect(screen.getByRole('dialog', { name: 'Importar extrato da B3' })).toBeInTheDocument()
  vi.restoreAllMocks()
})
