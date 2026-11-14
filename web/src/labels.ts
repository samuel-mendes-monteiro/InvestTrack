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
