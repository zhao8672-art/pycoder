import React, { useEffect, useRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { getWsUrl, getApiKey } from '../services/config';
import { WSConnectionManager } from '../services/websocket';

export const TerminalPanel: React.FC = () => {
  const terminalRef = useRef<HTMLDivElement>(null);
  const termInstance = useRef<Terminal | null>(null);
  const mgrRef = useRef<WSConnectionManager | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      cursorStyle: 'block',
      fontSize: 12,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
      theme: {
        background: '#1a1b2e', foreground: '#c0caf5', cursor: '#7aa2f7',
        selectionBackground: '#3b4261', black: '#1d202f', red: '#f7768e',
        green: '#9ece6a', yellow: '#e0af68', blue: '#7aa2f7',
        magenta: '#bb9af7', cyan: '#7dcfff', white: '#c0caf5',
      },
      allowTransparency: true,
      rows: 15,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    fitAddonRef.current = fitAddon;
    term.open(terminalRef.current);
    fitAddon.fit();
    termInstance.current = term;

    const onDataDisposable = term.onData((data) => {
      mgrRef.current?.sendJson({ type: 'command', data });
    });

    // Phase 1 #2: Terminal keyboard shortcuts
    term.attachCustomKeyEventHandler((e: KeyboardEvent) => {
      const isCtrl = e.ctrlKey && !e.altKey && !e.metaKey;
      const isShiftCtrl = e.ctrlKey && e.shiftKey;
      if (isCtrl && e.key === 'c' && !term.hasSelection()) {
        mgrRef.current?.sendJson({ type: 'break' });  // Ctrl+C → SIGINT
        return false;
      }
      if (isCtrl && e.key === 'v') {
        navigator.clipboard.readText().then(t => { mgrRef.current?.sendJson({ type: 'command', data: t }); });
        return false;
      }
      if (isCtrl && e.key === 'l') { term.clear(); return false; }
      if (isCtrl && e.key === 'u') { mgrRef.current?.sendJson({ type: 'command', data: '\x15' }); return false; }
      if (isShiftCtrl && (e.key === 'c' || e.key === 'C')) {
        const sel = term.getSelection();
        if (sel) navigator.clipboard.writeText(sel);
        return false;
      }
      return true;
    });

    const init = async () => {
      const [url, apiKey] = await Promise.all([getWsUrl('/ws/terminal'), getApiKey()]);
      const wsUrl = apiKey ? `${url}?api_key=${encodeURIComponent(apiKey)}` : url;
      const mgr = new WSConnectionManager(wsUrl);
      mgrRef.current = mgr;

      mgr.onMessage((msg) => {
        if (msg.type === 'output') term.write(msg.data);
        else if (msg.type === 'connected') term.write('\r\nShell: ' + msg.shell + '\r\n');
        else if (msg.type === 'exit') term.write('\r\n\x1b[31m[终端退出，代码: ' + msg.code + ']\x1b[0m\r\n');
        else if (msg.type === 'error') term.write('\r\n\x1b[31m[错误: ' + msg.message + ']\x1b[0m\r\n');
      });

      mgr.onStatusChange((s) => {
        if (s.connected) term.write('\r\n\x1b[32m[终端已连接]\x1b[0m\r\n');
      });

      mgr.connect();
    };
    init();

    const handleResize = () => {
      try { fitAddon.fit(); } catch { /* ignore */ }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      onDataDisposable.dispose();
      mgrRef.current?.disconnect();
      term.dispose();
    };
  }, []);

  return (
    <div className="terminal-panel">
      <div ref={terminalRef} className="terminal-container" />
    </div>
  );
};
