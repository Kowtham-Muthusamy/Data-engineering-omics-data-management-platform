import { useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Badge, Card, Empty, ErrorBanner, fmtTime, PageHeader, Table, Td, Th } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api } from '../services/api'
import type { QcResult } from '../types'

export default function QualityControl() {
  const res = usePolling(() => api<QcResult[]>('/qc/results'), 3000)
  const [picked, setPicked] = useState<number | null>(null)
  const sel = res.data?.find((r) => r.id === picked) ?? res.data?.[0]

  return (
    <>
      <PageHeader title="Quality Control" subtitle="Simulated InterOp + FastQC reports and the quality-gate verdict for every processing attempt" />
      <ErrorBanner error={res.error} />
      <Card title="Results">
        {(res.data?.length ?? 0) === 0 ? <Empty>No QC results yet.</Empty> : (
          <Table>
            <thead><tr><Th>Sample</Th><Th>Attempt</Th><Th>Catalogue</Th><Th>InterOp</Th><Th>FastQC</Th><Th>Gate</Th><Th>Current?</Th><Th>When</Th></tr></thead>
            <tbody>
              {res.data?.map((r) => (
                <tr key={r.id} className={`cursor-pointer hover:bg-slate-50 ${sel?.id === r.id ? 'bg-indigo-50' : ''}`} onClick={() => setPicked(r.id)}>
                  <Td className="font-medium">{r.sample_id}</Td><Td>#{r.attempt_no}</Td><Td>{r.catalogue_version}</Td>
                  <Td><Badge value={r.interop.status} /></Td><Td><Badge value={r.fastqc.status} /></Td><Td><Badge value={r.overall} /></Td>
                  <Td>{r.is_latest_attempt ? 'latest' : <span className="text-slate-400">superseded</span>}</Td><Td>{fmtTime(r.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {sel && (
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <Card title={`InterOp (simulated) — ${sel.sample_id}, attempt #${sel.attempt_no}`}>
            <p className="mb-2 text-xs text-amber-700">{sel.interop.tool}</p>
            <Table>
              <thead><tr><Th>Metric</Th><Th>Value</Th><Th>Rule</Th><Th>Status</Th></tr></thead>
              <tbody>{sel.interop.checks.map((c) => <tr key={c.metric}><Td className="font-mono text-xs">{c.metric}</Td><Td>{c.value}</Td><Td className="text-xs text-slate-500">{c.threshold}</Td><Td><Badge value={c.status} /></Td></tr>)}</tbody>
            </Table>
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-600">
              {Object.entries(sel.interop.metrics).filter(([k]) => !['cluster_density_k_mm2', 'clusters_pf_pct', 'q30_pct'].includes(k)).map(([k, v]) => <div key={k}><div className="text-slate-400">{k}</div><div className="font-medium">{v}</div></div>)}
            </div>
          </Card>

          <Card title="FastQC (simulated) — module summary">
            <p className="mb-2 text-xs text-amber-700">{sel.fastqc.tool}</p>
            <div className="mb-3 text-sm text-slate-600">{sel.fastqc.basic_statistics.total_reads} reads · length {sel.fastqc.basic_statistics.sequence_length} · GC {sel.fastqc.basic_statistics.gc_pct}%</div>
            <Table>
              <tbody>{Object.entries(sel.fastqc.modules).map(([name, m]) => <tr key={name}><Td className="font-mono text-xs">{name}</Td><Td><Badge value={m.status} /></Td></tr>)}</tbody>
            </Table>
          </Card>

          <Card title="Per-base sequence quality (median Phred)" className="lg:col-span-2">
            <div className="h-64">
              <ResponsiveContainer>
                <LineChart data={sel.fastqc.per_base_quality}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="position" fontSize={11} label={{ value: 'position in read', position: 'insideBottom', offset: -2, fontSize: 11 }} />
                  <YAxis domain={[0, 42]} fontSize={11} />
                  <Tooltip />
                  <Legend />
                  <ReferenceLine y={28} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'warn', fontSize: 10 }} />
                  <ReferenceLine y={20} stroke="#ef4444" strokeDasharray="4 4" label={{ value: 'fail', fontSize: 10 }} />
                  <Line type="monotone" dataKey="upper_quartile" stroke="#a5b4fc" dot={false} name="upper quartile" />
                  <Line type="monotone" dataKey="median" stroke="#4f46e5" strokeWidth={2} dot={false} name="median" />
                  <Line type="monotone" dataKey="lower_quartile" stroke="#a5b4fc" dot={false} name="lower quartile" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title={`Quality gate verdict: ${sel.overall}`} className="lg:col-span-2">
            <ul className="list-disc space-y-0.5 pl-5 text-sm text-slate-700">{sel.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </Card>
        </div>
      )}
    </>
  )
}
