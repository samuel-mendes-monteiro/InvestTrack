import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, call } from './client'
import type { components } from './schema'

export type Schemas = components['schemas']
export type Operation = Schemas['OperationOut']
export type OperationInput = Schemas['OperationCreate']

// Query keys name what the server owns. Pages share them: the portfolio
// fetched by one screen is reused from the cache by the next.
export const keys = {
  me: ['me'],
  portfolio: ['portfolio'],
  operations: ['operations'],
} as const

export function usePortfolio() {
  return useQuery({ queryKey: keys.portfolio, queryFn: () => call(api.GET('/portfolio')) })
}

export function useOperations() {
  return useQuery({ queryKey: keys.operations, queryFn: () => call(api.GET('/operations')) })
}

/**
 * After any change to operations, refetch everything. One trade moves
 * positions, totals, computed income (shares held on the record date), stock
 * events and the TWR, and the API is the one that knows how: guessing which
 * caches to patch here would copy its rules into the frontend.
 */
function useInvalidateAll() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries()
}

export function useCreateOperation() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: OperationInput) => call(api.POST('/operations', { body })),
    onSuccess: invalidate,
  })
}

export function useUpdateOperation() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: OperationInput }) =>
      call(api.PUT('/operations/{operation_id}', { params: { path: { operation_id: id } }, body })),
    onSuccess: invalidate,
  })
}

export function useDeleteOperation() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE('/operations/{operation_id}', { params: { path: { operation_id: id } } })),
    onSuccess: invalidate,
  })
}

export type Income = Schemas['IncomeOut']
export type IncomeInput = Schemas['IncomeCreate']

export function useIncomes() {
  return useQuery({ queryKey: ['income'], queryFn: () => call(api.GET('/income')) })
}

export function useMonthlyIncome(year: number | null) {
  return useQuery({
    queryKey: ['income', 'monthly', year],
    queryFn: () => call(api.GET('/income/monthly', { params: { query: { year: year! } } })),
    enabled: year != null, // waits until there is a year to ask for
  })
}

export function useCreateIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: IncomeInput) => call(api.POST('/income', { body })),
    onSuccess: invalidate,
  })
}

export function useDeleteIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => call(api.DELETE('/income/{income_id}', { params: { path: { income_id: id } } })),
    onSuccess: invalidate,
  })
}

export type StockEvent = Schemas['StockEventOut']

export function useStockEvents() {
  return useQuery({ queryKey: ['stock-events'], queryFn: () => call(api.GET('/stock-events')) })
}

const bonusPath = (e: StockEvent) => ({ params: { path: { ticker: e.ticker, record_date: e.record_date } } })

export function useSetBonusCost() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ event, unitCost }: { event: StockEvent; unitCost: string }) =>
      call(api.PUT('/stock-events/{ticker}/{record_date}/unit-cost', { ...bonusPath(event), body: { unit_cost: unitCost } })),
    onSuccess: invalidate,
  })
}

export function useDeleteBonusCost() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (event: StockEvent) => call(api.DELETE('/stock-events/{ticker}/{record_date}/unit-cost', bonusPath(event))),
    onSuccess: invalidate,
  })
}

export type FixedIncome = Schemas['FixedIncomeOut']
export type FixedIncomeInput = Schemas['FixedIncomeCreate']

export function useFixedIncome() {
  return useQuery({
    queryKey: ['fixed-income'],
    queryFn: () => call(api.GET('/fixed-income')),
    // The API syncs the CDI in the background; until it lands, values are
    // unknown (as_of null). Ask again every few seconds instead of telling the
    // user to reload, and stop as soon as everything has a value.
    refetchInterval: (query) => (query.state.data?.some((f) => f.as_of == null) ? 3000 : false),
  })
}

const investment = (id: number) => ({ params: { path: { investment_id: id } } })

export function useCreateFixedIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: FixedIncomeInput) => call(api.POST('/fixed-income', { body })),
    onSuccess: invalidate,
  })
}

/** Redeem everything on a day, or undo the redemption with null. */
export function useRedeem() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, day }: { id: number; day: string | null }) =>
      call(api.PUT('/fixed-income/{investment_id}/redemption', { ...investment(id), body: { redeemed_on: day } })),
    onSuccess: invalidate,
  })
}

export function useDeleteFixedIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => call(api.DELETE('/fixed-income/{investment_id}', investment(id))),
    onSuccess: invalidate,
  })
}

export function useAddPartialRedemption() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, date, gross }: { id: number; date: string; gross: string }) =>
      call(api.POST('/fixed-income/{investment_id}/partial-redemptions', { ...investment(id), body: { date, gross } })),
    onSuccess: invalidate,
  })
}

export function useDeletePartialRedemption() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, redemptionId }: { id: number; redemptionId: number }) =>
      call(
        api.DELETE('/fixed-income/{investment_id}/partial-redemptions/{redemption_id}', {
          params: { path: { investment_id: id, redemption_id: redemptionId } },
        }),
      ),
    onSuccess: invalidate,
  })
}
