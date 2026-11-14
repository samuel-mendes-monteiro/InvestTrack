import { describe, expect, test } from 'vitest'
import { brDate, brl, parseDecimal, pct, perShare, quantity } from './format'

// Same cases as the Streamlit helpers' tests, so both frontends agree.
describe('brl', () => {
  test.each([
    ['1234.5', 'R$ 1.234,50'],
    ['0', 'R$ 0,00'],
    ['-123.8', 'R$ -123,80'],
    ['1234567.891', 'R$ 1.234.567,89'],
  ])('%s -> %s', (value, expected) => expect(brl(value)).toBe(expected))

  test('null is a dash', () => expect(brl(null)).toBe('—'))

  test('rounds half to even on the digits, never through a float', () => {
    expect(brl('0.125')).toBe('R$ 0,12')
    expect(brl('0.135')).toBe('R$ 0,14')
    expect(brl('0.1251')).toBe('R$ 0,13')
    expect(brl('-0.001')).toBe('R$ 0,00')
    expect(brl('999.995')).toBe('R$ 1.000,00')
  })
})

test('pct always shows the sign', () => {
  expect(pct('8.57')).toBe('+8,57%')
  expect(pct('-7.82')).toBe('-7,82%')
  expect(pct('0')).toBe('+0,00%')
  expect(pct(null)).toBe('—')
})

test('quantity drops trailing zeros', () => {
  expect(quantity('150')).toBe('150')
  expect(quantity('0.50000000')).toBe('0,5')
  expect(quantity('100.00')).toBe('100')
  expect(quantity('1500.25')).toBe('1.500,25')
})

test('perShare keeps up to 8 decimals', () => {
  expect(perShare('0.10245643978')).toBe('R$ 0,10245644')
  expect(perShare('1.5')).toBe('R$ 1,50')
  expect(perShare('2')).toBe('R$ 2,00')
})

test('brDate', () => expect(brDate('2026-01-05')).toBe('05/01/2026'))

describe('parseDecimal', () => {
  test.each([
    ['30,50', '30.50'],
    ['30.50', '30.50'],
    ['1.234,56', '1234.56'],
    ['R$ 30,50', '30.50'],
    [' 7 ', '7'],
  ])('%s -> %s', (text, expected) => expect(parseDecimal(text)).toBe(expected))

  test.each(['abc', '', '1,2,3', 'NaN'])('rejects %s', (text) =>
    expect(() => parseDecimal(text)).toThrow('não é um número válido'),
  )
})
