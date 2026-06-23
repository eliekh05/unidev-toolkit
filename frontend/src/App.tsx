import { useState } from 'react';
import BuildTab from './tabs/BuildTab';
import ConverterTab from './tabs/ConverterTab';
import EditorTab from './tabs/EditorTab';
import Terminal from './components/Terminal';

type Tab = 'build' | 'convert' | 'editor';

const TABS: { id: Tab; label: string }[] = [
  { id: 'build', label: 'Build & Package' },
  { id: 'convert', label: 'File Converter' },
  { id: 'editor', label: 'Universal Editor' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('build');

  return (
    <>
      <header className="app-header">
        <h1>
          UniDev Toolkit
          <span className="badge">No accounts · No tracking · Free</span>
        </h1>
      </header>

      <nav className="tab-bar">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div className="main-layout">
        <main className="content-area">
          {activeTab === 'build' && <BuildTab />}
          {activeTab === 'convert' && <ConverterTab />}
          {activeTab === 'editor' && <EditorTab />}
        </main>

        <aside className="terminal-panel">
          <div className="terminal-header">
            <span>Terminal</span>
            <span style={{ fontWeight: 400, textTransform: 'none' }}>xterm.js</span>
          </div>
          <div className="terminal-container">
            <Terminal />
          </div>
        </aside>
      </div>
    </>
  );
}
