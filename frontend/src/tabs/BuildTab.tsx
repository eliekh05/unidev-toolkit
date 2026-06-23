import { useRef, useState } from 'react';

type SourceType = 'github' | 'gitlab' | 'upload' | 'local';

interface ProjectInfo {
  type: string;
  framework: string | null;
  platforms: string[];
  pwa: {
    has_pwa: boolean;
    prompt_enable_pwa: boolean;
    missing_fields: string[];
    manifest: Record<string, unknown> | null;
    icons: { src: string; sizes?: string; exists: boolean }[];
  };
}

const TARGETS = [
  { id: 'dmg', label: 'macOS (.dmg)' },
  { id: 'apk', label: 'Android (.apk)' },
  { id: 'ipa', label: 'iOS (.ipa)' },
  { id: 'msix', label: 'Windows (.msix)' },
];

export default function BuildTab() {
  const [sourceType, setSourceType] = useState<SourceType>('github');
  const [url, setUrl] = useState('');
  const [localPath, setLocalPath] = useState('');
  const [uploadId, setUploadId] = useState('');
  const [uploadName, setUploadName] = useState('');
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [availableTargets, setAvailableTargets] = useState<string[]>([]);
  const [selectedTarget, setSelectedTarget] = useState('');
  const [logs, setLogs] = useState('');
  const [downloadUrl, setDownloadUrl] = useState('');
  const [error, setError] = useState('');
  const [showPwaForm, setShowPwaForm] = useState(false);
  const [pwaConfig, setPwaConfig] = useState({
    name: '',
    short_name: '',
    start_url: '/',
    display: 'standalone',
    background_color: '#ffffff',
    theme_color: '#0d1117',
    icons: [{ src: '/icon-192.png', sizes: '192x192', type: 'image/png' }],
  });
  const uploadRef = useRef<HTMLInputElement>(null);

  const handleUpload = async (file: File) => {
    setLoading(true);
    setError('');
    setProject(null);
    setLogs('');
    setDownloadUrl('');
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/api/build/upload', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      setUploadId(data.upload_id);
      setUploadName(file.name);
      setSourceType('upload');
      setProject(data.project);
      setAvailableTargets(data.available_targets);
      setSelectedTarget(data.available_targets[0] || '');
      if (data.project.pwa?.prompt_enable_pwa) setShowPwaForm(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  const analyze = async () => {
    setLoading(true);
    setError('');
    setProject(null);
    setLogs('');
    setDownloadUrl('');
    try {
      const res = await fetch('/api/build/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_type: sourceType,
          url: sourceType === 'github' || sourceType === 'gitlab' ? url : null,
          local_path: sourceType === 'local' ? localPath : null,
          upload_id: sourceType === 'upload' ? uploadId : null,
          token: token || null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Analysis failed');
      setProject(data.project);
      setAvailableTargets(data.available_targets);
      setSelectedTarget(data.available_targets[0] || '');
      if (data.project.pwa?.prompt_enable_pwa) setShowPwaForm(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  };

  const build = async () => {
    if (!selectedTarget) return;
    setBuilding(true);
    setError('');
    setLogs('Build started — see terminal for live output.\n');
    setDownloadUrl('');
    try {
      const res = await fetch('/api/build/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_type: sourceType,
          url: sourceType === 'github' || sourceType === 'gitlab' ? url : null,
          local_path: sourceType === 'local' ? localPath : null,
          upload_id: sourceType === 'upload' ? uploadId : null,
          token: token || null,
          target: selectedTarget,
          pwa_config: showPwaForm ? pwaConfig : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Build failed');
      setLogs(data.logs || '');
      if (data.download_url) setDownloadUrl(data.download_url);
      if (!data.success && data.detail) setError(data.detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed');
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div>
      <div className="panel">
        <h2>Build &amp; Packaging Tool</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Generate .dmg, .apk, .ipa, and .msix from GitHub, GitLab, or an uploaded project archive.
          Detects project structure and PWA assets automatically.
        </p>

        <div className="source-tabs">
          {([
            ['github', 'GitHub'],
            ['gitlab', 'GitLab'],
            ['upload', 'Upload ZIP'],
            ['local', 'Server Path'],
          ] as const).map(([s, label]) => (
            <button
              key={s}
              className={`source-tab ${sourceType === s ? 'active' : ''}`}
              onClick={() => setSourceType(s)}
            >
              {label}
            </button>
          ))}
        </div>

        {sourceType === 'upload' && (
          <div
            className="drop-zone"
            style={{ marginBottom: '1rem' }}
            onClick={() => uploadRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('dragover'); }}
            onDragLeave={(e) => e.currentTarget.classList.remove('dragover')}
            onDrop={(e) => {
              e.preventDefault();
              e.currentTarget.classList.remove('dragover');
              const f = e.dataTransfer.files[0];
              if (f) handleUpload(f);
            }}
          >
            <input
              ref={uploadRef}
              type="file"
              hidden
              accept=".zip,.tar.gz,.tgz"
              onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
            />
            {uploadName ? (
              <p><strong>{uploadName}</strong> uploaded</p>
            ) : (
              <p>Drop a .zip project archive or click to upload</p>
            )}
          </div>
        )}

        {(sourceType === 'github' || sourceType === 'gitlab') && (
          <>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Repository URL</label>
              <input
                type="url"
                placeholder={
                  sourceType === 'github'
                    ? 'https://github.com/user/repo'
                    : 'https://gitlab.com/user/repo'
                }
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Access Token (optional, for private repos)</label>
              <input
                type="password"
                placeholder="ghp_... or glpat-..."
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
            </div>
          </>
        )}

        {sourceType === 'local' && (
          <>
            <div className="alert alert-info" style={{ marginBottom: '0.75rem' }}>
              Server-side path only (local dev). Use Upload ZIP when deployed on Hugging Face Spaces.
            </div>
            <div style={{ marginBottom: '0.75rem' }}>
              <label>Local Project Path</label>
              <input
                type="text"
                placeholder="/path/to/your/project"
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
              />
            </div>
          </>
        )}

        {sourceType !== 'upload' && (
          <button className="btn btn-primary" onClick={analyze} disabled={loading}>
            {loading ? 'Analyzing...' : 'Analyze Project'}
          </button>
        )}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {project && (
        <>
          <div className="panel">
            <h2>Project Detection</h2>
            <div className="grid-2">
              <div>
                <p><strong>Type:</strong> {project.type}</p>
                <p><strong>Framework:</strong> {project.framework || 'Unknown'}</p>
                <p><strong>Platforms:</strong> {project.platforms.join(', ') || 'Not detected'}</p>
              </div>
              <div>
                <p><strong>PWA:</strong> {project.pwa.has_pwa ? 'Detected' : 'Not found'}</p>
                {project.pwa.has_pwa && project.pwa.missing_fields.length > 0 && (
                  <p style={{ color: 'var(--warning)' }}>
                    Missing fields: {project.pwa.missing_fields.join(', ')}
                  </p>
                )}
              </div>
            </div>

            {project.pwa.prompt_enable_pwa && (
              <div className="alert alert-warning" style={{ marginTop: '1rem' }}>
                No PWA configuration detected. Fill in the fields below for better packaging accuracy.
              </div>
            )}
          </div>

          {(showPwaForm || project.pwa.prompt_enable_pwa) && (
            <div className="panel">
              <h2>PWA Configuration</h2>
              <div className="pwa-fields">
                <div>
                  <label>App Name</label>
                  <input
                    value={pwaConfig.name}
                    onChange={(e) => setPwaConfig({ ...pwaConfig, name: e.target.value })}
                    placeholder="My Application"
                  />
                </div>
                <div>
                  <label>Short Name</label>
                  <input
                    value={pwaConfig.short_name}
                    onChange={(e) => setPwaConfig({ ...pwaConfig, short_name: e.target.value })}
                    placeholder="MyApp"
                  />
                </div>
                <div>
                  <label>Start URL</label>
                  <input
                    value={pwaConfig.start_url}
                    onChange={(e) => setPwaConfig({ ...pwaConfig, start_url: e.target.value })}
                  />
                </div>
                <div>
                  <label>Display Mode</label>
                  <select
                    value={pwaConfig.display}
                    onChange={(e) => setPwaConfig({ ...pwaConfig, display: e.target.value })}
                  >
                    <option value="standalone">Standalone</option>
                    <option value="fullscreen">Fullscreen</option>
                    <option value="minimal-ui">Minimal UI</option>
                    <option value="browser">Browser</option>
                  </select>
                </div>
                <div>
                  <label>Theme Color</label>
                  <input
                    type="text"
                    value={pwaConfig.theme_color}
                    onChange={(e) => setPwaConfig({ ...pwaConfig, theme_color: e.target.value })}
                  />
                </div>
                <div>
                  <label>Background Color</label>
                  <input
                    type="text"
                    value={pwaConfig.background_color}
                    onChange={(e) => setPwaConfig({ ...pwaConfig, background_color: e.target.value })}
                  />
                </div>
              </div>
            </div>
          )}

          <div className="panel">
            <h2>Select Build Target</h2>
            <div style={{ marginBottom: '1rem' }}>
              {TARGETS.map((t) => {
                const available = availableTargets.includes(t.id);
                return (
                  <button
                    key={t.id}
                    className={`tag ${selectedTarget === t.id ? 'active' : ''}`}
                    style={{ opacity: available ? 1 : 0.4, cursor: available ? 'pointer' : 'not-allowed' }}
                    onClick={() => available && setSelectedTarget(t.id)}
                    disabled={!available}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
            <button
              className="btn btn-success"
              onClick={build}
              disabled={building || !selectedTarget}
            >
              {building ? 'Building...' : `Build .${selectedTarget}`}
            </button>
          </div>
        </>
      )}

      {logs && (
        <div className="panel">
          <h2>Build Log</h2>
          <div className="log-output">{logs}</div>
          {downloadUrl && (
            <a href={downloadUrl} className="btn btn-primary" style={{ marginTop: '1rem', display: 'inline-block', textDecoration: 'none' }}>
              Download Package
            </a>
          )}
        </div>
      )}
    </div>
  );
}
