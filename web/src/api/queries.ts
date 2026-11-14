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
