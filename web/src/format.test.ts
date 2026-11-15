import { describe, expect, test } from 'vitest'
import { brDate, brl, divideDecimal, isZero, multiplierToPercent, multiplyDecimals, parseDecimal, wholePct, pct, perShare, quantity, sumDecimals, todayIso } from './format'

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

test("reads Python's exponent notation, as the API sends some decimals", () => {
  expect(quantity('0E-8')).toBe('0')
  expect(quantity('1.5E+3')).toBe('1.500')
  expect(quantity('25E-3')).toBe('0,025')
  expect(brl('1E+2')).toBe('R$ 100,00')
  expect(isZero('0E-8')).toBe(true)
  expect(isZero('-0.00')).toBe(true)
  expect(isZero('1E-8')).toBe(false)
  expect(sumDecimals(['0.1', '0.2', '0E-8', '-1E-1'])).toBe('0.20000000') // keeps the scale, like Decimal
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

test('todayIso uses the local date, not UTC', () => {
  expect(todayIso(new Date(2026, 10, 14, 23, 30))).toBe('2026-11-14')
})

test.each(['1e3', '1E+3'])('people cannot type exponents (%s)', (text) =>
  expect(() => parseDecimal(text)).toThrow('não é um número válido'),
)

test('divideDecimal rounds the average exactly, half to even', () => {
  expect(divideDecimal('100.00', 3)).toBe('33.33')
  expect(divideDecimal('0.10', 4)).toBe('0.02') // 0.025 -> even
  expect(divideDecimal('0.30', 4)).toBe('0.08') // 0.075 -> even
  expect(divideDecimal('1.0000001', 1)).toBe('1.00')
  expect(divideDecimal('-10', 3)).toBe('-3.33')
})

test('multiplierToPercent', () => {
  expect(multiplierToPercent('1.1')).toBe('10')
  expect(multiplierToPercent('1.05')).toBe('5')
  expect(multiplierToPercent('1.0025')).toBe('0,25')
  expect(multiplierToPercent('2')).toBe('100')
})

test('wholePct rounds to a whole percentage', () => {
  expect(wholePct('112.6')).toBe('113%')
  expect(wholePct('112.5')).toBe('112%') // half to even
  expect(wholePct('1404.11')).toBe('1.404%')
  expect(wholePct(null)).toBe('—')
})

test('multiplies decimals exactly', () => {
  expect(multiplyDecimals('100', '30.50')).toBe('3050.00')
  expect(multiplyDecimals('0.1', '0.2')).toBe('0.02') // 0.020000000000000004 as Numbers
  expect(multiplyDecimals('50.00000000', '39.32')).toBe('1966.0000000000')
  expect(multiplyDecimals('-2', '1.5')).toBe('-3.0')
  expect(multiplyDecimals('0E-8', '42.27')).toBe('0.0000000000')
})
