import { useQuery } from '@tanstack/react-query'
import { api } from './api/client'

// Placeholder screen for v1.0a step 1: proves the page reaches the API through
// the dev proxy. Login and the real screens replace it in the next steps.
export default function App() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const { data, error } = await api.GET('/health')
      if (error || !data) throw new Error('API unreachable')
      return data
    },
    retry: false,
  })

  return (
    <main>
      <h1>InvestTrack</h1>
      <p role="status">
        {health.isPending && 'Conectando à API…'}
        {health.isSuccess && 'API conectada.'}
        {health.isError && 'Não foi possível conectar à API. O uvicorn está rodando na porta 8000?'}
      </p>
    </main>
  )
}
