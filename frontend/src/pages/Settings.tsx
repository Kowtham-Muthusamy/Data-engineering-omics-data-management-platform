import { useEffect, useState } from 'react'
import { Button, Card, ErrorBanner, Field, inputCls, PageHeader, useAction } from '../components/ui'
import { usePolling } from '../hooks/usePolling'
import { api, put } from '../services/api'
import type { Settings as SettingsT } from '../types'

export default function Settings() {
  const remote = usePolling(() => api<SettingsT>('/settings'), 0)
  const [s, setS] = useState<SettingsT | null>(null)
  const act = useAction()
  useEffect(() => { if (remote.data && !s) setS(remote.data) }, [remote.data, s])

  if (!s) return <ErrorBanner error={remote.error} />
  const toggle = (k: 'auto_scan_enabled' | 'auto_process' | 's3_versioning_enabled', label: string, help: string) => (
    <label className="flex items-start gap-3 py-2">
      <input type="checkbox" className="mt-1" checked={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.checked })} />
      <span><span className="text-sm font-medium text-slate-800">{label}</span><span className="block text-xs text-slate-500">{help}</span></span>
    </label>
  )

  return (
    <>
      <PageHeader title="Settings" subtitle="Runtime configuration. Changes apply immediately and persist across restarts." />
      <Card className="max-w-2xl">
        <div className="space-y-2">
          <Field label="Scan interval (seconds)">
            <input type="number" min={1} className={`${inputCls} w-32`} value={s.scan_interval_seconds} onChange={(e) => setS({ ...s, scan_interval_seconds: Number(e.target.value) })} />
          </Field>
          {toggle('auto_scan_enabled', 'Automatic folder scanning', 'The background sequencer scans the NFS share every interval. Manual scans always work.')}
          {toggle('auto_process', 'Automatically start workflows for newly discovered samples', 'When off, discovery only registers samples; start workflows from the Runs page.')}
          {toggle('s3_versioning_enabled', 'S3 object versioning simulation', 'Optional and OFF by default. Keeps every overwritten object as a native S3-style version. Unrelated to catalogue versions (V1, V2…).')}
          <Field label="QC warning policy">
            <select className={`${inputCls} w-40`} value={s.warning_policy} onChange={(e) => setS({ ...s, warning_policy: e.target.value })}>
              <option value="PASS">PASS (warnings allowed)</option><option value="FAIL">FAIL (warnings block)</option>
            </select>
          </Field>
          <p className="text-xs text-slate-500">Decides the outcome of the “instrument quality warning” scenario (C): treat WARN results as pass or fail at the quality gate.</p>
        </div>
        <div className="mt-4"><Button onClick={() => void act(() => put<SettingsT>('/settings', s).then(setS), 'Settings saved')}>Save settings</Button></div>
      </Card>
    </>
  )
}
