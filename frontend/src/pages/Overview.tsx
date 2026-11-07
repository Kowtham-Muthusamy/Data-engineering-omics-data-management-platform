import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Badge, Button, Card, Empty, ErrorBanner, fmtTime, Kpi, PageHeader, useAction } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api, post } from '../services/api'
import type { Scan, SequencerStatus, Summary } from '../types'

const COLORS = ['#6366f1', '#10b981', '#ef4444', '#f59e0b', '#06b6d4', '#8b5cf6', '#64748b', '#ec4899']
const PASS_FAIL_COLORS: Record<string, string> = { PASS: '#10b981', FAIL: '#ef4444' }

export default function Overview() {
  const summary = usePolling(() => api<Summary>('/dashboard/summary'), 3000)
  const seq = usePolling(() => api<SequencerStatus>('/sequencer/status'), 3000)
  const act = useAction()
  const refresh = () => { void summary.reload(); void seq.reload() }

  const k = summary.data?.kpis
  const charts = summary.data?.charts
  const last: Scan | null | undefined = seq.data?.last_scan

  return (
    <>
      <PageHeader title="Overview" subtitle="Version-aware scientific data ingestion and workflow orchestration (local simulation)"
        actions={
          <>
            <Button variant="secondary" onClick={() => void act(() => post('/nfs/simulate-arrival?incomplete=true'), 'Incomplete run created (no completion marker)').then(refresh)}>
              Simulate incomplete run
            </Button>
            <Button onClick={() => void act(() => post('/nfs/simulate-arrival'), 'New sequencing run arrived on the NFS share').then(refresh)}>
              Simulate new sequencing run
            </Button>
          </>
        } />
      <ErrorBanner error={summary.error} />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-7">
        <Kpi label="Sequencing runs" value={k?.total_runs ?? 0} />
        <Kpi label="Newly discovered" value={k?.newly_discovered_runs ?? 0} tone="text-indigo-600" />
        <Kpi label="Ingested runs" value={k?.ingested_runs ?? 0} tone="text-blue-600" />
        <Kpi label="Processing" value={k?.currently_processing ?? 0} tone="text-blue-600" />
        <Kpi label="Passed QC" value={k?.passed_qc ?? 0} tone="text-emerald-600" />
        <Kpi label="Failed QC" value={k?.failed_qc ?? 0} tone="text-red-600" />
        <Kpi label="Reruns initiated" value={k?.reruns_initiated ?? 0} tone="text-violet-600" />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <Card title="Folder sequencer" className="lg:col-span-1"
          actions={<Button disabled={seq.data?.scanning} onClick={() => void act(() => post<Scan>('/sequencer/scan'), 'Scan complete').then(refresh)}>
            {seq.data?.scanning ? 'Scanning…' : 'Scan now'}
          </Button>}>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <dt className="text-slate-500">Auto scan</dt>
            <dd>{seq.data?.auto_scan_enabled ? <Badge value="PASSED" /> : <Badge value="SKIPPED" />} every {seq.data?.interval_seconds ?? '—'}s</dd>
            <dt className="text-slate-500">Last scan</dt><dd>{fmtTime(last?.finished_at)}{last && <span className="ml-1 text-xs text-slate-400">({last.trigger})</span>}</dd>
            <dt className="text-slate-500">Next scan</dt><dd>{seq.data?.auto_scan_enabled ? fmtTime(seq.data?.next_scan_at) : 'auto scan off'}</dd>
            <dt className="text-slate-500">Folders discovered</dt><dd>{last?.discovered_folders ?? 0}</dd>
            <dt className="text-slate-500">New runs</dt><dd>{last?.new_runs ?? 0}</dd>
            <dt className="text-slate-500">Changed versions</dt><dd>{last?.changed_versions ?? 0}</dd>
            <dt className="text-slate-500">Skipped folders</dt><dd>{last?.skipped_folders ?? 0}</dd>
            <dt className="text-slate-500">Failed operations</dt><dd className={last?.failed_operations ? 'font-semibold text-red-600' : ''}>{last?.failed_operations ?? 0}</dd>
            <dt className="text-slate-500">Total scans</dt><dd>{seq.data?.scans_total ?? 0}</dd>
          </dl>
          {last && last.details.length > 0 && (
            <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-slate-500">
              {last.details.slice(0, 5).map((d, i) => <li key={i}>{d}</li>)}
            </ul>
          )}
        </Card>

        <Card title="Ingestion activity (processing attempts per day)" className="lg:col-span-2">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={charts?.ingestion_activity ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} fontSize={11} />
                <YAxis allowDecimals={false} fontSize={11} />
                <Tooltip />
                <Bar dataKey="attempts" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="PASS vs FAIL (latest results)">
          <Donut data={charts?.pass_fail ?? []} colors={PASS_FAIL_COLORS} />
        </Card>
        <Card title="Processing status distribution">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={charts?.processing_status ?? []} layout="vertical" margin={{ left: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis type="number" allowDecimals={false} fontSize={11} />
                <YAxis type="category" dataKey="name" fontSize={10} width={110} />
                <Tooltip />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {(charts?.processing_status ?? []).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Catalogue version distribution">
          <Donut data={charts?.catalogue_versions ?? []} />
        </Card>
      </div>

      <Card title="Recent activity" className="mt-5">
        {(summary.data?.recent_activity.length ?? 0) === 0 ? <Empty>No activity yet. Simulate a new sequencing run to begin.</Empty> : (
          <ul className="divide-y divide-slate-100">
            {summary.data?.recent_activity.map((e) => (
              <li key={e.id} className="flex items-start gap-3 py-2 text-sm">
                <span className="w-40 shrink-0 text-xs text-slate-400">{fmtTime(e.ts)}</span>
                <Badge value={e.level} />
                <span className="w-24 shrink-0 text-xs font-medium text-slate-500">{e.source}</span>
                <span className="min-w-0 break-words text-slate-700">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}

function Donut({ data, colors }: { data: { name: string; value: number }[]; colors?: Record<string, string> }) {
  const total = data.reduce((a, b) => a + b.value, 0)
  if (total === 0) return <Empty>No data yet</Empty>
  return (
    <div className="h-56">
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data.filter((d) => d.value > 0)} dataKey="value" nameKey="name" innerRadius={45} outerRadius={75} paddingAngle={2}>
            {data.filter((d) => d.value > 0).map((d, i) => <Cell key={d.name} fill={colors?.[d.name] ?? COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
