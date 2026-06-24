import { useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';

interface FormatInfo {
  extension: string;
  conversion_targets: string[];
  monaco_language: string;
  is_binary: boolean;
}

export default function EditorTab() {
  const [content, setContent] = useState('// Open a file or start typing\n');
  const [filename, setFilename] = useState('untitled.txt');
  const [language, setLanguage] = useState('plaintext');
  const [monacoLanguages, setMonacoLanguages] = useState<string[]>([]);
  const [availableTargets, setAvailableTargets] = useState<string[]>([]);
  const [targetFormat, setTargetFormat] = useState('');
  const [converting, setConverting] = useState(false);
  const [isBinary, setIsBinary] = useState(false);
  const [unsaved, setUnsaved] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load Monaco language list from the backend (driven by formats.json)
  useEffect(() => {
    fetch('/api/formats')
      .then((r) => r.json())
      .then((data) => {
        const langs = Object.values(data.monaco_languages as Record<string, string>);
        const unique = Array.from(new Set(['plaintext', ...langs])).sort();
        setMonacoLanguages(unique);
      })
      .catch(() => {
        setMonacoLanguages([
          'plaintext','python','javascript','typescript','java','c','cpp','csharp',
          'go','rust','ruby','php','swift','kotlin','html','css','scss','json',
          'yaml','xml','markdown','sql','shell','dockerfile','powershell','lua',
          'dart','elixir','haskell','fsharp','graphql','solidity','ini','toml','latex',
        ]);
      });
  }, []);

  const detectAndSet = async (name: string, text: string) => {
    setFilename(name);
    setContent(text);
    setUnsaved(false);
    try {
      const res = await fetch(`/api/formats/detect?filename=${encodeURIComponent(name)}`);
      const data: FormatInfo = await res.json();
      setLanguage(data.monaco_language);
      setAvailableTargets(data.conversion_targets);
      setTargetFormat(data.conversion_targets[0] || '');
      setIsBinary(data.is_binary);
    } catch {
      setLanguage('plaintext');
    }
  };

  const openFile = (f: File) => {
    const ext = f.name.includes('.') ? f.name.split('.').pop()!.toLowerCase() : 'bin';
    const BINARY_EXTS = new Set([
      'png','jpg','jpeg','gif','bmp','webp','ico','tiff','pdf',
      'mp3','wav','flac','ogg','mp4','avi','mkv','mov','wasm','bin','exe','dll','so','dylib',
    ]);
    if (BINARY_EXTS.has(ext)) {
      const reader = new FileReader();
      reader.onload = () => {
        const buf = reader.result as ArrayBuffer;
        const bytes = new Uint8Array(buf);
        const hex = Array.from(bytes.slice(0, 512))
          .map((b) => b.toString(16).padStart(2, '0'))
          .join(' ');
        detectAndSet(
          f.name,
          `// Binary file: ${f.name} (${(f.size / 1024).toFixed(1)} KB)\n// Hex preview (first 512 bytes):\n// ${hex}\n\n// Binary files cannot be edited as text.\n// Use the File Converter tab to convert this file to a text format.`,
        );
      };
      reader.readAsArrayBuffer(f);
    } else {
      const reader = new FileReader();
      reader.onload = () => detectAndSet(f.name, reader.result as string);
      reader.readAsText(f);
    }
  };

  const download = () => {
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    setUnsaved(false);
  };

  const switchFormat = async (newExt: string) => {
    if (!newExt) return;
    if (unsaved) {
      const ok = window.confirm(
        `You have unsaved changes.\nSwitch format to .${newExt} anyway? Content will be converted.`
      );
      if (!ok) return;
    }
    setConverting(true);
    const currentExt = filename.includes('.') ? filename.split('.').pop()! : 'txt';
    try {
      const res = await fetch('/api/convert/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, source_ext: currentExt, target_ext: newExt, filename }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      if (data.binary) {
        alert(`Cannot display binary format (.${newExt}) in the editor. Use the File Converter tab instead.`);
        return;
      }
      const baseName = filename.replace(/\.[^.]+$/, '');
      await detectAndSet(`${baseName}.${newExt}`, data.content);
    } catch (e) {
      alert(e instanceof Error ? e.message : 'Format switch failed');
    } finally {
      setConverting(false);
    }
  };

  return (
    <div>
      <div className="panel">
        <h2>Universal Text & Code Editor</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '1rem' }}>
          Syntax-aware Monaco editor. Open any text or code file, switch formats, change syntax
          highlighting, and download the result.
          {isBinary && (
            <strong style={{ color: 'var(--warning)' }}> Binary file — editing is limited.</strong>
          )}
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
            {unsaved ? '⬇ Download*' : '⬇ Download'}
          </button>

          <input
            type="text"
            value={filename}
            onChange={(e) => {
              setFilename(e.target.value);
              setUnsaved(true);
              fetch(`/api/formats/detect?filename=${encodeURIComponent(e.target.value)}`)
                .then((r) => r.json())
                .then((d) => setLanguage(d.monaco_language))
                .catch(() => {});
            }}
            style={{ width: '200px' }}
            placeholder="filename.ext"
          />

          {/* Language selector driven by backend monaco_languages map */}
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            style={{ width: 'auto' }}
            title="Syntax highlighting language"
          >
            {monacoLanguages.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>

          {availableTargets.length > 0 && (
            <>
              <select
                value={targetFormat}
                onChange={(e) => setTargetFormat(e.target.value)}
                style={{ width: 'auto' }}
                title="Convert to format"
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
                {converting ? 'Converting…' : 'Switch Format'}
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
            height="520px"
            language={language}
            value={content}
            onChange={(v) => {
              setContent(v || '');
              setUnsaved(true);
            }}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 14,
              wordWrap: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
              readOnly: isBinary,
            }}
          />
        </div>
      </div>
    </div>
  );
}
