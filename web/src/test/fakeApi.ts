import { vi } from 'vitest'

type Reply = { status?: number; body?: unknown }
type Handler = (request: Request) => Reply | Promise<Reply>

/**
 * Replace fetch with a tiny fake API: routes like 'POST /auth/login' (without
 * the /api prefix) answer with a status and JSON body. Unknown routes are a
 * 404, and every request is recorded so tests can check what was sent.
 */
export function fakeApi(routes: Record<string, Reply | Handler>) {
  const requests: Request[] = []
  const fetch = vi.fn(async (request: Request) => {
    requests.push(request.clone())
    const path = new URL(request.url).pathname.replace(/^\/api/, '')
    const route = routes[`${request.method} ${path}`]
    const reply = typeof route === 'function' ? await route(request) : (route ?? { status: 404 })
    const status = reply.status ?? 200
    return reply.body === undefined ? new Response(null, { status }) : Response.json(reply.body, { status })
  })
  vi.stubGlobal('fetch', fetch)
  return {
    requests,
    /** The JSON bodies sent to one route, in order. */
    sent: async (route: string) => {
      const [method, path] = route.split(' ')
      const matching = requests.filter((r) => r.method === method && new URL(r.url).pathname === `/api${path}`)
      return Promise.all(matching.map((r) => r.json()))
    },
  }
}
