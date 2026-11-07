import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, Empty, ErrorBanner, Field, fmtTime, inputCls, PageHeader, Table, Td, Th, useAction } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api, post } from '../services/api'
import type { Run } from '../types'

const SCENARIOS = ['A_GOOD', 'B_POOR_QUALITY', 'C_INSTRUMENT_WARNING']

export default function Runs() {
  const runs = usePolling(() => api<Run[]>('/runs'), 3000)
  const act = useAction()
  const [selected, setSelected] = useState<string | null>(null)
  const detail = usePolling(() => (selected ? api<Run>(`/runs/${selected}`) : Promise.resolve(null)), 3000, [selected])

  const [count, setCount] = useState(2)
  const [complete, setComplete] = useState(true)
  const [runId, setRunId] = useState('')

  const create = async () => {
    await act(() => post('/runs', { sample_count: count, mark_complete: complete, run_id: runId || undefined }), 'Run folder created on NFS')
    setRunId('')
    void runs.reload()
  }

  return (
    <>
      <PageHeader title="Sequencing Runs" subtitle="Run folders on the simulated NFS share and their ingestion state" />
      <ErrorBanner error={runs.error} />

      <Card title="Create a sequencing run on NFS" className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Run ID (optional)"><input className={inputCls} value={runId} placeholder="auto: RUN_00N" onChange={(e) => setRunId(e.target.value)} /></Field>
          <Field label="Samples (A good, B poor, C warning, cycling)">
            <input className={`${inputCls} w-24`} type="number" min={0} max={12} value={count} onChange={(e) => setCount(Number(e.target.value))} />
          </Field>
          <label className="flex items-center gap-2 pb-1.5 text-sm"><input type="checkbox" checked={complete} onChange={(e) => setComplete(e.target.checked)} /> write completion marker</label>
          <Button onClick={() => void create()}>Create run</Button>
        </div>
        <p className="mt-2 text-xs text-slate-500">Runs without the completion marker are skipped by the sequencer until you mark them complete. Run a scan (or wait for the next automatic one) to ingest.</p>
      </Card>

      <Card title="Runs">
        {(runs.data?.length ?? 0) === 0 ? <Empty>No runs yet. Create one above or use “Simulate new sequencing run” on the Overview.</Empty> : (
          <Table>
            <thead><tr><Th>Run</Th><Th>State</Th><Th>Completion marker</Th><Th>Samples</Th><Th>Sample states</Th><Th>Discovered</Th></tr></thead>
            <tbody>
              {runs.data?.map((r) => (
                <tr key={r.run_id} className={`cursor-pointer hover:bg-slate-50 ${selected === r.run_id ? 'bg-indigo-50' : ''}`} onClick={() => setSelected(r.run_id)}>
                  <Td className="font-medium text-slate-900">{r.run_id}</Td>
                  <Td><Badge value={r.state} /></Td>
                  <Td>{r.complete ? <Badge value="PASSED" /> : <Badge value="INCOMPLETE" />}</Td>
                  <Td>{r.sample_count}</Td>
                  <Td><div className="flex flex-wrap gap-1">{Object.entries(r.status_counts).map(([s, n]) => <span key={s} className="flex items-center gap-1"><Badge value={s} /><span className="text-xs text-slate-500">×{n}</span></span>)}</div></Td>
                  <Td>{fmtTime(r.discovered_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {selected && detail.data && <RunDetail run={detail.data} onChange={() => { void detail.reload(); void runs.reload() }} />}
    </>
  )
}

function RunDetail({ run, onChange }: { run: Run; onChange: () => void }) {
  const act = useAction()
  const [sampleId, setSampleId] = useState('')
  const [path, setPath] = useState('instrument_data/notes.txt')
  const [file, setFile] = useState<File | null>(null)
  const [scenario, setScenario] = useState('A_GOOD')

  const upload = async () => {
    if (!file || !sampleId) return
    const form = new FormData()
    form.append('file', file)
    await act(async () => {
      const res = await fetch(`/api/runs/${run.run_id}/files?sample_id=${encodeURIComponent(sampleId)}&path=${encodeURIComponent(path)}`, { method: 'POST', body: form })
      if (!res.ok) throw new Error((await res.json()).detail ?? 'upload failed')
    }, 'File uploaded to NFS')
    onChange()
  }

  return (
    <Card className="mt-5" title={`Run ${run.run_id}`}
      actions={
        <>
          {!run.complete && <Button variant="secondary" onClick={() => void act(() => post(`/runs/${run.run_id}/complete`), 'Run marked complete').then(onChange)}>Mark complete</Button>}
          <Button disabled={!run.discovered} title={run.discovered ? '' : 'Run a sequencer scan first'}
            onClick={() => void act(() => post(`/workflows/${run.run_id}/execute`), 'Workflow jobs submitted').then(onChange)}>
            Execute workflow
          </Button>
        </>
      }>
      {!run.discovered && (
        <p className="mb-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
          {run.complete ? 'Not discovered yet — the sequencer will pick this up on its next scan.' : 'Incomplete: no completion marker, so the sequencer will skip this folder.'}
          {' '}NFS samples: {run.nfs_samples.join(', ') || 'none'}
        </p>
      )}
      {run.samples.length > 0 && (
        <Table>
          <thead><tr><Th>Sample</Th><Th>Status</Th><Th>Quality</Th><Th>Catalogue</Th><Th>Processed</Th><Th>S3 destination</Th></tr></thead>
          <tbody>
            {run.samples.map((s) => (
              <tr key={s.sample_id}>
                <Td className="font-medium"><Link className="text-indigo-600 hover:underline" to={`/reruns?sample=${s.sample_id}`}>{s.sample_id}</Link></Td>
                <Td><Badge value={s.status} /></Td><Td><Badge value={s.quality_status} /></Td>
                <Td>{s.catalogue_version}</Td><Td>{s.processed_version ?? '—'}</Td>
                <Td className="font-mono text-xs">{s.s3_destination}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {!run.complete && (
        <div className="mt-4 border-t border-slate-100 pt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Add data to this (incomplete) run</h3>
          <div className="mb-3 flex flex-wrap items-end gap-3">
            <Field label="New sample scenario">
              <select className={inputCls} value={scenario} onChange={(e) => setScenario(e.target.value)}>{SCENARIOS.map((s) => <option key={s}>{s}</option>)}</select>
            </Field>
            <Button variant="secondary" onClick={() => void act(() => post(`/runs/${run.run_id}/samples`, { scenario }), 'Sample folder created').then(onChange)}>Add sample</Button>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Sample">
              <select className={inputCls} value={sampleId} onChange={(e) => setSampleId(e.target.value)}>
                <option value="">select…</option>{run.nfs_samples.map((s) => <option key={s}>{s}</option>)}
              </select>
            </Field>
            <Field label="Path inside sample folder"><input className={`${inputCls} w-64`} value={path} onChange={(e) => setPath(e.target.value)} /></Field>
            <Field label="File"><input type="file" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
            <Button variant="secondary" disabled={!file || !sampleId} onClick={() => void upload()}>Upload to NFS</Button>
          </div>
        </div>
      )}
    </Card>
  )
}
