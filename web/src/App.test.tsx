import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import App from './App'

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

test('shows the API as connected when /api/health answers', async () => {
  const fetch = vi.fn(async () => Response.json({ status: 'ok' }))
  vi.stubGlobal('fetch', fetch)
  renderApp()
  expect(await screen.findByText('API conectada.')).toBeInTheDocument()
  const request = fetch.mock.calls[0] as unknown as [Request]
  expect(new URL(request[0].url).pathname).toBe('/api/health')
})

test('explains what to check when the API is down', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 502 })))
  renderApp()
  expect(await screen.findByText(/Ela está rodando/)).toBeInTheDocument()
})
