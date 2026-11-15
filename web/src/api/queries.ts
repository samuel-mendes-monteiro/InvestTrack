import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

/** The logged-in account: e-mail and since when. */
export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => call(api.GET('/api/auth/me')) })
}

export function usePortfolio() {
  return useQuery({ queryKey: keys.portfolio, queryFn: () => call(api.GET('/api/portfolio')) })
}

export function useOperations() {
  return useQuery({ queryKey: keys.operations, queryFn: () => call(api.GET('/api/operations')) })
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
    mutationFn: (body: OperationInput) => call(api.POST('/api/operations', { body })),
    onSuccess: invalidate,
  })
}

export function useUpdateOperation() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: OperationInput }) =>
      call(api.PUT('/api/operations/{operation_id}', { params: { path: { operation_id: id } }, body })),
    onSuccess: invalidate,
  })
}

export function useDeleteOperation() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE('/api/operations/{operation_id}', { params: { path: { operation_id: id } } })),
    onSuccess: invalidate,
  })
}

export type Income = Schemas['IncomeOut']
export type IncomeInput = Schemas['IncomeCreate']

export function useIncomes() {
  return useQuery({ queryKey: ['income'], queryFn: () => call(api.GET('/api/income')) })
}

export function useMonthlyIncome(year: number | null) {
  return useQuery({
    queryKey: ['income', 'monthly', year],
    queryFn: () => call(api.GET('/api/income/monthly', { params: { query: { year: year! } } })),
    enabled: year != null, // waits until there is a year to ask for
  })
}

export function useCreateIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: IncomeInput) => call(api.POST('/api/income', { body })),
    onSuccess: invalidate,
  })
}

export function useDeleteIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => call(api.DELETE('/api/income/{income_id}', { params: { path: { income_id: id } } })),
    onSuccess: invalidate,
  })
}

export type StockEvent = Schemas['StockEventOut']

export function useStockEvents() {
  return useQuery({ queryKey: ['stock-events'], queryFn: () => call(api.GET('/api/stock-events')) })
}

const bonusPath = (e: StockEvent) => ({ params: { path: { ticker: e.ticker, record_date: e.record_date } } })

export function useSetBonusCost() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ event, unitCost }: { event: StockEvent; unitCost: string }) =>
      call(api.PUT('/api/stock-events/{ticker}/{record_date}/unit-cost', { ...bonusPath(event), body: { unit_cost: unitCost } })),
    onSuccess: invalidate,
  })
}

export function useDeleteBonusCost() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (event: StockEvent) => call(api.DELETE('/api/stock-events/{ticker}/{record_date}/unit-cost', bonusPath(event))),
    onSuccess: invalidate,
  })
}

export type FixedIncome = Schemas['FixedIncomeOut']
export type FixedIncomeInput = Schemas['FixedIncomeCreate']

const TICKER = /^[A-Z0-9]{4,12}$/

/**
 * Price of `ticker` on `day`, to suggest in a new operation: the current
 * quote for today, B3's close for an earlier day. Asks only for something
 * shaped like a ticker; a 404 (no price known) is an answer, not an error to retry.
 */
export function usePriceOn(ticker: string, day: string) {
  return useQuery({
    queryKey: ['price', ticker, day],
    queryFn: () =>
      call(api.GET('/api/prices/{ticker}', { params: { path: { ticker }, query: { date: day } } })),
    enabled: TICKER.test(ticker) && day !== '',
    retry: false,
    staleTime: 5 * 60_000,
  })
}

export function useFixedIncome() {
  return useQuery({
    queryKey: ['fixed-income'],
    queryFn: () => call(api.GET('/api/fixed-income')),
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
    mutationFn: (body: FixedIncomeInput) => call(api.POST('/api/fixed-income', { body })),
    onSuccess: invalidate,
  })
}

/** Redeem everything on a day, or undo the redemption with null. */
export function useRedeem() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, day }: { id: number; day: string | null }) =>
      call(api.PUT('/api/fixed-income/{investment_id}/redemption', { ...investment(id), body: { redeemed_on: day } })),
    onSuccess: invalidate,
  })
}

export function useDeleteFixedIncome() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (id: number) => call(api.DELETE('/api/fixed-income/{investment_id}', investment(id))),
    onSuccess: invalidate,
  })
}

export function useAddPartialRedemption() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, date, gross }: { id: number; date: string; gross: string }) =>
      call(api.POST('/api/fixed-income/{investment_id}/partial-redemptions', { ...investment(id), body: { date, gross } })),
    onSuccess: invalidate,
  })
}

export function useDeletePartialRedemption() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: ({ id, redemptionId }: { id: number; redemptionId: number }) =>
      call(
        api.DELETE('/api/fixed-income/{investment_id}/partial-redemptions/{redemption_id}', {
          params: { path: { investment_id: id, redemption_id: redemptionId } },
        }),
      ),
    onSuccess: invalidate,
  })
}

export type ImportResult = Schemas['ImportOut']

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

/**
 * The import endpoints take the .xlsx bytes as the whole request body, not a
 * multipart form. The schema types that body as a string (OpenAPI's
 * "binary"); the File goes through untouched, with the spreadsheet's type.
 */
function sendStatement(path: '/api/imports/b3/preview' | '/api/imports/b3', file: File) {
  return call(
    api.POST(path, {
      body: file as unknown as string,
      bodySerializer: (body) => body as unknown as BodyInit,
      headers: { 'Content-Type': XLSX },
    }),
  )
}

/** What importing would add. A mutation, not a query: the file is the input, and nothing is cached. */
export function usePreviewImport() {
  return useMutation({ mutationFn: (file: File) => sendStatement('/api/imports/b3/preview', file) })
}

export function useImport() {
  const invalidate = useInvalidateAll()
  return useMutation({ mutationFn: (file: File) => sendStatement('/api/imports/b3', file), onSuccess: invalidate })
}

export type Period = Schemas['Period']

export function usePerformance(period: Period) {
  return useQuery({
    queryKey: ['performance', period],
    queryFn: () => call(api.GET('/api/performance', { params: { query: { period } } })),
    // While another period loads, keep showing the current one instead of
    // flashing the loading text: the buttons stay put under the user's mouse.
    placeholderData: keepPreviousData,
    // The first time, the API downloads years of B3, Ibovespa and CDI history
    // in the background (~1 min). Poll while it says so, then stop.
    refetchInterval: (query) => (query.state.data?.syncing ? 5000 : false),
  })
}
