import { NavLink, Route, Routes } from 'react-router-dom'
import { ToastProvider } from './components/ui'
import Downstream from './pages/Downstream'
import Logs from './pages/Logs'
import MetadataSearch from './pages/MetadataSearch'
import NfsExplorer from './pages/NfsExplorer'
import Overview from './pages/Overview'
import QualityControl from './pages/QualityControl'
import Reruns from './pages/Reruns'
import Runs from './pages/Runs'
import S3Explorer from './pages/S3Explorer'
import Settings from './pages/Settings'
import Workflows from './pages/Workflows'

const NAV = [
  { to: '/', label: 'Overview', icon: '▦' },
  { to: '/runs', label: 'Sequencing Runs', icon: '≋' },
  { to: '/nfs', label: 'NFS Explorer', icon: '🗀' },
  { to: '/s3', label: 'S3 Explorer', icon: '▤' },
  { to: '/search', label: 'Metadata Search', icon: '⌕' },
  { to: '/workflows', label: 'Workflow Executions', icon: '⇉' },
  { to: '/qc', label: 'Quality Control', icon: '✓' },
  { to: '/reruns', label: 'Base Recall / Reruns', icon: '↻' },
  { to: '/downstream', label: 'Downstream Applications', icon: '⇲' },
  { to: '/logs', label: 'System Logs', icon: '☰' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]

export default function App() {
  return (
    <ToastProvider>
      <div className="flex h-full">
        <aside className="flex w-60 shrink-0 flex-col bg-slate-900 text-slate-300">
          <div className="border-b border-slate-800 px-4 py-4">
            <div className="text-sm font-bold tracking-wide text-white">SciData Platform</div>
            <div className="text-[11px] text-slate-400">Ingestion &amp; Workflow Orchestration</div>
          </div>
          <nav className="flex-1 overflow-y-auto py-2">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2 text-sm transition ${isActive ? 'border-l-2 border-indigo-400 bg-slate-800 font-medium text-white' : 'border-l-2 border-transparent hover:bg-slate-800/60 hover:text-white'}`}>
                <span className="w-4 text-center text-slate-400">{n.icon}</span>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="border-t border-slate-800 px-4 py-3 text-[11px] leading-snug text-slate-500">
            100% local simulation. No AWS services are used: NFS/S3 are folders, DynamoDB/OpenSearch are SQLite.
          </div>
        </aside>
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-1.5 text-xs text-amber-800">
            Simulation mode — Batch, miniWDL, InterOp and FastQC are local simulators, not the real tools.
          </div>
          <div className="mx-auto max-w-7xl p-6">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/runs" element={<Runs />} />
              <Route path="/nfs" element={<NfsExplorer />} />
              <Route path="/s3" element={<S3Explorer />} />
              <Route path="/search" element={<MetadataSearch />} />
              <Route path="/workflows" element={<Workflows />} />
              <Route path="/qc" element={<QualityControl />} />
              <Route path="/reruns" element={<Reruns />} />
              <Route path="/downstream" element={<Downstream />} />
              <Route path="/logs" element={<Logs />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </main>
      </div>
    </ToastProvider>
  )
}
