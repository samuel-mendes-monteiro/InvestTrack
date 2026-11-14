// Brazilian formatting for the decimal strings the API sends ("1234.50").
//
// Money never becomes a JavaScript number here: Number is a binary float, so
// 0.1 + 0.2 !== 0.3. The API already did the math with Decimal; the frontend
// only rounds for display, which is done exactly on the digits with BigInt.

// What a person types: no exponent.
const DECIMAL = /^([+-])?(\d+)(?:\.(\d*))?$/
// What the API sends: Python's str(Decimal) uses an exponent for some values,
// e.g. a closed position's quantity, 100.00000000 - 100.00000000, is "0E-8".
const API_DECIMAL = /^([+-])?(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/

type Parts = { negative: boolean; whole: string; fraction: string }

/** "1.5E+3" -> 1500, "0E-8" -> 0: sign plus plain digits, the exponent applied. */
function parts(value: string): Parts {
  const match = API_DECIMAL.exec(value.trim())
  if (!match) throw new Error(`not a decimal: ${value}`)
  const [, sign, intDigits, fracDigits = '', exp = '0'] = match
  const digits = intDigits + fracDigits
  const point = intDigits.length + Number(exp) // where the decimal point lands
  const padded = point <= 0 ? '0'.repeat(1 - point) + digits : digits.padEnd(point, '0')
  const at = point <= 0 ? 1 : point
  return {
    negative: sign === '-',
    whole: padded.slice(0, at).replace(/^0+(?=\d)/, ''),
    fraction: padded.slice(at),
  }
}

/** Round a decimal string to `places` digits, half-even like Python's Decimal. */
function round(value: string, places: number): { negative: boolean; digits: string } {
  const { negative: minus, whole, fraction } = parts(value)
  const kept = fraction.slice(0, places).padEnd(places, '0')
  let n = BigInt(whole + kept)
  const rest = fraction.slice(places)
  if (rest !== '' && /[1-9]/.test(rest)) {
    const half = rest[0] === '5' && !/[1-9]/.test(rest.slice(1))
    if (rest[0] > '5' || (rest[0] === '5' && !half) || (half && n % 2n === 1n)) n += 1n
  }
  const digits = n.toString().padStart(places + 1, '0')
  return { negative: minus && n !== 0n, digits }
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

/** "150" -> "150", "1500.5" -> "1.500,5", "0E-8" -> "0" (no trailing zeros). */
export function quantity(value: string): string {
  const { negative, whole, fraction } = parts(value)
  const rest = fraction.replace(/0+$/, '')
  const sign = negative && /[1-9]/.test(whole + rest) ? '-' : ''
  return sign + groupThousands(whole) + (rest ? ',' + rest : '')
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

/**
 * Today's date in the user's time zone, as "YYYY-MM-DD". Not
 * toISOString(): that is UTC, so in Brazil after 21h it is already tomorrow.
 */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** "2026-11-14T13:44:43Z" -> "14/11 10:44" in the viewer's time zone. */
export function localTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** True for "0", "0.00", "0E-8": the API's numbers are strings, so `!== 0` doesn't work. */
export function isZero(value: string): boolean {
  const { whole, fraction } = parts(value)
  return !/[1-9]/.test(whole + fraction)
}

/** Exact sum of decimal strings ("0.1" + "0.2" is "0.3" here, unlike Number). */
export function sumDecimals(values: string[]): string {
  const parsed = values.map((v) => {
    const { negative, whole, fraction } = parts(v)
    return { sign: negative ? -1n : 1n, whole, fraction }
  })
  const scale = Math.max(0, ...parsed.map((p) => p.fraction.length))
  const total = parsed.reduce((sum, p) => sum + p.sign * BigInt(p.whole + p.fraction.padEnd(scale, '0')), 0n)
  const digits = (total < 0n ? -total : total).toString().padStart(scale + 1, '0')
  const whole = digits.slice(0, digits.length - scale)
  return (total < 0n ? '-' : '') + whole + (scale ? '.' + digits.slice(-scale) : '')
}

/** 'positive' / 'negative' for a decimal string, for coloring gains and losses. */
export function toneOf(value: string | null | undefined): 'positive' | 'negative' | undefined {
  if (value == null || isZero(value)) return undefined
  return value.startsWith('-') ? 'negative' : 'positive'
}

/** value / divisor rounded half-even to 2 places, exactly: an average in reais. */
export function divideDecimal(value: string, divisor: number): string {
  if (!Number.isInteger(divisor) || divisor <= 0) throw new Error(`bad divisor: ${divisor}`)
  const { negative, whole, fraction } = parts(value)
  const scale = fraction.length
  const numerator = BigInt(whole + fraction) * 100n // result in cents, before / 10^scale
  const denominator = BigInt(divisor) * 10n ** BigInt(scale)
  let cents = numerator / denominator
  const twice = (numerator % denominator) * 2n
  if (twice > denominator || (twice === denominator && cents % 2n === 1n)) cents += 1n
  const digits = cents.toString().padStart(3, '0')
  const sign = negative && cents !== 0n ? '-' : ''
  return `${sign}${digits.slice(0, -2)}.${digits.slice(-2)}`
}

/** Parse one number field, naming it in the error. */
export function decimalField(label: string, text: string, fallback?: string): string {
  if (!text.trim()) {
    if (fallback !== undefined) return fallback
    throw new Error(`Preencha o campo ${label}.`)
  }
  try {
    return parseDecimal(text)
  } catch {
    throw new Error(`${label}: '${text}' não é um número válido.`)
  }
}

/** "1.1" -> "10": a bonus multiplier as the percentage of new shares, exactly. */
export function multiplierToPercent(multiplier: string): string {
  // "E+2" moves the decimal point two places: x100 with no arithmetic at all.
  return quantity(`${sumDecimals([multiplier, '-1'])}E+2`)
}
