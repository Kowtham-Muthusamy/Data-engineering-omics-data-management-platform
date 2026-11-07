import { useState } from 'react'
import { Badge, Button, Card, Empty, ErrorBanner, Field, fmtTime, inputCls, PageHeader, Table, Td, Th } from '../components/ui'
import { api, qs } from '../services/api'
import type { SearchHit } from '../types'

const STATUSES = ['', 'DISCOVERED', 'INGESTING', 'INGESTED', 'PROCESSING', 'QC_PENDING', 'PASSED', 'FAILED', 'RERUN_REQUIRED']
const QUALITY = ['', 'NOT_RUN', 'PENDING', 'PASS', 'FAIL', 'STALE', 'ERROR']

export default function MetadataSearch() {
  const [f, setF] = useState({ q: '', sample_id: '', run_id: '', catalogue_version: '', processing_status: '', quality_status: '', created_from: '', created_to: '' })
  const [res, setRes] = useState<{ total: number; items: SearchHit[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value })

  const search = async () => {
    try {
      setErr(null)
      setRes(await api('/metadata/search' + qs({ ...f, created_from: f.created_from || undefined, created_to: f.created_to || undefined })))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }
  const sel = (k: keyof typeof f, opts: string[]) => (
    <select className={inputCls} value={f[k]} onChange={set(k)}>{opts.map((o) => <option key={o} value={o}>{o || 'any'}</option>)}</select>
  )

  return (
    <>
      <PageHeader title="Metadata Search" subtitle="Search the metadata index (OpenSearch simulator). It is derived from, and separate from, the operational state tables." />
      <Card className="mb-5">
        <form className="grid gap-3 md:grid-cols-4" onSubmit={(e) => { e.preventDefault(); void search() }}>
          <Field label="Free text"><input className={inputCls} value={f.q} onChange={set('q')} placeholder="e.g. homo sapiens" /></Field>
          <Field label="Sample ID"><input className={inputCls} value={f.sample_id} onChange={set('sample_id')} placeholder="SAMPLE_001" /></Field>
          <Field label="Run ID"><input className={inputCls} value={f.run_id} onChange={set('run_id')} placeholder="RUN_001" /></Field>
          <Field label="Catalogue version"><input className={inputCls} value={f.catalogue_version} onChange={set('catalogue_version')} placeholder="V2" /></Field>
          <Field label="Processing status">{sel('processing_status', STATUSES)}</Field>
          <Field label="Quality status">{sel('quality_status', QUALITY)}</Field>
          <Field label="Created from"><input type="date" className={inputCls} value={f.created_from} onChange={set('created_from')} /></Field>
          <Field label="Created to"><input type="date" className={inputCls} value={f.created_to} onChange={set('created_to')} /></Field>
          <div className="md:col-span-4"><Button type="submit">Search</Button></div>
        </form>
      </Card>
      <ErrorBanner error={err} />
      {res && (
        <Card title={`${res.total} result${res.total === 1 ? '' : 's'}`}>
          {res.items.length === 0 ? <Empty>No matching samples.</Empty> : (
            <Table>
              <thead><tr><Th>Sample</Th><Th>Run</Th><Th>Catalogue</Th><Th>Processing</Th><Th>Quality</Th><Th>Created</Th><Th>Indexed</Th></tr></thead>
              <tbody>
                {res.items.map((h) => (
                  <>
                    <tr key={h.sample_id} className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === h.sample_id ? null : h.sample_id)}>
                      <Td className="font-medium">{h.sample_id}</Td><Td>{h.run_id}</Td><Td>{h.catalogue_version}</Td>
                      <Td><Badge value={h.processing_status} /></Td><Td><Badge value={h.quality_status} /></Td>
                      <Td>{fmtTime(h.created_at)}</Td><Td>{fmtTime(h.indexed_at)}</Td>
                    </tr>
                    {open === h.sample_id && (
                      <tr key={h.sample_id + '-doc'}><td colSpan={7} className="bg-slate-50 p-3"><pre className="max-h-72 overflow-auto text-xs text-slate-700">{JSON.stringify(h.document, null, 2)}</pre></td></tr>
                    )}
                  </>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      )}
    </>
  )
}
