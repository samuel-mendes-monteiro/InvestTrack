import { brDate, brl, quantity } from '../format'
import type { components } from './schema'

type ErrorDetail = components['schemas']['ErrorDetail']
type ValidationError = components['schemas']['ValidationError']

/** A failed call, with one sentence in Portuguese for the user. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(message: string, status: number, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const FIELD_NAMES: Record<string, string> = {
  ticker: 'Ticker',
  op_type: 'Tipo',
  date: 'Data',
  quantity: 'Quantidade',
  price: 'Preço',
  fees: 'Taxas',
  asset_type: 'Classe do ativo',
  income_type: 'Tipo de provento',
  amount: 'Valor bruto',
  tax: 'IR retido',
  unit_cost: 'Custo atribuído',
  name: 'Nome',
  product: 'Produto',
  indexer: 'Indexador',
  rate: 'Taxa',
  start: 'Data da aplicação',
  maturity: 'Vencimento',
  redeemed_on: 'Data do resgate',
  gross: 'Valor do resgate',
  email: 'E-mail',
  password: 'Senha',
  new_password: 'Nova senha',
}

// The fixed-income module's validation messages, which come without their own code.
const FIXED_INCOME_MESSAGES: Record<string, string> = {
  'maturity must be after the start date': 'O vencimento deve ser depois da aplicação.',
  'redemption must be between the start and the maturity':
    'A data do resgate deve estar entre a aplicação e o vencimento.',
  'a partial redemption must be after the start and before the end':
    'O resgate parcial deve ser depois da aplicação e antes do resgate total ou do vencimento.',
}

const qty = (value: string | null | undefined) => quantity(value ?? '0')
const day = (value: string | null | undefined) => (value ? brDate(value) : '?')

/** Our API's errors, translated from their stable code (the English message is a fallback). */
export function domainMessage(d: ErrorDetail): string {
  switch (d.code) {
    case 'INSUFFICIENT_POSITION':
      return `Você tem ${qty(d.available)} ${d.ticker} nessa data e tentou vender ${qty(d.requested)}.`
    case 'DELETE_BREAKS_LATER_SALE':
      return `Apagar essa operação deixaria uma venda posterior de ${d.ticker} sem ações suficientes. Apague a venda primeiro.`
    case 'EDIT_BREAKS_HISTORY':
      return `Com essa alteração, uma venda de ${d.ticker} ficaria sem ações: haveria ${qty(d.available)} e a venda é de ${qty(d.requested)}.`
    case 'EDIT_ORPHANS_INCOME':
      return `Com essa alteração, proventos de ${d.ticker} ficariam antes da primeira compra. Confira a data.`
    case 'OPERATION_NOT_FOUND':
      return 'Operação não encontrada. Talvez ela já tenha sido apagada.'
    case 'INCOME_WITHOUT_POSITION':
      return d.first_buy
        ? `A primeira compra de ${d.ticker} foi em ${day(d.first_buy)}, então não pode haver provento em ${day(d.income_date)}.`
        : `Não há compra de ${d.ticker} registrada. Confira o ticker.`
    case 'DELETE_ORPHANS_INCOME':
      return `Apagar essa compra deixaria proventos de ${d.ticker} recebidos antes de qualquer compra. Apague os proventos primeiro.`
    case 'INVALID_CREDENTIALS':
      return 'E-mail ou senha incorretos.'
    case 'TOO_MANY_ATTEMPTS': {
      const minutes = Math.max(1, Math.ceil((d.retry_after ?? 60) / 60))
      return `Muitas tentativas de login erradas. Tente de novo em ${minutes} minuto${minutes > 1 ? 's' : ''}.`
    }
    case 'TOO_MANY_RESET_REQUESTS': {
      const minutes = Math.max(1, Math.ceil((d.retry_after ?? 60) / 60))
      return `Muitos pedidos de redefinição de senha. Tente de novo em ${minutes} minuto${minutes > 1 ? 's' : ''}.`
    }
    case 'INVALID_RESET_TOKEN':
      return 'Esse link não vale mais: ele expira em 30 minutos e funciona uma vez só. Peça um novo.'
    case 'EMAIL_TAKEN':
      return 'Já existe uma conta com esse e-mail.'
    case 'WRONG_PASSWORD':
      return 'A senha atual está incorreta.'
    case 'WEAK_PASSWORD':
      return 'A senha precisa ter pelo menos 8 caracteres.'
    case 'INVALID_EMAIL':
      return 'E-mail inválido.'
    case 'NOT_AUTHENTICATED':
      return 'Sua sessão expirou. Entre de novo.'
    case 'INVALID_STATEMENT':
      return d.message.includes('columns')
        ? 'Esse arquivo não parece ser o extrato de Negociação da B3. Na Área do Investidor, use Extratos → Negociação e exporte em Excel.'
        : 'O arquivo não é uma planilha Excel (.xlsx).'
    case 'FILE_TOO_LARGE':
      return 'Arquivo grande demais (máximo de 5 MB).'
    case 'INVALID_FIXED_INCOME':
    case 'INVALID_PARTIAL_REDEMPTION':
      return FIXED_INCOME_MESSAGES[d.message] ?? d.message
    case 'REDEMPTION_TOO_LARGE':
      return `Em ${day(d.date)} a aplicação valia ${brl(d.available)}: um resgate parcial precisa ser menor. Para tirar tudo, use o resgate total.`
    case 'VALUE_NOT_KNOWN':
      return 'Não há valor para essa data: não é dia útil, ou o CDI dela ainda não foi publicado.'
    case 'PARTIAL_REDEMPTION_NOT_FOUND':
      return 'Resgate parcial não encontrado. Talvez ele já tenha sido apagado.'
    case 'FIXED_INCOME_NOT_FOUND':
      return 'Aplicação não encontrada. Talvez ela já tenha sido apagada.'
    case 'STOCK_EVENT_NOT_FOUND':
      return 'Não há bonificação desse ativo nessa data.'
    case 'INCOME_NOT_FOUND':
      return 'Provento não encontrado. Talvez ele já tenha sido apagado.'
    default:
      return d.message || 'Erro desconhecido da API.'
  }
}

/** One Pydantic validation error (e.g. price < 0), in Portuguese. */
export function validationMessage(err: ValidationError): string {
  const last = err.loc.at(-1)
  const field = last === undefined ? 'Campo' : (FIELD_NAMES[String(last)] ?? String(last))
  const ctx = (err.ctx ?? {}) as Record<string, unknown>
  const messages: Record<string, string> = {
    greater_than: `deve ser maior que ${ctx.gt}`,
    greater_than_equal: 'não pode ser negativo',
    string_too_short: 'não pode ficar vazio',
    string_too_long: `pode ter no máximo ${ctx.max_length} caracteres`,
    decimal_parsing: 'não é um número válido',
    enum: 'valor inválido',
    missing: 'é obrigatório',
  }
  if (err.type in messages) return `${field} ${messages[err.type]}`
  if (err.msg.includes('future')) return 'A data não pode estar no futuro'
  if (err.msg.includes('larger than the amount')) return 'O IR retido não pode ser maior que o valor bruto'
  return `${field}: ${err.msg || 'inválido'}`
}

/**
 * Turn an error body into an ApiError. Our own errors look like
 * {"detail": {"code": ...}}; Pydantic's like {"detail": [{"loc": ..., "type": ...}]}.
 */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (Array.isArray(detail)) {
    const text = (detail as ValidationError[]).map(validationMessage).join('; ')
    return new ApiError(text + '.', status, 'VALIDATION')
  }
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const d = detail as ErrorDetail
    return new ApiError(domainMessage(d), status, d.code)
  }
  if (typeof detail === 'string') return new ApiError(detail, status)
  return new ApiError(`Erro ${status} da API.`, status)
}
