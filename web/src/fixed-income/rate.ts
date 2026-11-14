import type { FixedIncome } from '../api/queries'
import { quantity } from '../format'

/** "110% do CDI", "12,5% a.a." or "IPCA + 6,5% a.a." */
export function rateLabel(f: Pick<FixedIncome, 'rate' | 'indexer'>): string {
  const rate = quantity(f.rate)
  switch (f.indexer) {
    case 'CDI':
      return `${rate}% do CDI`
    case 'IPCA':
      return `IPCA + ${rate}% a.a.`
    case 'PRE':
      return `${rate}% a.a.`
  }
}
