import { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';

export default function EditorTab() {
  const [content, setContent] = useState('// Open a file or start typing\n');
  const [filename, setFilename] = useState('untitled.txt');
  const [language, setLanguage] = useState('plaintext');
  const [extensions, setExtensions] = useState<string[]>([]);
  const [targetFormat, setTargetFormat] = useState('');
  const [converting, setConverting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch('/api/formats')
      .then((r) => r.json())
      .then((data) => {
        setExtensions(data.extensions);
      })
      .catch(() => {});
  }, []);

  const detectAndSet = async (name: string, text: string) => {
    setFilename(name);
    setContent(text);
    try {
      const res = await fetch(`/api/formats/detect?filename=${encodeURIComponent(name)}`);
      const data = await res.json();
      setLanguage(data.monaco_language);
      setTargetFormat(data.conversion_targets[0] || '');
    } catch {
      setLanguage('plaintext');
    }
  };

  const openFile = (f: File) => {
    const reader = new FileReader();
    reader.onload = () => detectAndSet(f.name, reader.result as string);
    reader.readAsText(f);
  };

  const download = () => {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const switchFormat = async (newExt: string) => {
    if (!newExt) return;
    setConverting(true);
    const currentExt = filename.includes('.') ? filename.split('.').pop()! : 'txt';
    try {
      const res = await fetch('/api/convert/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          source_ext: currentExt,
          target_ext: newExt,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      const baseName = filename.replace(/\.[^.]+$/, '');
      await detectAndSet(`${baseName}.${newExt}`, data.content);
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Format switch failed');
    } finally {
      setConverting(false);
    }
  };

  const changeLanguage = (lang: string) => {
    setLanguage(lang);
  };

  const [availableTargets, setAvailableTargets] = useState<string[]>([]);
  useEffect(() => {
    fetch(`/api/formats/detect?filename=${encodeURIComponent(filename)}`)
      .then((r) => r.json())
      .then((d) => setAvailableTargets(d.conversion_targets))
      .catch(() => setAvailableTargets([]));
  }, [filename]);

  return (
    <div>
      <div className="panel">
        <h2>Universal Text & Code Editor</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Syntax-aware editing with Monaco. Switch formats, change language modes, and export files.
          Supports {extensions.length}+ file extensions.
        </p>

        <div className="editor-toolbar">
          <button className="btn" onClick={() => fileInputRef.current?.click()}>
            Open File
          </button>
          <input
            ref={fileInputRef}
            type="file"
            hidden
            onChange={(e) => e.target.files?.[0] && openFile(e.target.files[0])}
          />
          <button className="btn btn-success" onClick={download}>
            Download / Export
          </button>

          <input
            type="text"
            value={filename}
            onChange={(e) => {
              setFilename(e.target.value);
              fetch(`/api/formats/detect?filename=${encodeURIComponent(e.target.value)}`)
                .then((r) => r.json())
                .then((d) => setLanguage(d.monaco_language))
                .catch(() => {});
            }}
            style={{ width: '200px' }}
            placeholder="filename.ext"
          />

          <select
            value={language}
            onChange={(e) => changeLanguage(e.target.value)}
            style={{ width: 'auto' }}
          >
            {[
              'plaintext', 'python', 'javascript', 'typescript', 'java', 'c', 'cpp',
              'csharp', 'go', 'rust', 'ruby', 'php', 'swift', 'kotlin', 'html', 'css',
              'scss', 'json', 'yaml', 'xml', 'markdown', 'sql', 'shell', 'dockerfile',
              'powershell', 'lua', 'dart', 'elixir', 'haskell', 'fsharp', 'verilog',
              'toml', 'ini', 'latex', 'graphql', 'solidity',
            ].map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>

          {availableTargets.length > 0 && (
            <>
              <select
                value={targetFormat}
                onChange={(e) => setTargetFormat(e.target.value)}
                style={{ width: 'auto' }}
              >
                {availableTargets.map((t) => (
                  <option key={t} value={t}>.{t}</option>
                ))}
              </select>
              <button
                className="btn btn-primary"
                onClick={() => switchFormat(targetFormat)}
                disabled={converting || !targetFormat}
              >
                {converting ? 'Switching...' : 'Switch Format'}
              </button>
            </>
          )}
        </div>

        <div
          className="editor-container"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files[0];
            if (f) openFile(f);
          }}
        >
          <Editor
            height="500px"
            language={language}
            value={content}
            onChange={(v) => setContent(v || '')}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              wordWrap: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
            }}
          />
        </div>
      </div>
    </div>
  );
}
