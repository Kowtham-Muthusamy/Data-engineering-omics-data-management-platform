export interface SampleSummary {
  sample_id: string
  run_id: string
  catalogue_version: string
  processed_version: string | null
  status: string
  quality_status: string
  last_processed_at: string | null
  latest_attempt_id: number | null
  s3_destination: string
}

export interface SampleDetail extends SampleSummary {
  eligible_for_downstream: boolean
  downstream_reason: string
  nfs_complete: boolean
  metadata: Record<string, unknown>
}

export interface Run {
  run_id: string
  state: string
  complete: boolean
  discovered: boolean
  discovered_at: string | null
  sample_count: number
  status_counts: Record<string, number>
  samples: SampleSummary[]
  nfs_samples: string[]
}

export interface Step {
  step_order: number
  name: string
  status: string
  retries: number
  logs: string
  error: string | null
  started_at: string | null
  ended_at: string | null
}

export interface Job {
  job_id: string
  run_id: string
  sample_id: string
  attempt_id: number
  status: string
  error: string | null
  created_at: string
  started_at: string | null
  ended_at: string | null
}

export interface JobDetail extends Job {
  steps: Step[]
  attempt_no: number | null
  attempt_kind: string | null
  catalogue_version: string | null
  notice: string
}

export interface S3Object {
  key: string
  run_id: string
  sample_id: string
  size: number
  checksum: string
  nfs_checksum: string
  attempt_id: number | null
  catalogue_version: string | null
  overwrite_count: number
  first_uploaded_at: string
  uploaded_at: string
}

export interface Scan {
  id: number
  trigger: string
  started_at: string
  finished_at: string | null
  discovered_folders: number
  new_runs: number
  new_samples: number
  changed_versions: number
  skipped_folders: number
  unchanged_samples: number
  failed_operations: number
  jobs_submitted: number
  details: string[]
}

export interface SequencerStatus {
  scanning: boolean
  auto_scan_enabled: boolean
  interval_seconds: number
  next_scan_at: string | null
  last_scan: Scan | null
  scans_total: number
}

export interface Settings {
  scan_interval_seconds: number
  auto_scan_enabled: boolean
  auto_process: boolean
  s3_versioning_enabled: boolean
  warning_policy: string
}

export interface Check {
  metric: string
  value: number
  threshold: string
  status: string
}

export interface QcResult {
  id: number
  attempt_id: number
  attempt_no: number | null
  sample_id: string
  run_id: string
  catalogue_version: string
  overall: string
  reasons: string[]
  is_latest_attempt: boolean
  created_at: string
  interop: {
    tool: string
    status: string
    metrics: Record<string, number>
    checks: Check[]
    lanes: Record<string, number>[]
  }
  fastqc: {
    tool: string
    status: string
    basic_statistics: { total_reads: number; sequence_length: string; gc_pct: number }
    per_base_quality: { position: number; median: number; lower_quartile: number; upper_quartile: number }[]
    modules: Record<string, Record<string, unknown> & { status: string }>
  }
}

export interface Attempt {
  id: number
  attempt_no: number
  kind: string
  catalogue_version: string
  status: string
  qc_status: string | null
  accepted: boolean
  triggered_by: string
  job_id: string | null
  error: string | null
  created_at: string
  started_at: string | null
  ended_at: string | null
}

export interface CatalogueVersion {
  id: number
  version: string
  source: string
  content: Record<string, unknown>
  created_at: string
}

export interface History {
  sample_id: string
  run_id: string
  current_status: string
  catalogue_version: string
  processed_version: string | null
  catalogue_versions: CatalogueVersion[]
  attempts: Attempt[]
  s3_objects: { key: string; checksum: string; overwrite_count: number; uploaded_at: string; attempt_id: number | null; catalogue_version: string | null }[]
  events: { ts: string; level: string; source: string; message: string }[]
}

export interface SearchHit {
  sample_id: string
  run_id: string
  catalogue_version: string
  processing_status: string
  quality_status: string
  created_at: string
  indexed_at: string
  document: Record<string, unknown>
}

export interface LogEntry {
  id: number
  ts: string
  level: string
  source: string
  message: string
  run_id: string | null
  sample_id: string | null
}

export interface Summary {
  kpis: Record<string, number>
  charts: {
    ingestion_activity: { date: string; attempts: number }[]
    pass_fail: { name: string; value: number }[]
    processing_status: { name: string; value: number }[]
    catalogue_versions: { name: string; value: number }[]
  }
  recent_activity: LogEntry[]
}

export interface DownstreamItem {
  sample_id: string
  run_id: string
  catalogue_version: string
  quality_status: string
  status: string
  eligible: boolean
  reason: string
  last_processed_at: string | null
}

export interface DownstreamFetch {
  sample_id: string
  run_id: string
  catalogue_version: string
  processed_version: string
  quality_status: string
  s3_destination: string
  metadata: Record<string, unknown>
  files: { key: string; path: string; s3_uri: string; size: number; checksum: string; download_url: string }[]
}

export interface NfsRun {
  run_id: string
  complete: boolean
  samples: { sample_id: string; files: { path: string; size: number }[] }[]
}

export interface IntegrityRow {
  key: string
  status: string
  recorded_nfs_sha256: string
  current_nfs_sha256: string | null
}
