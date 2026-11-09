import { createContext, ReactNode, useCallback, useContext, useState } from 'react'

// ---------- formatting ----------
export function fmtTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' })
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function duration(a: string | null, b: string | null): string {
  if (!a) return '—'
  const ms = (b ? new Date(b).getTime() : Date.now()) - new Date(a).getTime()
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

// ---------- badges ----------
const TONES: Record<string, string> = {
  PASSED: 'bg-emerald-100 text-emerald-800', PASS: 'bg-emerald-100 text-emerald-800', SUCCEEDED: 'bg-emerald-100 text-emerald-800',
  UNCHANGED: 'bg-emerald-100 text-emerald-800', INFO: 'bg-slate-100 text-slate-700', NOT_RUN: 'bg-slate-100 text-slate-600',
  FAILED: 'bg-red-100 text-red-800', FAIL: 'bg-red-100 text-red-800', ERROR: 'bg-red-100 text-red-800', MISSING: 'bg-red-100 text-red-800',
  INTERRUPTED: 'bg-red-100 text-red-800',
  WARN: 'bg-amber-100 text-amber-800', RERUN_REQUIRED: 'bg-amber-100 text-amber-800', STALE: 'bg-amber-100 text-amber-800',
  MODIFIED: 'bg-amber-100 text-amber-800', INCOMPLETE: 'bg-amber-100 text-amber-800', SUPERSEDED: 'bg-amber-100 text-amber-800',
  INGESTING: 'bg-blue-100 text-blue-800', INGESTED: 'bg-blue-100 text-blue-800', PROCESSING: 'bg-blue-100 text-blue-800',
  QC_PENDING: 'bg-blue-100 text-blue-800', RUNNING: 'bg-blue-100 text-blue-800', PENDING: 'bg-blue-100 text-blue-800',
  QUEUED: 'bg-blue-100 text-blue-800', DISCOVERED: 'bg-indigo-100 text-indigo-800', NOT_DISCOVERED: 'bg-slate-200 text-slate-700',
  SKIPPED: 'bg-slate-200 text-slate-600', BASE_RECALL: 'bg-violet-100 text-violet-800', INITIAL: 'bg-slate-100 text-slate-700',
  RETRY: 'bg-orange-100 text-orange-800',
}

export function Badge({ value }: { value: string | null | undefined }) {
  const v = value ?? '—'
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${TONES[v] ?? 'bg-slate-100 text-slate-700'}`}>
      {v.replace(/_/g, ' ')}
    </span>
  )
}

// ---------- layout ----------
export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  )
}

export function Kpi({ label, value, tone = 'text-slate-900' }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${tone}`}>{value}</div>
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>
}

export function ErrorBanner({ error }: { error: string | null }) {
  if (!error) return null
  return <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">{error}</div>
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  )
}
export const Th = ({ children }: { children?: ReactNode }) => (
  <th className="whitespace-nowrap border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{children}</th>
)
export const Td = ({ children, className = '' }: { children?: ReactNode; className?: string }) => (
  <td className={`border-b border-slate-100 px-3 py-2 align-top text-slate-700 ${className}`}>{children}</td>
)

type BtnProps = { onClick?: () => void; children: ReactNode; variant?: 'primary' | 'secondary' | 'danger'; disabled?: boolean; type?: 'button' | 'submit'; title?: string }
export function Button({ onClick, children, variant = 'primary', disabled, type = 'button', title }: BtnProps) {
  const styles = {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700',
    secondary: 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  }[variant]
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}>
      {children}
    </button>
  )
}

export const inputCls = 'rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
      {label}
      {children}
    </label>
  )
}

// ---------- toasts ----------
type Toast = { id: number; text: string; kind: 'ok' | 'error' }
const ToastCtx = createContext<(text: string, kind?: 'ok' | 'error') => void>(() => undefined)
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const notify = useCallback((text: string, kind: 'ok' | 'error' = 'ok') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, text, kind }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000)
  }, [])
  return (
    <ToastCtx.Provider value={notify}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={`rounded-lg px-4 py-2 text-sm shadow-lg ${t.kind === 'ok' ? 'bg-slate-900 text-white' : 'bg-red-600 text-white'}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

/** Runs an async action, toasting success/failure. */
export function useAction() {
  const notify = useToast()
  return useCallback(
    async <T,>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> => {
      try {
        const r = await fn()
        if (okMsg) notify(okMsg, 'ok')
        return r
      } catch (e) {
        notify(e instanceof Error ? e.message : String(e), 'error')
        return undefined
      }
    },
    [notify],
  )
}
