import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, duration, Empty, ErrorBanner, Field, fmtTime, inputCls, PageHeader, Table, Td, Th, useAction } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api, post } from '../services/api'
import type { History, SampleDetail, SampleSummary } from '../types'

const SCENARIOS = ['', 'A_GOOD', 'B_POOR_QUALITY', 'C_INSTRUMENT_WARNING']

export default function Reruns() {
  const [params, setParams] = useSearchParams()
  const samples = usePolling(() => api<SampleSummary[]>('/samples'), 3000)
  const picked = params.get('sample')
  const sample = usePolling(() => (picked ? api<SampleDetail>(`/samples/${picked}`) : Promise.resolve(null)), 2000, [picked])
  const history = usePolling(() => (picked ? api<History>(`/samples/${picked}/history`) : Promise.resolve(null)), 2000, [picked])
  const act = useAction()
  const [version, setVersion] = useState('')
  const [notes, setNotes] = useState('')
  const [scenario, setScenario] = useState('')

  const cur = sample.data
  useEffect(() => {
    if (cur) {
      const n = Number(cur.catalogue_version.replace('V', '')) + 1
      setVersion(`V${n}`)
    }
  }, [cur?.catalogue_version]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { void samples.reload(); void sample.reload(); void history.reload() }

  return (
    <>
      <PageHeader title="Base Recall / Reruns" subtitle="Update a sample's catalogue version and re-run the same sample. Reruns overwrite the same S3 keys and add a new processing attempt." />
      <ErrorBanner error={samples.error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Samples" className="lg:col-span-1">
          {(samples.data?.length ?? 0) === 0 ? <Empty>No samples discovered yet.</Empty> : (
            <ul className="divide-y divide-slate-100">
              {samples.data?.map((s) => (
                <li key={s.sample_id}>
                  <button onClick={() => setParams({ sample: s.sample_id })}
                    className={`flex w-full items-center justify-between gap-2 px-2 py-2 text-left text-sm hover:bg-slate-50 ${picked === s.sample_id ? 'bg-indigo-50' : ''}`}>
                    <span><span className="font-medium">{s.sample_id}</span> <span className="text-xs text-slate-500">{s.catalogue_version}{s.processed_version && s.processed_version !== s.catalogue_version ? ` (processed ${s.processed_version})` : ''}</span></span>
                    <Badge value={s.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {!cur ? <Card><Empty>Select a sample to update its catalogue or start a base recall.</Empty></Card> : (
            <>
              <Card title={`${cur.sample_id} — ${cur.run_id}`}>
                <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                  <div><div className="text-xs text-slate-500">Status</div><Badge value={cur.status} /></div>
                  <div><div className="text-xs text-slate-500">Quality</div><Badge value={cur.quality_status} /></div>
                  <div><div className="text-xs text-slate-500">Catalogue version</div><b>{cur.catalogue_version}</b></div>
                  <div><div className="text-xs text-slate-500">Last successfully processed</div><b>{cur.processed_version ?? '—'}</b></div>
                </div>
                <p className="mt-3 text-sm text-slate-600">
                  Downstream: {cur.eligible_for_downstream ? <Badge value="PASSED" /> : <Badge value="FAILED" />} <span className="ml-1">{cur.downstream_reason}</span>
                </p>
                {cur.status === 'RERUN_REQUIRED' && (
                  <div className="mt-3 flex items-center gap-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    Catalogue {cur.catalogue_version} differs from the last successfully processed version ({cur.processed_version ?? 'none'}). Previous results are withdrawn from downstream.
                    <Button onClick={() => void act(() => post(`/samples/${cur.sample_id}/base-recall`), 'Base recall started').then(refresh)}>Start base recall</Button>
                  </div>
                )}
              </Card>

              <Card title="Update catalogue information">
                <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => {
                  e.preventDefault()
                  const fields: Record<string, unknown> = {}
                  if (scenario) fields.simulation_scenario = scenario
                  void act(() => post(`/samples/${cur.sample_id}/catalogue/update`, { version, notes: notes || undefined, fields }), `Catalogue updated to ${version}`).then(refresh)
                }}>
                  <Field label="New version"><input className={`${inputCls} w-24`} value={version} onChange={(e) => setVersion(e.target.value)} /></Field>
                  <Field label="Notes"><input className={`${inputCls} w-64`} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="what changed?" /></Field>
                  <Field label="Simulated outcome (optional)">
                    <select className={inputCls} value={scenario} onChange={(e) => setScenario(e.target.value)}>{SCENARIOS.map((s) => <option key={s} value={s}>{s || 'keep current'}</option>)}</select>
                  </Field>
                  <Button type="submit">Update catalogue</Button>
                </form>
                <p className="mt-2 text-xs text-slate-500">The update is written to the sample&apos;s catalogue.json on NFS and registered as a new catalogue version. The sample keeps its ID. “Simulated outcome” lets you flip a FAIL to a PASS (or vice versa) on rerun to see the quality gate react.</p>
              </Card>

              {history.data && (
                <>
                  <Card title="Processing attempt history">
                    <Table>
                      <thead><tr><Th>#</Th><Th>Kind</Th><Th>Catalogue</Th><Th>Status</Th><Th>QC</Th><Th>Accepted</Th><Th>Job</Th><Th>Started</Th><Th>Duration</Th></tr></thead>
                      <tbody>
                        {history.data.attempts.map((a) => (
                          <tr key={a.id}>
                            <Td>{a.attempt_no}</Td><Td><Badge value={a.kind} /></Td><Td><b>{a.catalogue_version}</b></Td><Td><Badge value={a.status} /></Td>
                            <Td>{a.qc_status ? <Badge value={a.qc_status} /> : '—'}</Td><Td>{a.accepted ? 'yes' : 'no'}</Td>
                            <Td className="font-mono text-xs">{a.job_id}</Td><Td>{fmtTime(a.started_at)}</Td><Td>{duration(a.started_at, a.ended_at)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                    {history.data.attempts.some((a) => a.error) && <ul className="mt-2 space-y-1 text-xs text-red-700">{history.data.attempts.filter((a) => a.error).map((a) => <li key={a.id}>#{a.attempt_no}: {a.error}</li>)}</ul>}
                  </Card>
                  <div className="grid gap-4 md:grid-cols-2">
                    <Card title="Catalogue versions">
                      <ul className="space-y-2 text-sm">
                        {history.data.catalogue_versions.map((v) => (
                          <li key={v.id} className="rounded-lg border border-slate-200 p-2"><b>{v.version}</b> <span className="text-xs text-slate-500">{v.source} · {fmtTime(v.created_at)}</span>
                            <div className="text-xs text-slate-500">{String(v.content.notes ?? '')}</div></li>
                        ))}
                      </ul>
                    </Card>
                    <Card title="S3 objects (same keys across reruns)">
                      <ul className="space-y-1 text-xs">
                        {history.data.s3_objects.map((o) => (
                          <li key={o.key} className="flex justify-between gap-2 font-mono"><span className="truncate">{o.key.split('/').slice(2).join('/')}</span>
                            <span className="shrink-0 text-slate-500">{o.catalogue_version} · overwritten ×{o.overwrite_count}</span></li>
                        ))}
                      </ul>
                    </Card>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}
