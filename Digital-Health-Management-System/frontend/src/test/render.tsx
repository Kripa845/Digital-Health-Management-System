import type { ReactElement } from 'react'
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '@/lib/auth'

/** Render a page at `path` with the providers the app uses. `routes` adds other pages to navigate to. */
export function renderPage(
  ui: ReactElement,
  { path = '/', route = path, routes = {} }: { path?: string; route?: string; routes?: Record<string, ReactElement> } = {},
) {
  localStorage.setItem('access_token', 'test-token')
  localStorage.setItem('user_role', 'PATIENT')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
            {Object.entries(routes).map(([p, el]) => <Route key={p} path={p} element={el} />)}
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}
