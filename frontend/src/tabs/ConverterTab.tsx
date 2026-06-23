import { useCallback, useRef, useState } from 'react';

interface FormatInfo {
  extension: string;
  category: string | null;
  conversion_targets: string[];
  monaco_language: string;
}

export default function ConverterTab() {
  const [file, setFile] = useState<File | null>(null);
  const [formatInfo, setFormatInfo] = useState<FormatInfo | null>(null);
  const [targetExt, setTargetExt] = useState('');
  const [converting, setConverting] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState('');
  const [lastOutputBlob, setLastOutputBlob] = useState<Blob | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const detectFile = async (f: File) => {
    setFile(f);
    setError('');
    setPreview('');
    setLastOutputBlob(null);
    try {
      const res = await fetch(`/api/formats/detect?filename=${encodeURIComponent(f.name)}`);
      const data = await res.json();
      setFormatInfo(data);
      setTargetExt(data.conversion_targets[0] || '');
    } catch {
      setError('Failed to detect file type');
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.currentTarget.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f) detectFile(f);
  }, []);

  const convert = async () => {
    if (!file || !targetExt) return;
    setConverting(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('target_ext', targetExt);

      const res = await fetch('/api/convert', { method: 'POST', body: form });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Conversion failed');
      }

      const blob = await res.blob();
      setLastOutputBlob(blob);
      const textTypes = ['txt', 'md', 'html', 'json', 'xml', 'yaml', 'yml', 'csv', 'tsv', 'css', 'js', 'py', 'swift', 'c', 'cpp', 'go', 'rs', 'java', 'ts'];
      if (textTypes.includes(targetExt)) {
        setPreview(await blob.text());
      } else {
        setPreview(`[Binary output: ${blob.size} bytes — use Download]`);
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `converted.${targetExt}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Conversion failed');
    } finally {
      setConverting(false);
    }
  };

  const reverseConvert = async () => {
    if (!formatInfo || !targetExt || !lastOutputBlob) return;
    setConverting(true);
    setError('');
    try {
      const form = new FormData();
      form.append(
        'file',
        new File([lastOutputBlob], `converted.${targetExt}`, { type: lastOutputBlob.type || 'application/octet-stream' }),
      );
      form.append('target_ext', formatInfo.extension);

      const res = await fetch('/api/convert', { method: 'POST', body: form });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Reverse conversion failed');
      }
      const blob = await res.blob();
      const textTypes = ['txt', 'md', 'html', 'json', 'xml', 'yaml', 'yml', 'csv', 'tsv', 'css', 'js', 'py'];
      if (textTypes.includes(formatInfo.extension)) {
        setPreview(await blob.text());
      } else {
        setPreview(`[Binary output: ${blob.size} bytes]`);
      }
      setLastOutputBlob(blob);

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `reversed.${formatInfo.extension}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reverse conversion failed');
    } finally {
      setConverting(false);
    }
  };

  return (
    <div>
      <div className="panel">
        <h2>File Converter</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Bidirectional conversion with automatic type detection. Supports code, images, audio, video,
          documents, and data formats.
        </p>

        <div
          className="drop-zone"
          onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('dragover'); }}
          onDragLeave={(e) => e.currentTarget.classList.remove('dragover')}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            hidden
            onChange={(e) => e.target.files?.[0] && detectFile(e.target.files[0])}
          />
          {file ? (
            <p>
              <strong>{file.name}</strong> ({(file.size / 1024).toFixed(1)} KB)
            </p>
          ) : (
            <p>Drop a file here or click to upload</p>
          )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {formatInfo && (
        <>
          <div className="panel">
            <h2>Detected Format</h2>
            <p>
              <span className="tag active">.{formatInfo.extension}</span>
              {formatInfo.category && <span className="tag">{formatInfo.category}</span>}
            </p>
          </div>

          <div className="panel">
            <h2>Convert To</h2>
            <div style={{ marginBottom: '1rem' }}>
              {formatInfo.conversion_targets.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)' }}>No conversion targets available for this format.</p>
              ) : (
                formatInfo.conversion_targets.map((ext) => (
                  <button
                    key={ext}
                    className={`tag ${targetExt === ext ? 'active' : ''}`}
                    onClick={() => setTargetExt(ext)}
                  >
                    .{ext}
                  </button>
                ))
              )}
            </div>

            <div className="form-row">
              <button className="btn btn-primary" onClick={convert} disabled={converting || !targetExt}>
                {converting ? 'Converting...' : `Convert .${formatInfo.extension} ? .${targetExt}`}
              </button>
              {lastOutputBlob && (
                <button className="btn" onClick={reverseConvert} disabled={converting}>
                  Reverse: .{targetExt} ? .{formatInfo.extension}
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {preview && (
        <div className="panel">
          <h2>Preview</h2>
          <pre className="log-output" style={{ maxHeight: '400px' }}>{preview}</pre>
        </div>
      )}
    </div>
  );
}
