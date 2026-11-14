import type { components } from './api/schema'

type Schemas = components['schemas']

// Record<Enum, string> makes the compiler demand a label for every value the
// API can send: a new enum member in Python breaks the build until it's named here.

export const OP_TYPES: Record<Schemas['OpType'], string> = { BUY: 'Compra', SELL: 'Venda' }

export const ASSET_TYPES: Record<Schemas['AssetType'], string> = {
  STOCK: 'Ação',
  FII: 'FII',
  ETF: 'ETF',
  BDR: 'BDR',
}

export const INCOME_TYPES: Record<Schemas['IncomeType'], string> = {
  DIVIDEND: 'Dividendo',
  JCP: 'JCP',
  DISTRIBUTION: 'Rendimento (FII)',
}

export const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']

export const STOCK_EVENT_TYPES: Record<Schemas['StockEventType'], string> = {
  SPLIT: 'Desdobramento',
  REVERSE_SPLIT: 'Grupamento',
  BONUS: 'Bonificação',
}

export const FI_PRODUCTS: Schemas['Product'][] = ['CDB', 'LCI', 'LCA']

export const FI_INDEXERS: Record<Schemas['Indexer'], string> = { CDI: '% do CDI', PRE: 'Prefixado', IPCA: 'IPCA+' }

export const FI_STATUS: Record<Schemas['FixedIncomeOut']['status'], string> = { ACTIVE: 'Aplicado', REDEEMED: 'Resgatado', MATURED: 'Vencido' }

export const IMPORT_STATUS: Record<Schemas['ImportRowOut']['status'], string> = {
  NEW: 'Nova',
  DUPLICATE: 'Já registrada',
  REJECTED: 'Recusada',
  IMPORTED: 'Importada',
}

export const SKIP_REASONS: Record<Schemas['SkippedRowOut']['reason'], string> = {
  UNSUPPORTED_MARKET: 'mercado não suportado (opções, termo, futuro...)',
  UNKNOWN_TYPE: 'não é compra nem venda',
  UNREADABLE_ROW: 'linha ilegível',
}

// In button order, shortest first.
export const PERIODS: { value: Schemas['Period']; label: string; name: string }[] = [
  { value: '1M', label: '1M', name: 'Último mês' },
  { value: '6M', label: '6M', name: 'Últimos 6 meses' },
  { value: '1Y', label: '1A', name: 'Último ano' },
  { value: 'ALL', label: 'Total', name: 'Desde a primeira operação' },
]
