import { useState } from 'react'
import { Badge, Card, duration, Empty, ErrorBanner, fmtTime, PageHeader, Table, Td, Th } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api } from '../services/api'
import type { Job, JobDetail } from '../types'

const BAR: Record<string, string> = {
  SUCCEEDED: 'bg-emerald-500', FAILED: 'bg-red-500', RUNNING: 'bg-blue-500 animate-pulse', INTERRUPTED: 'bg-red-400',
  SKIPPED: 'bg-slate-300', PENDING: 'bg-slate-200',
}

export default function Workflows() {
  const jobs = usePolling(() => api<Job[]>('/workflows'), 2000)
  const [picked, setPicked] = useState<string | null>(null)
  const detail = usePolling(() => (picked ? api<JobDetail>(`/workflows/${picked}`) : Promise.resolve(null)), 1500, [picked])
  const [openStep, setOpenStep] = useState<string | null>(null)

  return (
    <>
      <PageHeader title="Workflow Executions" subtitle="Local workflow engine — a simulation of the roles AWS Batch and miniWDL play. It does not run either." />
      <ErrorBanner error={jobs.error} />
      <Card title="Jobs (one per sample processing attempt)">
        {(jobs.data?.length ?? 0) === 0 ? <Empty>No workflow jobs yet.</Empty> : (
          <Table>
            <thead><tr><Th>Job</Th><Th>Run</Th><Th>Sample</Th><Th>Status</Th><Th>Created</Th><Th>Duration</Th></tr></thead>
            <tbody>
              {jobs.data?.map((j) => (
                <tr key={j.job_id} className={`cursor-pointer hover:bg-slate-50 ${picked === j.job_id ? 'bg-indigo-50' : ''}`} onClick={() => setPicked(j.job_id)}>
                  <Td className="font-mono text-xs">{j.job_id}</Td><Td>{j.run_id}</Td><Td>{j.sample_id}</Td>
                  <Td><Badge value={j.status} /></Td><Td>{fmtTime(j.created_at)}</Td><Td>{duration(j.started_at, j.ended_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {detail.data && (
        <Card className="mt-5" title={`Execution timeline — ${detail.data.job_id}`}
          actions={<span className="text-xs text-slate-500">{detail.data.sample_id} · attempt #{detail.data.attempt_no} ({detail.data.attempt_kind}) · catalogue {detail.data.catalogue_version}</span>}>
          <p className="mb-3 text-xs text-amber-700">{detail.data.notice}</p>
          {detail.data.error && <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{detail.data.error}</div>}
          <ol className="space-y-2">
            {detail.data.steps.map((s) => (
              <li key={s.name} className="rounded-lg border border-slate-200">
                <button className="flex w-full items-center gap-3 px-3 py-2 text-left" onClick={() => setOpenStep(openStep === s.name ? null : s.name)}>
                  <span className={`h-3 w-3 shrink-0 rounded-full ${BAR[s.status] ?? 'bg-slate-300'}`} />
                  <span className="w-48 shrink-0 font-mono text-sm text-slate-800">{s.step_order + 1}. {s.name}</span>
                  <Badge value={s.status} />
                  {s.retries > 0 && <span className="text-xs text-orange-600">{s.retries} retr{s.retries === 1 ? 'y' : 'ies'}</span>}
                  <span className="ml-auto text-xs text-slate-500">{fmtTime(s.started_at)} → {s.ended_at ? fmtTime(s.ended_at) : '…'} ({duration(s.started_at, s.ended_at)})</span>
                </button>
                {(openStep === s.name || s.status === 'FAILED') && (
                  <div className="border-t border-slate-100 bg-slate-50 px-3 py-2">
                    {s.error && <div className="mb-1 text-sm font-medium text-red-700">Error: {s.error}</div>}
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs text-slate-700">{s.logs || '(no log output)'}</pre>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </Card>
      )}
    </>
  )
}
