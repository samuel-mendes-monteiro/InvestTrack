import { useQuery } from '@tanstack/react-query'
import { api, call } from './api/client'

// Placeholder screen until the login screen (step 3): proves the page reaches
// the API through the dev proxy.
export default function App() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => call(api.GET('/health')),
    retry: false,
  })

  return (
    <main>
      <h1>InvestTrack</h1>
      <p role="status">
        {health.isPending && 'Conectando à API…'}
        {health.isSuccess && 'API conectada.'}
        {health.isError && health.error.message}
      </p>
    </main>
  )
}
