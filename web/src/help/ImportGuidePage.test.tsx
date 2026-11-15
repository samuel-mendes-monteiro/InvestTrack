import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { renderWithApp } from '../test/render'
import { ImportGuidePage } from './ImportGuidePage'

test('walks through the export, step by step, and imports from the page', async () => {
  renderWithApp(<ImportGuidePage />)

  expect(screen.getByRole('heading', { level: 1, name: 'Como importar seu histórico da B3' })).toBeInTheDocument()
  const steps = screen.getAllByRole('listitem').filter((li) => li.querySelector('.step-number'))
  expect(steps.map((s) => s.querySelector('h2')!.textContent)).toEqual([
    'Entre na Área do Investidor da B3',
    'Abra Extratos → Negociação',
    'Escolha o período desde a sua primeira compra',
    'Baixe o extrato em Excel',
    'Importe no InvestTrack',
  ])

  await userEvent.click(screen.getByRole('button', { name: 'Importar extrato agora' }))
  expect(screen.getByRole('dialog', { name: 'Importar extrato da B3' })).toBeInTheDocument()
})
