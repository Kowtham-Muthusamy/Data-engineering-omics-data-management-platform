import { useState } from 'react'
import { Badge, Card, Empty, ErrorBanner, Field, fmtTime, inputCls, PageHeader, Table, Td, Th } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api, qs } from '../services/api'
import type { LogEntry } from '../types'

export default function Logs() {
  const [level, setLevel] = useState('')
  const [source, setSource] = useState('')
  const [sample, setSample] = useState('')
  const logs = usePolling(() => api<LogEntry[]>('/logs' + qs({ level, source, sample_id: sample, limit: 300 })), 3000, [level, source, sample])

  return (
    <>
      <PageHeader title="System Logs" subtitle="Audit trail of state transitions, scans, workflow events, recoveries and downstream access decisions" />
      <ErrorBanner error={logs.error} />
      <Card className="mb-5">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Level"><select className={inputCls} value={level} onChange={(e) => setLevel(e.target.value)}>{['', 'INFO', 'WARN', 'ERROR'].map((l) => <option key={l} value={l}>{l || 'any'}</option>)}</select></Field>
          <Field label="Source"><select className={inputCls} value={source} onChange={(e) => setSource(e.target.value)}>{['', 'nfs', 'sequencer', 'state', 'catalogue', 'workflow', 'rerun', 'recovery', 'downstream'].map((l) => <option key={l} value={l}>{l || 'any'}</option>)}</select></Field>
          <Field label="Sample"><input className={inputCls} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="SAMPLE_001" /></Field>
        </div>
      </Card>
      <Card>
        {(logs.data?.length ?? 0) === 0 ? <Empty>No log entries.</Empty> : (
          <Table>
            <thead><tr><Th>Time</Th><Th>Level</Th><Th>Source</Th><Th>Message</Th></tr></thead>
            <tbody>
              {logs.data?.map((e) => (
                <tr key={e.id}><Td className="whitespace-nowrap text-xs">{fmtTime(e.ts)}</Td><Td><Badge value={e.level} /></Td><Td className="text-xs font-medium">{e.source}</Td><Td className="break-words text-xs">{e.message}</Td></tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  )
}
