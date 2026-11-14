// Brazilian formatting for the decimal strings the API sends ("1234.50").
//
// Money never becomes a JavaScript number here: Number is a binary float, so
// 0.1 + 0.2 !== 0.3. The API already did the math with Decimal; the frontend
// only rounds for display, which is done exactly on the digits with BigInt.

const DECIMAL = /^([+-])?(\d+)(?:\.(\d*))?$/

/** Round a decimal string to `places` digits, half-even like Python's Decimal. */
function round(value: string, places: number): { negative: boolean; digits: string } {
  const match = DECIMAL.exec(value.trim())
  if (!match) throw new Error(`not a decimal: ${value}`)
  const [, sign, whole, fraction = ''] = match
  const kept = fraction.slice(0, places).padEnd(places, '0')
  let n = BigInt(whole + kept)
  const rest = fraction.slice(places)
  if (rest !== '' && /[1-9]/.test(rest)) {
    const half = rest[0] === '5' && !/[1-9]/.test(rest.slice(1))
    if (rest[0] > '5' || (rest[0] === '5' && !half) || (half && n % 2n === 1n)) n += 1n
  }
  const digits = n.toString().padStart(places + 1, '0')
  return { negative: sign === '-' && n !== 0n, digits }
}

function groupThousands(whole: string): string {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

function toBr(value: string, places: number): string {
  const { negative, digits } = round(value, places)
  const whole = groupThousands(digits.slice(0, digits.length - places))
  const fraction = places ? ',' + digits.slice(-places) : ''
  return (negative ? '-' : '') + whole + fraction
}

/** "1234.5" -> "R$ 1.234,50". null -> "—". */
export function brl(value: string | null | undefined): string {
  return value == null ? '—' : 'R$ ' + toBr(value, 2)
}

/** "8.57" -> "+8,57%". null -> "—". */
export function pct(value: string | null | undefined): string {
  if (value == null) return '—'
  const text = toBr(value, 2)
  return (text.startsWith('-') ? text : '+' + text) + '%'
}

/** Drop trailing zeros: "0.50000000" -> "0,5", "100.00" -> "100". */
function trimmed(value: string): string {
  const [whole, fraction = ''] = value.split('.')
  const rest = fraction.replace(/0+$/, '')
  return rest ? `${whole}.${rest}` : whole
}

/** "150" -> "150", "1500.5" -> "1.500,5" (no trailing zeros). */
export function quantity(value: string): string {
  const [whole, fraction] = trimmed(value).split('.')
  const sign = whole.startsWith('-') ? '-' : ''
  return sign + groupThousands(whole.replace('-', '')) + (fraction ? ',' + fraction : '')
}

/** Per-share income: "0.10245643978" -> "R$ 0,10245644" (8 decimals at most, 2 at least). */
export function perShare(value: string | null | undefined): string {
  if (value == null) return '—'
  const { negative, digits } = round(value, 8)
  const whole = digits.slice(0, -8)
  const fraction = digits.slice(-8).replace(/0+$/, '').padEnd(2, '0')
  return `R$ ${negative ? '-' : ''}${groupThousands(whole)},${fraction}`
}

/** "2026-01-05" -> "05/01/2026" (no Date object: no time zone can shift the day). */
export function brDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-')
  return `${day}/${month}/${year}`
}

/**
 * Parse what a user types ("30,50", "30.50", "1.234,56", "R$ 30,50") into the
 * decimal string the API takes ("30.50"). Throws with a Portuguese message.
 */
export function parseDecimal(text: string): string {
  let s = text.trim().replace('R$', '').replace(/\s/g, '')
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.') // dots are thousands
  if (!DECIMAL.test(s)) throw new Error(`'${text}' não é um número válido`)
  return s.replace(/^\+/, '')
}
