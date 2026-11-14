import { screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { renderWithApp } from '../test/render'
import { performance } from '../test/samples'
import { PerformancePage } from './PerformancePage'

function metric(label: string) {
  return screen.getByText(label, { selector: '.metric-label' }).parentElement!
}

test('shows the TWR next to CDI and Ibovespa', async () => {
  fakeApi({ 'GET /performance': { body: performance() } })
  renderWithApp(<PerformancePage />)

  expect(await screen.findByText('Carteira', { selector: '.metric-label' })).toBeInTheDocument()
  expect(metric('Carteira')).toHaveTextContent('+48,82%')
  expect(metric('CDI')).toHaveTextContent('+12,08%')
  expect(metric('Ibovespa')).toHaveTextContent('+7,42%')
  expect(metric('% do CDI')).toHaveTextContent('404%')
  expect(screen.getByText(/De 05\/01\/2026 a 13\/11\/2026/)).toBeInTheDocument()
})

test('while history downloads it says so and refetches by itself', async () => {
  let calls = 0
  fakeApi({
    'GET /performance': () => {
      calls += 1
      return { body: calls === 1 ? performance({ syncing: true, points: [], twr: null, cdi: null, ibovespa: null, pct_of_cdi: null, start: null, as_of: null }) : performance() }
    },
  })
  renderWithApp(<PerformancePage />)

  expect(await screen.findByRole('status')).toHaveTextContent('Baixando o histórico')
  expect(screen.queryByText(/Registre uma compra/)).not.toBeInTheDocument()
  await vi.waitFor(() => expect(metric('Carteira')).toHaveTextContent('+48,82%'), { timeout: 8000 })
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
}, 10000)

test('without trades it says how to start', async () => {
  fakeApi({ 'GET /performance': { body: performance({ points: [], twr: null, start: null, as_of: null }) } })
  renderWithApp(<PerformancePage />)
  expect(await screen.findByText('Registre uma compra para ver a rentabilidade.')).toBeInTheDocument()
})
