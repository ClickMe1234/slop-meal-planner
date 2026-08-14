import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { LoginPage } from './AuthPages'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    isDemoMode: false,
    api: {
      ...actual.api,
      me: vi.fn(),
      setupStatus: vi.fn(),
      login: vi.fn(),
    },
  }
})

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="current-route">{location.pathname}</output>
}

function renderLogin(queryClient = new QueryClient()) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/week" element={<h1>Week</h1>} />
          <Route path="/change-password" element={<h1>Change password</h1>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const signedInUser = {
  id: 'user-1',
  username: 'owner',
  role: 'owner' as const,
  member_id: 'member-1',
  must_change_password: false,
  ingredient_locale: 'uk' as const,
  method_view_preference: 'summary' as const,
  measurement_system: 'metric' as const,
  method_tutorial_version_seen: 0,
}

beforeEach(() => {
  vi.mocked(api.setupStatus).mockResolvedValue({ setup_required: false })
  vi.mocked(api.me).mockRejectedValue(new Error('not signed in'))
  vi.mocked(api.login).mockResolvedValue({ user: signedInUser, csrf_token: 'csrf-token' })
})

describe('LoginPage', () => {
  it('opens an existing remembered session instead of showing the login form', async () => {
    vi.mocked(api.me).mockResolvedValue(signedInUser)

    renderLogin()

    await waitFor(() => expect(screen.getByTestId('current-route')).toHaveTextContent('/week'))
    expect(screen.queryByRole('heading', { name: /sign in to your household/i })).not.toBeInTheDocument()
  })
  it('does not trust cached session data when revalidation fails', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['session'], signedInUser)
    vi.mocked(api.me).mockRejectedValue(new Error('session revoked'))

    renderLogin(queryClient)

    await screen.findByRole('heading', { name: /sign in to your household/i })
    expect(screen.getByTestId('current-route')).toHaveTextContent('/login')
  })

  it('passes an unchecked keep-signed-in choice to login', async () => {
    const user = userEvent.setup()
    renderLogin()

    await screen.findByRole('heading', { name: /sign in to your household/i })
    await user.type(screen.getByRole('textbox', { name: 'Username' }), 'owner')
    await user.type(screen.getByLabelText('Password'), 'password')
    await user.click(screen.getByRole('checkbox', { name: 'Keep me signed in' }))
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => expect(api.login).toHaveBeenCalledWith('owner', 'password', false))
  })
})
