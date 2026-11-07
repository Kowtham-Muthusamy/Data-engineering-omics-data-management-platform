import { useState } from 'react'
import { Badge, Card, Empty, ErrorBanner, Field, fmtBytes, fmtTime, inputCls, PageHeader, Table, Td, Th } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api, qs } from '../services/api'
import type { S3Object } from '../types'

interface ObjVersion { version_id: string; size: number; checksum: string; is_latest: boolean; created_at: string }

export default function S3Explorer() {
  const [run, setRun] = useState('')
  const [sample, setSample] = useState('')
  const [picked, setPicked] = useState<string | null>(null)
  const objs = usePolling(() => api<S3Object[]>('/s3/objects' + qs({ run_id: run, sample_id: sample })), 3000, [run, sample])
  const versions = usePolling(() => (picked ? api<ObjVersion[]>('/s3/versions' + qs({ key: picked })) : Promise.resolve([])), 0, [picked])

  const total = objs.data?.reduce((a, o) => a + o.size, 0) ?? 0
  const overwritten = objs.data?.filter((o) => o.overwrite_count > 0).length ?? 0

  return (
    <>
      <PageHeader title="S3 Explorer" subtitle="Objects in the simulated bucket (local_data/s3_bucket). Reruns overwrite objects at the same keys." />
      <ErrorBanner error={objs.error} />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Run ID"><input className={inputCls} value={run} onChange={(e) => setRun(e.target.value)} placeholder="RUN_001" /></Field>
          <Field label="Sample ID"><input className={inputCls} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="SAMPLE_001" /></Field>
          <div className="ml-auto text-sm text-slate-600">{objs.data?.length ?? 0} objects · {fmtBytes(total)} · {overwritten} overwritten on rerun</div>
        </div>
      </Card>
      <Card title="Objects">
        {(objs.data?.length ?? 0) === 0 ? <Empty>No objects uploaded yet.</Empty> : (
          <Table>
            <thead><tr><Th>Object key</Th><Th>Size</Th><Th>SHA-256</Th><Th>Catalogue</Th><Th>Attempt</Th><Th>Overwrites</Th><Th>Uploaded</Th></tr></thead>
            <tbody>
              {objs.data?.map((o) => (
                <tr key={o.key} className={`cursor-pointer hover:bg-slate-50 ${picked === o.key ? 'bg-indigo-50' : ''}`} onClick={() => setPicked(o.key)}>
                  <Td className="font-mono text-xs">{o.key}</Td><Td>{fmtBytes(o.size)}</Td>
                  <Td className="font-mono text-xs">{o.checksum.slice(0, 12)}…</Td>
                  <Td>{o.catalogue_version ? <Badge value={o.catalogue_version} /> : '—'}</Td>
                  <Td>#{o.attempt_id}</Td>
                  <Td>{o.overwrite_count > 0 ? <Badge value="MODIFIED" /> : '0'} {o.overwrite_count > 0 && <span className="text-xs text-slate-500">×{o.overwrite_count}</span>}</Td>
                  <Td>{fmtTime(o.uploaded_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {picked && (
        <Card className="mt-5" title={`Native object versions — ${picked}`}>
          {(versions.data?.length ?? 0) === 0 ? (
            <Empty>No native versions recorded. The optional S3 versioning simulation is off by default (enable it in Settings). Catalogue versions (V1, V2…) are a separate concept and are tracked per sample.</Empty>
          ) : (
            <Table>
              <thead><tr><Th>Version id</Th><Th>Size</Th><Th>SHA-256</Th><Th>Latest</Th><Th>Created</Th></tr></thead>
              <tbody>{versions.data?.map((v) => <tr key={v.version_id}><Td className="font-mono text-xs">{v.version_id}</Td><Td>{fmtBytes(v.size)}</Td><Td className="font-mono text-xs">{v.checksum.slice(0, 12)}…</Td><Td>{v.is_latest ? 'yes' : ''}</Td><Td>{fmtTime(v.created_at)}</Td></tr>)}</tbody>
            </Table>
          )}
        </Card>
      )}
    </>
  )
}
