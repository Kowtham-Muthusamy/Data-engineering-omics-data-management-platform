import { useState } from 'react'
import { Badge, Button, Card, Empty, ErrorBanner, fmtBytes, fmtTime, PageHeader, Table, Td, Th, useToast } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api } from '../services/api'
import type { DownstreamFetch, DownstreamItem } from '../types'

export default function Downstream() {
  const [showBlocked, setShowBlocked] = useState(false)
  const list = usePolling(() => api<DownstreamItem[]>(`/downstream/available?include_blocked=${showBlocked}`), 3000, [showBlocked])
  const [fetched, setFetched] = useState<DownstreamFetch | null>(null)
  const [denied, setDenied] = useState<string | null>(null)
  const notify = useToast()

  const doFetch = async (id: string) => {
    setFetched(null)
    setDenied(null)
    try {
      setFetched(await api<DownstreamFetch>(`/downstream/${id}/fetch`))
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setDenied(`${id}: ${msg}`)
      notify(`Backend refused access to ${id}`, 'error')
    }
    void list.reload()
  }

  return (
    <>
      <PageHeader title="Downstream Applications" subtitle="A simulated downstream consumer. The quality gate is enforced by the backend; the buttons here are only a convenience."
        actions={<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showBlocked} onChange={(e) => setShowBlocked(e.target.checked)} /> show blocked samples</label>} />
      <ErrorBanner error={list.error} />
      <Card title={showBlocked ? 'All samples (blocked ones included)' : 'Samples eligible for consumption'}>
        {(list.data?.length ?? 0) === 0 ? <Empty>No eligible samples. Samples appear here once the latest required processing attempt has passed QC.</Empty> : (
          <Table>
            <thead><tr><Th>Sample</Th><Th>Run</Th><Th>Latest catalogue</Th><Th>Quality</Th><Th>Gate</Th><Th>Processed</Th><Th></Th></tr></thead>
            <tbody>
              {list.data?.map((s) => (
                <tr key={s.sample_id}>
                  <Td className="font-medium">{s.sample_id}</Td><Td>{s.run_id}</Td><Td>{s.catalogue_version}</Td><Td><Badge value={s.quality_status} /></Td>
                  <Td>{s.eligible ? <Badge value="PASSED" /> : <span><Badge value="FAILED" /> <span className="text-xs text-slate-500">{s.reason}</span></span>}</Td>
                  <Td>{fmtTime(s.last_processed_at)}</Td>
                  <Td><Button variant={s.eligible ? 'primary' : 'secondary'} onClick={() => void doFetch(s.sample_id)}>{s.eligible ? 'Fetch' : 'Try fetch'}</Button></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {denied && (
        <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <b>403 Forbidden — blocked by the backend quality gate.</b>
          <div className="mt-1">{denied}</div>
        </div>
      )}

      {fetched && (
        <Card className="mt-5" title={`${fetched.sample_id} — catalogue ${fetched.catalogue_version} (processed ${fetched.processed_version})`}>
          <div className="mb-3 text-sm text-slate-600">S3 location: <span className="font-mono text-xs">{fetched.s3_destination}</span></div>
          <Table>
            <thead><tr><Th>File</Th><Th>S3 URI</Th><Th>Size</Th><Th></Th></tr></thead>
            <tbody>
              {fetched.files.map((f) => (
                <tr key={f.key}><Td className="font-mono text-xs">{f.path}</Td><Td className="font-mono text-xs">{f.s3_uri}</Td><Td>{fmtBytes(f.size)}</Td>
                  <Td><a className="rounded-lg border border-slate-300 px-2.5 py-1 text-sm text-indigo-700 hover:bg-slate-50" href={f.download_url} download>Download</a></Td></tr>
              ))}
            </tbody>
          </Table>
          <h3 className="mb-1 mt-4 text-sm font-semibold text-slate-700">Sample metadata</h3>
          <pre className="max-h-64 overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(fetched.metadata, null, 2)}</pre>
        </Card>
      )}
    </>
  )
}
