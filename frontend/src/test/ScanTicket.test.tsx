import { render, screen } from '@testing-library/react'
import { ScanTicket } from '../components/ScanTicket'
import { describeScan } from '../utils/scanState'
import type { ScanResult } from '../types'

const input = { phase: 'scanning' as const, recognizing: false, faceDetected: true, backendOnline: true }
const marked: ScanResult = {
  status: 'marked', message: 'Welcome, Rahul Sharma. Attendance recorded at 9:12 AM.', similarity: 0.87,
  person: { id: 1, person_code: 'E1', full_name: 'Rahul Sharma', department: 'CS' },
  attendance: { id: 5, session: 'Morning', session_date: '2026-01-05', marked_at: '2026-01-05T03:42:00Z', local_time: '09:12:00', status: 'late', method: 'face' },
}
const show = (result: ScanResult | null, extra = {}) => render(<ScanTicket view={describeScan({ ...input, result, ...extra })} result={result} />)

describe('ScanTicket', () => {
  it('shows the confirmed attendance with name, ID, session and time', () => {
    show(marked)
    expect(screen.getByText('Attendance marked')).toBeInTheDocument()
    expect(screen.getByText('Welcome, Rahul Sharma. Attendance recorded at 9:12 AM.')).toBeInTheDocument()
    expect(screen.getByText('E1')).toBeInTheDocument()
    expect(screen.getByText('Morning')).toBeInTheDocument()
    expect(screen.getByText(/09:12:00/)).toBeInTheDocument()
    expect(screen.getByText('Late')).toBeInTheDocument()
    expect(screen.getByTitle(/not a probability/i)).toHaveTextContent('0.87')         // score is labelled, never a "confidence %"
    expect(screen.getByTestId('scan-ticket')).toHaveAttribute('data-state', 'marked')
  })
  it('shows the duplicate warning without claiming a new record', () => {
    show({ ...marked, status: 'already_marked', message: 'Your attendance has already been recorded.' })
    expect(screen.getByText('Already marked')).toBeInTheDocument()
    expect(screen.getByText('First recorded at')).toBeInTheDocument()
    expect(screen.queryByText('Attendance marked')).not.toBeInTheDocument()
  })
  it('shows unknown people without any name or ID', () => {
    show({ status: 'unknown', message: 'x' })
    expect(screen.getByText('Person not recognized')).toBeInTheDocument()
    expect(screen.getByText('Person not recognized. No attendance recorded.')).toBeInTheDocument()
    expect(screen.queryByText('Person ID')).not.toBeInTheDocument()
  })
  it('shows server and model errors', () => {
    show({ status: 'model_unavailable', message: 'The face recognition model is not available. Contact an administrator.' })
    expect(screen.getByText('Recognition unavailable')).toBeInTheDocument()
  })
  it('shows the lost-connection state instead of stale results', () => {
    show(marked, { backendOnline: false })
    expect(screen.getByText('Server not connected')).toBeInTheDocument()
    expect(screen.queryByText('Person ID')).not.toBeInTheDocument()
  })
  it('shows the liveness instruction', () => {
    show({ status: 'liveness_challenge', message: 'Slowly turn your head to YOUR LEFT.', challenge: 'left' })
    expect(screen.getByText('Slowly turn your head to YOUR LEFT.')).toBeInTheDocument()
    expect(screen.getByText(/not strong spoof protection/i)).toBeInTheDocument()
  })
})
