import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import './index.css'
import App from './App.tsx'

// Before v1.0 the session token was kept in localStorage; it is now an
// HttpOnly cookie, so drop the old copy instead of leaving it lying around.
try {
  localStorage.removeItem('investtrack.token')
} catch {
  // storage blocked: nothing was saved there either
}

// One cache for everything the server owns (portfolio, income, ...). Screens
// read through it instead of keeping their own copies in React state.
const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
