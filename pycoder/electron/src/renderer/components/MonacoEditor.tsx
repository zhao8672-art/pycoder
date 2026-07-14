import React, { useCallback, useRef, useEffect, useState, useMemo } from 'react';
import Editor, { OnMount, loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor';
import { useAppStore } from '../stores/appStore';
import { getLSPClient, LSPDiagnostic } from '../services/lsp-client';
import { registerInlineCompletion } from '../services/inlineCompletion';

// 强制使用本地 Monaco，不走 CDN
loader.config({ monaco });

interface Props {
  filePath: string;
  content: string;
  language: string;
  wsClient?: any | null;
  onCodeReplaced?: (newCode: string) => void;
}

export const MonacoEditor: React.FC<Props> = ({ filePath, content, language, wsClient, onCodeReplaced }) => {
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const lspModelUri = useRef<string>('');
  const lspVersion = useRef(0);

  // ── 内联编辑状态 ──
  const [inlineEditOpen, setInlineEditOpen] = useState(false);
  const [inlineEditInstruction, setInlineEditInstruction] = useState('');
  const [inlineEditLoading, setInlineEditLoading] = useState(false);
  const [inlineEditPreview, setInlineEditPreview] = useState('');
  const [inlineEditError, setInlineEditError] = useState('');
  const inlineEditRequestId = useRef('');
  const inlineEditRef = useRef<HTMLDivElement>(null);

  // ── LSP 初始化 ──
  useEffect(() => {
    const lsp = getLSPClient();
    if (filePath && language === 'python') {
      const uri = `file:///${filePath.replace(/\\/g, '/')}`;
      lspModelUri.current = uri;
      lsp.initialize(uri.replace(/\/[^/]+$/, ''));

      // 监听诊断结果 → 设置 Monaco markers
      const onDiagnostics = (_uri: string, diagnostics: LSPDiagnostic[]) => {
        if (_uri !== uri) return;
        const model = monaco.editor.getModel(monaco.Uri.parse(uri));
        if (!model) return;
        const markers: monaco.editor.IMarkerData[] = diagnostics.map((d) => ({
          severity: d.severity === 'error'
            ? monaco.MarkerSeverity.Error
            : d.severity === 'warning'
              ? monaco.MarkerSeverity.Warning
              : monaco.MarkerSeverity.Info,
          message: d.message,
          startLineNumber: d.line + 1,
          startColumn: d.column + 1,
          endLineNumber: d.endLine + 1,
          endColumn: d.endColumn + 1,
        }));
        monaco.editor.setModelMarkers(model, 'pyright', markers);
      };

      lsp.on('diagnostics', onDiagnostics);

      return () => {
        lsp.removeListener('diagnostics', onDiagnostics);
      };
    }
  }, [filePath, language]);

  const handleMount: OnMount = useCallback((editor) => {
    editorRef.current = editor;

    // Phase 1: Register Inline AI Completion Provider
    try { registerInlineCompletion(monaco); } catch { }

    // 打开文件时通知 LSP
    if (lspModelUri.current) {
      const lsp = getLSPClient();
      lsp.openDocument(lspModelUri.current, editor.getValue());
    }

    editor.updateOptions({
      fontSize: 13,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
      minimap: { enabled: true },
      lineNumbers: 'on',
      renderWhitespace: 'selection',
      tabSize: 4,
      insertSpaces: true,
      bracketPairColorization: { enabled: true },
      autoClosingBrackets: 'always',
      autoClosingQuotes: 'always',
      formatOnPaste: true,
      suggest: { showWords: true },
    });

    // ── 调试器断点 (gutter) ──
    const breakpoints = new Set<number>();
    let breakpointDecorations: string[] = [];

    const renderBreakpoints = () => {
      breakpointDecorations = editor.deltaDecorations(breakpointDecorations, [
        ...[...breakpoints].map((line) => ({
          range: new monaco.Range(line, 1, line, 1),
          options: {
            isWholeLine: true,
            glyphMarginClassName: 'breakpoint-glyph',
            glyphMarginHoverMessage: { value: '断点 (行 ' + line + ')' },
          },
        })),
      ]);
    };

    editor.onMouseDown((e) => {
      if (e.target.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN) {
        const line = e.target.position?.lineNumber;
        if (line) {
          if (breakpoints.has(line)) {
            breakpoints.delete(line);
          } else {
            breakpoints.add(line);
          }
          renderBreakpoints();
        }
      }
    });

    // Ctrl+F5 — 从当前断点启动调试
    editor.addAction({
      id: 'pycoder-debug-start',
      label: 'PyCoder: 启动调试',
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.F5],
      run: async () => {
        if (breakpoints.size === 0) {
          useAppStore.getState().addMessage({
            id: 'dbg-' + Date.now(), role: 'system',
            content: '⚠️ 请在行号左侧点击设置断点后，再按 Ctrl+F5 启动调试',
            timestamp: Date.now(),
          });
          return;
        }
        const value = editor.getValue();
        try {
          const base = 'http://127.0.0.1:8423';
          const r = await fetch(base + '/api/code/exec', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              code: value,
              timeout: 60,
              long_running: true,
            }),
          });
          const data = await r.json();
          const bpList = [...breakpoints].sort((a, b) => a - b);
          useAppStore.getState().addMessage({
            id: 'dbg-result-' + Date.now(), role: 'system',
            content: '🔍 调试结果 (' + bpList.length + ' 个断点)\n'
              + '断点行: ' + bpList.join(', ') + '\n'
              + '输出: ' + (data.stdout || '(空)') + '\n'
              + (data.stderr ? '错误: ' + data.stderr : ''),
            timestamp: Date.now(),
          });
        } catch (e: any) {
          useAppStore.getState().addMessage({
            id: 'dbg-err-' + Date.now(), role: 'system',
            content: '❌ 调试失败: ' + e.message,
            timestamp: Date.now(),
          });
        }
      },
    });

    // ── LSP 补全提供者 ──
    if (language === 'python') {
      const lsp = getLSPClient();
      const disposeProvider = monaco.languages.registerCompletionItemProvider('python', {
        triggerCharacters: ['.', '(', '[', '"', "'"],
        provideCompletionItems: async (model, position) => {
          const word = model.getWordUntilPosition(position);
          const uri = model.uri.toString();
          const items = await lsp.getCompletions(uri, position.lineNumber - 1, position.column - 1);
          return {
            suggestions: items.map((item) => ({
              label: item.label,
              kind: mapCompletionKind(item.kind),
              detail: item.detail,
              insertText: item.insertText,
              range: {
                startLineNumber: position.lineNumber,
                endLineNumber: position.lineNumber,
                startColumn: word.startColumn,
                endColumn: word.endColumn,
              },
            } as monaco.languages.CompletionItem)),
          };
        },
      });

      // ── LSP 悬停提供者 ──
      const disposeHover = monaco.languages.registerHoverProvider('python', {
        provideHover: async (model, position) => {
          const uri = model.uri.toString();
          const text = await lsp.getHover(uri, position.lineNumber - 1, position.column - 1);
          if (!text) return null;
          return { contents: [{ value: text }] };
        },
      });

      // ── LSP 定义提供者 ──
      const disposeDefinition = monaco.languages.registerDefinitionProvider('python', {
        provideDefinition: async (model, position) => {
          const uri = model.uri.toString();
          const result = await lsp.goToDefinition(uri, position.lineNumber - 1, position.column - 1);
          if (!result) return null;
          return {
            uri: monaco.Uri.parse(result.uri),
            range: new monaco.Range(result.line + 1, result.column + 1, result.line + 1, result.column + 1),
          };
        },
      });

      // 清理
      editor.onDidDispose(() => {
        disposeProvider.dispose();
        disposeHover.dispose();
        disposeDefinition.dispose();
      });
    }

    // Ctrl+S 保存（自动调用 black/isort 格式化 Python）
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
      async () => {
        let value = editor.getValue();
        // Python 文件自动格式化
        if (language === 'python' && value.trim()) {
          try {
            const base = 'http://127.0.0.1:8423';
            const r = await fetch(base + '/api/format', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ code: value, style: 'black' }),
            });
            const data = await r.json();
            if (data?.success && data.formatted) {
              value = data.formatted;
              editor.setValue(value);
            }
          } catch { /* 格式化失败，仍尝试保存原始内容 */ }
        }
        if (window.electronAPI) {
          try {
            const result = await window.electronAPI.saveFile(filePath, value);
            if (result?.success) {
              useAppStore.getState().updateTabContent(
                useAppStore.getState().activeTabId || '',
                value,
              );
            }
          } catch { /* 静默 */ }
        }
      },
    );

    // Ctrl+Shift+O — 符号大纲
    editor.addAction({
      id: 'pycoder-outline',
      label: 'PyCoder: 符号大纲',
      keybindings: [
        monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyO,
      ],
      run: () => {
        const model = editor.getModel();
        if (!model) return;
        const text = model.getValue();
        const lines = text.split('\n');
        const symbols: Array<{ name: string; kind: string; line: number }> = [];
        const pattern = /^(?:async\s+)?(?:def |class\s+)(\w+)/;
        for (let i = 0; i < lines.length; i++) {
          const m = lines[i].match(pattern);
          if (m) {
            symbols.push({
              name: m[1],
              kind: lines[i].startsWith('class') ? 'class' : 'function',
              line: i + 1,
            });
          }
        }
        const icons: Record<string, string> = { class: '📦', function: '🔧' };
        const content = '📋 符号大纲 (' + symbols.length + ' 个):\n' +
          symbols.map((s) => '  ' + (icons[s.kind] || '•') + ' ' + s.name + ' (第' + s.line + '行)').join('\n');
        useAppStore.getState().addMessage({
          id: 'outline-' + Date.now(),
          role: 'system',
          content: content,
          timestamp: Date.now(),
        });
      },
    });

    // Cmd+K / Ctrl+K — 内联编辑
    editor.addAction({
      id: 'pycoder-inline-edit',
      label: 'PyCoder: AI 内联编辑',
      keybindings: [
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyK,
      ],
      run: () => {
        const selection = editor.getSelection();
        if (!selection || selection.isEmpty()) {
          useAppStore.getState().addMessage({
            id: `inline-${Date.now()}`,
            role: 'assistant',
            content: '⚠️ 请先在编辑器中选中要修改的代码，再按 Cmd+K',
            timestamp: Date.now(),
          });
          return;
        }
        setInlineEditOpen(true);
        setInlineEditInstruction('');
        setInlineEditPreview('');
        setInlineEditError('');
      },
    });

    // 内容变更时通知 LSP
    editor.onDidChangeModelContent(() => {
      if (lspModelUri.current && language === 'python') {
        lspVersion.current++;
        getLSPClient().changeDocument(lspModelUri.current, editor.getValue());
      }
    });
  }, [filePath, language]);

  // ── WebSocket 监听 inline_edit 响应 ──
  useEffect(() => {
    if (!wsClient) return;
    const unsub = wsClient.onMessage((msg: any) => {
      if (msg.type === 'inline_edit_stream' && msg.request_id === inlineEditRequestId.current) {
        if (msg.content) {
          setInlineEditPreview(msg.content);
        }
      }
      if (msg.type === 'inline_edit_done' && msg.request_id === inlineEditRequestId.current) {
        setInlineEditLoading(false);
        const editor = editorRef.current;
        if (editor && msg.code) {
          const selection = editor.getSelection();
          if (selection) {
            editor.executeEdits('inline-edit', [{
              range: selection,
              text: msg.code,
            }]);
            editor.focus();
          }
          onCodeReplaced?.(msg.code);
        }
        setInlineEditOpen(false);
        setInlineEditPreview('');
        setInlineEditError('');
      }
    });
    return () => unsub();
  }, [wsClient, onCodeReplaced]);

  // ── 提交内联编辑 ──
  const handleInlineEditSubmit = useCallback(() => {
    if (!wsClient || !editorRef.current || !inlineEditInstruction.trim()) return;

    const editor = editorRef.current;
    const selection = editor.getSelection();
    if (!selection) return;

    const code = editor.getModel()?.getValueInRange(selection) || '';
    setInlineEditLoading(true);
    setInlineEditError('');
    inlineEditRequestId.current = Math.random().toString(36).slice(2, 10);

    wsClient.sendJson({
      type: 'inline_edit',
      code,
      instruction: inlineEditInstruction,
      file_path: filePath,
      language,
      request_id: inlineEditRequestId.current,
    });
  }, [wsClient, filePath, language, inlineEditInstruction]);

  return (
    <div className="monaco-container">
      <Editor
        height="100%"
        language={language}
        value={content}
        theme="vs-dark"
        onMount={handleMount}
        options={{ automaticLayout: true }}
      />

      {/* ── 内联编辑弹出层 ── */}
      {inlineEditOpen && (
        <div ref={inlineEditRef} className="inline-edit-popup">
          <div className="inline-edit-header">
            <span className="inline-edit-title">✏️ AI 内联编辑</span>
            <button className="inline-edit-close" onClick={() => setInlineEditOpen(false)}>✕</button>
          </div>
          <textarea
            className="inline-edit-input"
            placeholder="输入修改指令，如「改用 asyncio 实现」..."
            value={inlineEditInstruction}
            onChange={(e) => setInlineEditInstruction(e.target.value)}
            rows={3}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleInlineEditSubmit();
              }
              if (e.key === 'Escape') {
                setInlineEditOpen(false);
              }
            }}
          />
          {inlineEditLoading && (
            <div className="inline-edit-preview">
              <pre className="inline-edit-pre"><code>{inlineEditPreview || '⏳ 生成中...'}</code></pre>
            </div>
          )}
          {inlineEditError && <div className="inline-edit-error">{inlineEditError}</div>}
          <div className="inline-edit-actions">
            <button className="inline-edit-btn inline-edit-btn-cancel" onClick={() => setInlineEditOpen(false)}>
              取消
            </button>
            <button
              className="inline-edit-btn inline-edit-btn-submit"
              onClick={handleInlineEditSubmit}
              disabled={inlineEditLoading || !inlineEditInstruction.trim()}
            >
              {inlineEditLoading ? '⏳ 生成中...' : '生成 (↵)'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

/** 将 LSP 补全类型映射为 Monaco CompletionItemKind */
function mapCompletionKind(kind: string): monaco.languages.CompletionItemKind {
  const map: Record<string, monaco.languages.CompletionItemKind> = {
    'Text': monaco.languages.CompletionItemKind.Text,
    'Method': monaco.languages.CompletionItemKind.Method,
    'Function': monaco.languages.CompletionItemKind.Function,
    'Constructor': monaco.languages.CompletionItemKind.Constructor,
    'Field': monaco.languages.CompletionItemKind.Field,
    'Variable': monaco.languages.CompletionItemKind.Variable,
    'Class': monaco.languages.CompletionItemKind.Class,
    'Interface': monaco.languages.CompletionItemKind.Interface,
    'Module': monaco.languages.CompletionItemKind.Module,
    'Property': monaco.languages.CompletionItemKind.Property,
    'Unit': monaco.languages.CompletionItemKind.Unit,
    'Value': monaco.languages.CompletionItemKind.Value,
    'Enum': monaco.languages.CompletionItemKind.Enum,
    'Keyword': monaco.languages.CompletionItemKind.Keyword,
    'Snippet': monaco.languages.CompletionItemKind.Snippet,
    'Color': monaco.languages.CompletionItemKind.Color,
    'File': monaco.languages.CompletionItemKind.File,
    'Reference': monaco.languages.CompletionItemKind.Reference,
    'Constant': monaco.languages.CompletionItemKind.Constant,
    'Struct': monaco.languages.CompletionItemKind.Struct,
    'Event': monaco.languages.CompletionItemKind.Event,
    'Operator': monaco.languages.CompletionItemKind.Operator,
    'TypeParameter': monaco.languages.CompletionItemKind.TypeParameter,
  };
  return map[kind] || monaco.languages.CompletionItemKind.Text;
}
