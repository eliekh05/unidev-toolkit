import { useCallback, useRef, useState } from 'react';

interface FormatInfo {
  extension: string;
  category: string | null;
  conversion_targets: string[];
  monaco_language: string;
  is_binary: boolean;
}

interface ConvertState {
  blob: Blob;
  ext: string;
  name: string;
}

export default function ConverterTab() {
  const [file, setFile] = useState<File | null>(null);
  const [formatInfo, setFormatInfo] = useState<FormatInfo | null>(null);
  const [targetExt, setTargetExt] = useState('');
  const [converting, setConverting] = useState(false);
  const [error, setError] = useState('');
  const [previewText, setPreviewText] = useState('');
  const [previewImgUrl, setPreviewImgUrl] = useState('');
  const [lastOutput, setLastOutput] = useState<ConvertState | null>(null);
  const [ffmpegWarning, setFfmpegWarning] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const IMAGE_EXTS = new Set(['png','jpg','jpeg','gif','bmp','webp','ico','tiff','tif','ppm','pgm','pbm']);
  const AUDIO_VIDEO = new Set(['mp3','wav','flac','ogg','oga','aac','m4a','wma','aiff','aif','opus','amr',
    'mp4','avi','mkv','mov','wmv','flv','webm','m4v','mpeg','mpg','3gp','ogv','ts']);

  const detectFile = async (f: File) => {
    setFile(f);
    setError('');
    setPreviewText('');
    setPreviewImgUrl('');
    setLastOutput(null);
    setFfmpegWarning('');
    try {
      const res = await fetch(`/api/formats/detect?filename=${encodeURIComponent(f.name)}`);
      const data: FormatInfo = await res.json();
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

  const showPreview = async (blob: Blob, ext: string) => {
    setPreviewImgUrl('');
    setPreviewText('');
    if (IMAGE_EXTS.has(ext)) {
      setPreviewImgUrl(URL.createObjectURL(blob));
      return;
    }
    const TEXT_EXTS = new Set([
      'txt','md','html','htm','json','xml','yaml','yml','csv','tsv',
      'css','js','ts','py','swift','c','cpp','go','rs','java','sh',
      'sql','toml','ini','conf','svg','markdown',
    ]);
    if (TEXT_EXTS.has(ext)) {
      setPreviewText(await blob.text());
    } else {
      setPreviewText(`Binary output (${(blob.size / 1024).toFixed(1)} KB) — click Download to save`);
    }
  };

  const doConvert = async (srcBlob: Blob, srcExt: string, srcName: string, dstExt: string): Promise<Blob | null> => {
    if (AUDIO_VIDEO.has(srcExt) && AUDIO_VIDEO.has(dstExt)) {
      setFfmpegWarning('Audio/video conversion requires ffmpeg on the server. If this fails, ffmpeg may not be installed.');
    }
    const form = new FormData();
    form.append('file', new File([srcBlob], srcName, { type: srcBlob.type || 'application/octet-stream' }));
    form.append('target_ext', dstExt);
    const res = await fetch('/api/convert', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Conversion failed');
    }
    return res.blob();
  };

  const downloadBlob = (blob: Blob, name: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  const convert = async () => {
    if (!file || !targetExt || !formatInfo) return;
    setConverting(true);
    setError('');
    setFfmpegWarning('');
    try {
      const blob = await doConvert(file, formatInfo.extension, file.name, targetExt);
      if (!blob) return;
      const outName = `converted.${targetExt}`;
      setLastOutput({ blob, ext: targetExt, name: outName });
      await showPreview(blob, targetExt);
      downloadBlob(blob, outName);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Conversion failed');
    } finally {
      setConverting(false);
    }
  };

  const reverseConvert = async () => {
    if (!lastOutput || !formatInfo) return;
    setConverting(true);
    setError('');
    try {
      const blob = await doConvert(lastOutput.blob, lastOutput.ext, lastOutput.name, formatInfo.extension);
      if (!blob) return;
      const outName = `reversed.${formatInfo.extension}`;
      setLastOutput({ blob, ext: formatInfo.extension, name: outName });
      await showPreview(blob, formatInfo.extension);
      downloadBlob(blob, outName);
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
          Bidirectional conversion with automatic type detection. Supports code, images, audio,
          video, documents, and data formats. Audio/video conversion requires ffmpeg on the server.
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
            <p><strong>{file.name}</strong> ({(file.size / 1024).toFixed(1)} KB)</p>
          ) : (
            <p>Drop a file here or click to upload</p>
          )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {ffmpegWarning && <div className="alert alert-warning">{ffmpegWarning}</div>}

      {formatInfo && (
        <>
          <div className="panel">
            <h2>Detected Format</h2>
            <p>
              <span className="tag active">.{formatInfo.extension}</span>
              {formatInfo.category && <span className="tag">{formatInfo.category}</span>}
              {formatInfo.is_binary && <span className="tag">binary</span>}
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
                    style={{ cursor: 'pointer', border: 'none' }}
                    onClick={() => setTargetExt(ext)}
                  >
                    .{ext}
                  </button>
                ))
              )}
            </div>
            <div className="form-row">
              <button
                className="btn btn-primary"
                onClick={convert}
                disabled={converting || !targetExt}
              >
                {converting ? 'Converting…' : `Convert .${formatInfo.extension} → .${targetExt}`}
              </button>
              {lastOutput && (
                <button className="btn" onClick={reverseConvert} disabled={converting}>
                  ↩ Reverse: .{lastOutput.ext} → .{formatInfo.extension}
                </button>
              )}
              {lastOutput && (
                <button
                  className="btn btn-success"
                  onClick={() => downloadBlob(lastOutput.blob, lastOutput.name)}
                >
                  Download .{lastOutput.ext}
                </button>
              )}
            </div>
          </div>
        </>
      )}

      {previewImgUrl && (
        <div className="panel">
          <h2>Preview</h2>
          <img
            src={previewImgUrl}
            alt="converted output"
            style={{ maxWidth: '100%', maxHeight: '400px', borderRadius: '6px', display: 'block' }}
          />
        </div>
      )}

      {previewText && (
        <div className="panel">
          <h2>Preview</h2>
          <pre className="log-output" style={{ maxHeight: '400px' }}>{previewText}</pre>
        </div>
      )}
    </div>
  );
}
