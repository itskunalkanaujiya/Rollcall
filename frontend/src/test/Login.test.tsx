import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError } from 'axios'
import { MemoryRouter } from 'react-router-dom'
import Login from '../pages/Login'
import { AuthProvider } from '../hooks/useAuth'
import * as svc from '../services/endpoints'

vi.mock('../services/endpoints', () => ({ auth: { me: vi.fn(), login: vi.fn(), logout: vi.fn() } }))
const auth = svc.auth as unknown as { me: ReturnType<typeof vi.fn>; login: ReturnType<typeof vi.fn> }

const apiError = (status: number, code: string, message: string) =>
  new AxiosError('failed', 'ERR_BAD_REQUEST', undefined, undefined, { status, data: { error: { code, message } } } as never)

function setup() {
  auth.me.mockRejectedValue(apiError(401, 'not_authenticated', 'Authentication required'))
  render(<MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter>)
}

describe('Login', () => {
  beforeEach(() => vi.clearAllMocks())

  it('validates empty fields before calling the API', async () => {
    setup()
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(screen.getByText('Enter your username or email.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(auth.login).not.toHaveBeenCalled()
  })
  it('shows a clear error for wrong credentials', async () => {
    auth.login.mockRejectedValue(apiError(401, 'invalid_credentials', 'Invalid username or password'))
    setup()
    await userEvent.type(await screen.findByLabelText('Username or email'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Wrong username or password.')).toBeInTheDocument()
    expect(auth.login).toHaveBeenCalledWith('admin', 'wrong-password')
  })
  it('shows rate-limit and network errors', async () => {
    auth.login.mockRejectedValueOnce(apiError(429, 'rate_limited', 'Too many login attempts. Try again in 30s.'))
    setup()
    await userEvent.type(await screen.findByLabelText('Username or email'), 'admin')
    await userEvent.type(screen.getByLabelText('Password'), 'x')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Too many login attempts. Try again in 30s.')).toBeInTheDocument()
    auth.login.mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK'))
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText(/Cannot reach the server/)).toBeInTheDocument()
  })
  it('toggles password visibility', async () => {
    setup()
    const pw = await screen.findByLabelText('Password')
    expect(pw).toHaveAttribute('type', 'password')
    await userEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(pw).toHaveAttribute('type', 'text')
  })
  it('submits trimmed credentials', async () => {
    auth.login.mockResolvedValue({ id: 1, username: 'admin', role: 'admin' })
    setup()
    await userEvent.type(await screen.findByLabelText('Username or email'), '  admin  ')
    await userEvent.type(screen.getByLabelText('Password'), 'secret-pass')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(auth.login).toHaveBeenCalledWith('admin', 'secret-pass'))
  })
})
