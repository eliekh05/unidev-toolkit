import { useEffect, useRef } from 'react';
import { Terminal as XTerm } from 'xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import 'xterm/css/xterm.css';

function getWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/terminal`;
}

export default function Terminal() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new XTerm({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'SF Mono', 'Fira Code', Consolas, monospace",
      theme: {
        background: '#0a0e14',
        foreground: '#b3b1ad',
        cursor: '#ffcc66',
        selectionBackground: '#3d3d3d',
        black: '#0a0e14',
        red: '#ff3333',
        green: '#b8cc52',
        yellow: '#ffcc66',
        blue: '#66d9ef',
        magenta: '#f92672',
        cyan: '#66d9ef',
        white: '#f8f8f2',
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());
    term.open(containerRef.current);
    fitAddon.fit();

    termRef.current = term;

    term.writeln('\x1b[1;33mUniDev Toolkit Terminal\x1b[0m');
    term.writeln('Shared terminal across all tabs.');
    term.writeln('');

    let ws: WebSocket;
    try {
      ws = new WebSocket(getWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        term.writeln('\x1b[32mConnected.\x1b[0m');
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      };

      ws.onmessage = (ev) => {
        term.write(typeof ev.data === 'string' ? ev.data : '');
      };

      ws.onclose = () => {
        term.writeln('\r\n\x1b[31mDisconnected. Refresh to reconnect.\x1b[0m');
      };

      ws.onerror = () => {
        term.writeln('\r\n\x1b[33mTerminal backend unavailable (PTY may require Linux).\x1b[0m');
        term.writeln('You can still use Build, Convert, and Editor features.');
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data);
        }
      });
    } catch {
      term.writeln('\x1b[33mWebSocket unavailable in this environment.\x1b[0m');
    }

    const handleResize = () => {
      fitAddon.fit();
      if (wsRef.current?.readyState === WebSocket.OPEN && termRef.current) {
        wsRef.current.send(
          JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }),
        );
      }
    };

    const observer = new ResizeObserver(handleResize);
    observer.observe(containerRef.current);
    window.addEventListener('resize', handleResize);

    return () => {
      observer.disconnect();
      window.removeEventListener('resize', handleResize);
      wsRef.current?.close();
      term.dispose();
    };
  }, []);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}
