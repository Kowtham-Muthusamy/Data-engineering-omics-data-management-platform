import { useState } from 'react'
import { Badge, Button, Card, Empty, ErrorBanner, fmtBytes, PageHeader, Table, Td, Th } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api } from '../services/api'
import type { IntegrityRow, NfsRun } from '../types'

export default function NfsExplorer() {
  const tree = usePolling(() => api<NfsRun[]>('/nfs/tree'), 4000)
  const [integrity, setIntegrity] = useState<IntegrityRow[] | null>(null)

  return (
    <>
      <PageHeader title="NFS Explorer" subtitle="The simulated NFS source share (local_data/nfs_source). The platform only reads from it."
        actions={<Button variant="secondary" onClick={() => void api<IntegrityRow[]>('/nfs/integrity').then(setIntegrity)}>Verify source integrity</Button>} />
      <ErrorBanner error={tree.error} />

      {integrity && (
        <Card title="Source integrity vs checksums recorded at sync time" className="mb-5"
          actions={<span className="text-xs text-slate-500">{integrity.filter((i) => i.status === 'UNCHANGED').length}/{integrity.length} unchanged</span>}>
          <Table>
            <thead><tr><Th>S3 key / NFS file</Th><Th>Status</Th><Th>Recorded sha256</Th><Th>Current sha256</Th></tr></thead>
            <tbody>
              {integrity.map((i) => (
                <tr key={i.key}><Td className="font-mono text-xs">{i.key}</Td><Td><Badge value={i.status} /></Td>
                  <Td className="font-mono text-xs">{i.recorded_nfs_sha256.slice(0, 16)}…</Td><Td className="font-mono text-xs">{i.current_nfs_sha256?.slice(0, 16) ?? '—'}…</Td></tr>
              ))}
            </tbody>
          </Table>
          <p className="mt-2 text-xs text-slate-500">MODIFIED means the NFS file was edited after its last sync (e.g. a scientist updated catalogue.json) — synchronization itself never changes NFS files.</p>
        </Card>
      )}

      {(tree.data?.length ?? 0) === 0 ? <Card><Empty>The NFS share is empty.</Empty></Card> : (
        <div className="space-y-4">
          {tree.data?.map((run) => (
            <Card key={run.run_id} title={<span className="flex items-center gap-2">{run.run_id}{run.complete ? <Badge value="PASSED" /> : <Badge value="INCOMPLETE" />}<span className="text-xs font-normal text-slate-500">{run.complete ? 'RUN_COMPLETE marker present' : 'no completion marker — will be skipped'}</span></span>}>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {run.samples.map((s) => (
                  <div key={s.sample_id} className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-2 text-sm font-semibold text-slate-800">{s.sample_id}/</div>
                    <ul className="space-y-0.5 text-xs">
                      {s.files.map((f) => (
                        <li key={f.path} className="flex justify-between gap-2 font-mono text-slate-600"><span className="truncate">{f.path}</span><span className="shrink-0 text-slate-400">{fmtBytes(f.size)}</span></li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
