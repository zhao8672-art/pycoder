import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useAppStore, useChatStore } from '../stores/appStore';
import type { WSConnectionManager, WSMessage } from '../services/websocket';
import type { ChatMessage, DiffFile } from '../types';
import type { AgentProgress, PluginEvent } from '../stores/chatStore';
import { BackendAPI } from '../services/backend';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ChatMessagesList } from './ChatMessagesList';
import { SessionManager } from './SessionManager';
import { AgentThinkingBlock } from './AgentThinkingBlock';
import { AgentToolChain } from './AgentToolChain';
import { AgentDiffCard } from './AgentDiffCard';
import { AgentProgressBar } from './AgentProgressBar';

interface Props {
  wsClient: WSConnectionManager | null;
}

interface Mention {
  type: string;
  label: string;
  value: string;
  content?: string;
}

export const AIPanel: React.FC<Props> = ({ wsClient }) => {
  const {
    chatMessages,
    isStreaming,
    addMessage,
    updateLastMessage,
    setStreaming,
    clearChat,
    toggleAIPanel,
    currentModel,
    models,
    sessions,
    activeSessionId,
    setActiveSession,
    setSessions,
    updateSessionModel,
    setPendingDiffs,
    layout,
  } = useAppStore();

  const { addTokenUsage, agentProgress, pluginEvents, setAgentProgress, addPluginEvent, clearAgentEvents } = useChatStore();

  const [input, setInput] = useState('');
  const [reasoningText, setReasoningText] = useState('');
  const [showSessionManager, setShowSessionManager] = useState(false);
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set());
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteMode, setDeleteMode] = useState<'selected' | 'all'>('selected');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── @mention 状态 ──
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionResults, setMentionResults] = useState<any[]>([]);
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [mentionActiveIdx, setMentionActiveIdx] = useState(0);
  const mentionInputRef = useRef<HTMLTextAreaElement>(null);
  const cursorPosRef = useRef(0);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // 组件挂载时主动加载会话列表（防止 connected 事件丢失）
  useEffect(() => {
    if (!wsClient) return;
    const timer = setTimeout(() => {
      wsClient.sendJson({ type: 'list_sessions' });
    }, 500);
    return () => clearTimeout(timer);
  }, [wsClient]);

  useEffect(() => {
    if (!wsClient) return;
    const unsub = wsClient.onMessage((msg: WSMessage) => {
      switch (msg.type) {
        case 'connected': {
          // 连接成功 — 如果有历史记录，直接加载
          setActiveSession(msg.session_id || '');
          // V2: 保存引擎状态
          if (msg.engine === 'v2' || msg.capabilities !== undefined) {
            useChatStore.getState().setV2Engine(
              true,
              msg.capabilities || 0,
              msg.trust_level || 'READ_ONLY',
            );
          }
          if (msg.has_history) {
            wsClient.sendJson({ type: 'history', session_id: msg.session_id });
          }
          wsClient.sendJson({ type: 'list_sessions' });
          break;
        }
        case 'session_list': {
          const sessionList = msg.sessions || [];
          setSessions(sessionList);
          break;
        }
        case 'history': {
          // 用后端返回的历史消息替换当前对话
          const historyMsgs = msg.messages || [];
          clearChat();
          historyMsgs.forEach((m: any) => {
            const role = m.role || 'assistant';
            const content = m.content || '';
            const id = `hist-${m.timestamp || Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
            if (content) {
              addMessage({ id, role, content, timestamp: (m.timestamp || Date.now()) * 1000 });
            }
          });
          break;
        }
        case 'session_switched':
          break;
        case 'session_created': {
          const newSid = msg.session_id || '';
          if (newSid) {
            setActiveSession(newSid);
            setSessions([{ id: newSid, model: currentModel || 'auto' }, ...sessions]);
          }
          break;
        }
        case 'token': {
          const msgs = useAppStore.getState().chatMessages;
          const last = msgs[msgs.length - 1];
          if (last) {
            const tokenText = msg.data || msg.content || '';
            useAppStore.getState().updateLastMessage(last.content + tokenText);
            useChatStore.getState().addTokenUsage(1);
          }
          break;
        }
        case 'reasoning': {
          // DeepSeek V4 思考链内容 — 渲染为灰色思考块
          const text = msg.data || msg.content || '';
          setReasoningText(prev => prev + text);
          break;
        }
        case 'done':
          setReasoningText('');  // 思考结束，清除 thinking 状态
          if (msg.content) {
            const msgs2 = useAppStore.getState().chatMessages;
            const last2 = msgs2[msgs2.length - 1];
            if (last2 && msg.content !== last2.content) {
              useAppStore.getState().updateLastMessage(msg.content);
            }
          }
          setStreaming(false);
          // 进度显示保留 8 秒后自动清除，让用户看到最终完成状态
          setTimeout(() => {
            useChatStore.getState().clearAgentEvents();
          }, 8000);
          break;
        case 'agent_status':
          addMessage({
            id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            role: 'agent_event',
            content: JSON.stringify({ type: 'status', status: msg.status, message: msg.message }),
            timestamp: Date.now(),
          });
          break;
        case 'agent_step':
          if (msg.step === 'tool_execute') {
            addMessage({
              id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
              role: 'agent_event',
              content: JSON.stringify({ type: 'tool_execute', tool: msg.tool, params: msg.params }),
              timestamp: Date.now(),
            });
          } else if (msg.step === 'tool_result') {
            addMessage({
              id: `agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
              role: 'agent_event',
              content: JSON.stringify({ type: 'tool_result', tool: msg.tool, result: msg.result }),
              timestamp: Date.now(),
            });
          }
          break;
        case 'agent_result':
          setStreaming(false);
          addMessage({
            id: `agent-${Date.now()}`,
            role: 'agent_event',
            content: JSON.stringify({ type: 'result', status: msg.status, summary: msg.summary, iterations: msg.iterations }),
            timestamp: Date.now(),
          });
          break;
        case 'agent_chunk': {
          // agent_chunk 当作普通 token 渲染
          const msgs2 = useAppStore.getState().chatMessages;
          const last2 = msgs2[msgs2.length - 1];
          if (last2) {
            const chunkText = msg.data || msg.content || '';
            useAppStore.getState().updateLastMessage(last2.content + chunkText);
            useChatStore.getState().addTokenUsage(1);
          }
          break;
        }
        case 'agent_error':
          setStreaming(false);
          addMessage({
            id: `agent-err-${Date.now()}`,
            role: 'system',
            content: `❌ Agent 错误: ${msg.message}`,
            timestamp: Date.now(),
          });
          break;
        // ── 统一入口调度事件（展示路由状态）──
        case 'unified_intent':
        case 'unified_beautify':
        case 'unified_route':
        case 'unified_merge':
        case 'unified_health':
          // 调度事件仅在前端状态栏显示，不在消息列表中展示
          break;
        // ── 进度报告事件（独立进度区域展示，不插入消息列表）──
        case 'progress':
          setAgentProgress({
            phase: msg.phase || '',
            stage: msg.stage || '',
            current_step: msg.current_step || 0,
            total_steps: msg.total_steps || 0,
            percent: msg.percent || 0,
            elapsed_seconds: msg.elapsed_seconds || 0,
            eta_seconds: msg.eta_seconds || 0,
            milestones: msg.milestones || [],
          });
          break;
        // ── 后台静默插件/技能执行事件（进度栏展示，不插入消息列表）──
        case 'plugin_event':
          if (msg.hidden) {
            addPluginEvent({
              plugin_id: msg.plugin_id || '',
              plugin_name: msg.plugin_name || msg.plugin_id || '',
              action: msg.action || 'start',
              duration_ms: msg.duration_ms || 0,
              error: msg.error || '',
            });
          }
          break;
        // ── 自动插件/Skills 补全事件（进度栏展示，不插入消息列表）──
        case 'auto_plugin_detected':
          addPluginEvent({
            plugin_id: '__auto_plugin__',
            plugin_name: msg.message || `检测到 ${msg.count || 0} 个缺失能力`,
            action: 'start',
            duration_ms: 0,
          });
          break;
        case 'auto_plugin_evaluated':
          if (msg.best) {
            addPluginEvent({
              plugin_id: '__auto_plugin__',
              plugin_name: msg.message || '评估完成',
              action: 'skip',
              duration_ms: 0,
            });
          }
          break;
        case 'auto_plugin_installed':
          addPluginEvent({
            plugin_id: msg.id || '__auto_plugin__',
            plugin_name: `${msg.message || '已安装'} v${msg.version || ''}`,
            action: 'done',
            duration_ms: 0,
          });
          break;
        case 'error':
          setReasoningText('');
          setStreaming(false);
          addMessage({ id: `err-${Date.now()}`, role: 'system', content: `❌ 错误: ${msg.data || msg.message}`, timestamp: Date.now() });
          break;
        case 'diff-preview':
          setPendingDiffs(msg.files || msg.data);
          break;
        case 'mcp_tools': {
          const builtin = msg.builtin || [];
          const remote = msg.remote || [];
          const servers = msg.connected_servers || [];
          let mcpText = `**🧰 MCP 工具 (共 ${msg.total} 个)**\n\n`;
          mcpText += `**内置 (${builtin.length})**\n`;
          builtin.forEach((t: any) => {
            mcpText += `- \`${t.name}\`: ${t.description}\n`;
          });
          if (remote.length > 0) {
            mcpText += `\n**外部 (${remote.length})**\n`;
            remote.forEach((t: any) => {
              mcpText += `- \`${t.name}\` [${t.source}]: ${t.description}\n`;
            });
            mcpText += `\n已连接服务器: ${servers.join(', ') || '(无)'}\n`;
          }
          mcpText += `\n调用方式: \`/mcp call <工具名> <JSON参数>\``;
          addMessage({
            id: `mcp-${Date.now()}`, role: 'assistant',
            content: mcpText, timestamp: Date.now(),
          });
          break;
        }
        case 'v2_capabilities': {
          const caps = msg.capabilities || [];
          // 更新 V2 引擎状态到 store
          useChatStore.getState().setV2Engine(true, msg.total || caps.length, msg.trust_level || '');
          let capsText = `**⚡ V2 引擎能力 (共 ${caps.length} 个)**\n\n`;
          // 按类别分组
          const byCategory: Record<string, any[]> = {};
          caps.forEach((c: any) => {
            const cat = c.category || 'other';
            if (!byCategory[cat]) byCategory[cat] = [];
            byCategory[cat].push(c);
          });
          Object.entries(byCategory).forEach(([cat, items]) => {
            capsText += `**${cat}** (${items.length})\n`;
            items.slice(0, 5).forEach((c: any) => {
              capsText += `- \`${c.id}\`: ${c.name}\n`;
            });
            if (items.length > 5) capsText += `  ... 还有 ${items.length - 5} 个\n`;
            capsText += '\n';
          });
          capsText += `信任级别: ${msg.trust_level || '—'} | `;
          capsText += `意识模式: ${msg.consciousness_mode || '—'}\n`;
          capsText += `\n调用方式: \`/v2 call <能力ID> <JSON参数>\``;
          addMessage({
            id: `v2-caps-${Date.now()}`, role: 'assistant',
            content: capsText, timestamp: Date.now(),
          });
          break;
        }
        case 'v2_call_result': {
          const resultText = msg.success
            ? `**✅ V2 能力调用成功**\n\n${JSON.stringify(msg.data, null, 2)}`
            : `**❌ V2 能力调用失败**\n\n${msg.error || '未知错误'}`;
          addMessage({
            id: `v2-call-${Date.now()}`, role: 'assistant',
            content: resultText, timestamp: Date.now(),
          });
          break;
        }
        case 'mcp_result':
          addMessage({
            id: `mcp-${Date.now()}`, role: 'system',
            content: msg.success
              ? `✅ **${msg.tool}** 调用成功\n\`\`\`json\n${JSON.stringify(msg.output, null, 2).slice(0, 2000)}\n\`\`\``
              : `❌ **${msg.tool}** 调用失败: ${msg.error}`,
            timestamp: Date.now(),
          });
          break;
        case 'mcp_connect_result':
          addMessage({
            id: `mcp-${Date.now()}`, role: 'system',
            content: msg.success
              ? `✅ 已连接 MCP Server: ${msg.name}`
              : `❌ 连接 MCP Server 失败: ${msg.name}`,
            timestamp: Date.now(),
          });
          break;
      }
    });
    return () => unsub();
  }, [wsClient]);

  const activeModelLabel = currentModel
    ? (models.find((m) => m.id === currentModel)?.name || currentModel)
    : '自动';

  const ensureSession = useCallback(async () => {
    if (activeSessionId) return activeSessionId;
    // 没有活跃会话时，通过 WebSocket 创建新会话
    wsClient?.sendJson({ type: 'create_session' });
    return null;
  }, [activeSessionId, wsClient]);

  // ── 从文件树展平所有文件路径 ──
  function flattenFileTree(tree: any, prefix: string): string[] {
    if (!tree || !Array.isArray(tree)) return [];
    const result: string[] = [];
    for (const item of tree) {
      const fullPath = prefix ? `${prefix}/${item.name}` : item.name;
      if (item.type === 'file') {
        if (item.name.endsWith('.py') || item.name.endsWith('.ts') || item.name.endsWith('.js') || item.name.endsWith('.tsx') || item.name.endsWith('.jsx') || item.name.endsWith('.json') || item.name.endsWith('.md') || item.name.endsWith('.css') || item.name.endsWith('.html')) {
          result.push(fullPath);
        }
      } else if (item.children) {
        result.push(...flattenFileTree(item.children, fullPath));
      }
    }
    return result;
  }

  // ── @mention 搜索 (去抖) ──
  const debouncedMentionSearch = useMemo(() => {
    let timer: ReturnType<typeof setTimeout>;
    return (query: string) => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (query.startsWith('file:') || query.startsWith('f:')) {
          const q = query.replace(/^(file:|f:)/, '');
          const res = await BackendAPI.files.list('.');
          const allFiles = flattenFileTree(res?.tree || [], '');
          const filtered = allFiles
            .filter((f: string) => f.toLowerCase().includes(q.toLowerCase()))
            .slice(0, 10);
          setMentionResults(filtered.map((f: string) => ({ type: 'file', label: `📄 ${f}`, value: f })));
        } else if (query.startsWith('symbol:') || query.startsWith('s:')) {
          const q = query.replace(/^(symbol:|s:)/, '');
          const res = await BackendAPI.context.symbols(q);
          setMentionResults((res?.symbols || []).map((s: any) => ({
            type: 'symbol', label: `🔍 ${s.kind} ${s.name}`, value: `${s.file}:${s.line}`,
            detail: s.name, extra: s,
          })));
        } else if (query.startsWith('dep:') || query.startsWith('d:')) {
          const q = query.replace(/^(dep:|d:)/, '');
          const res = await BackendAPI.context.deps(q);
          setMentionResults((res?.dependencies || []).map((dep: any) => ({
            type: 'dep', label: `📦 ${dep.name} v${dep.version || ''}`, value: dep.name,
            detail: dep.description || '', extra: dep,
          })));
        } else if (query.startsWith('web:') || query.startsWith('w:')) {
          const q = query.replace(/^(web:|w:)/, '');
          const res = await BackendAPI.context.web(q);
          setMentionResults((res?.results || []).slice(0, 5).map((r: any) => ({
            type: 'web', label: `🌐 ${r.title || r.url || q}`, value: r.url || q,
            detail: r.snippet || '', extra: r,
          })));
        } else if (!query.includes(':')) {
          setMentionResults([
            { type: 'type', label: '📄 @file: 引用文件', value: 'file:', typeHint: 'file' },
            { type: 'type', label: '🔍 @symbol: 搜索符号', value: 'symbol:', typeHint: 'symbol' },
            { type: 'type', label: '📦 @dep: 搜索依赖', value: 'dep:', typeHint: 'dep' },
            { type: 'type', label: '🌐 @web: 网页搜索', value: 'web:', typeHint: 'web' },
          ]);
        } else {
          setMentionResults([]);
        }
        setMentionActiveIdx(0);
      }, 200);
    };
  }, []);

  // ── 文本变化检测 @ 触发 ──
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    const pos = e.target.selectionStart;
    setInput(value);
    cursorPosRef.current = pos;

    const lastAt = value.lastIndexOf('@', pos - 1);
    if (lastAt >= 0 && (lastAt === 0 || value[lastAt - 1] === ' ' || value[lastAt - 1] === '\n')) {
      const query = value.slice(lastAt + 1, pos);
      if (!query.includes(' ') && !query.includes('\n')) {
        setMentionOpen(true);
        setMentionQuery(query);
        debouncedMentionSearch(query);
        return;
      }
    }
    if (mentionOpen) {
      setMentionOpen(false);
      setMentionResults([]);
    }
  }, [mentionOpen, debouncedMentionSearch]);

  // ── 选中 mention ──
  const handleMentionSelect = useCallback(async (item: any) => {
    if (item.typeHint) {
      const value = input;
      const pos = cursorPosRef.current;
      const lastAt = value.lastIndexOf('@', pos - 1);
      if (lastAt >= 0) {
        const newInput = value.slice(0, lastAt + 1) + item.value;
        setInput(newInput);
        setMentionQuery(item.value);
        debouncedMentionSearch(item.value);
      }
      return;
    }

    let contextContent = '';
    const mentionLabel = item.label;
    const mentionValue = item.value;

    switch (item.type) {
      case 'file': {
        const res = await BackendAPI.context.file(item.value);
        contextContent = res?.content || '';
        if (!contextContent) {
          addMessage({ id: `mention-${Date.now()}`, role: 'system', content: `⚠️ 无法读取文件: ${item.value}`, timestamp: Date.now() });
          return;
        }
        break;
      }
      case 'symbol': {
        const sym = item.extra || {};
        contextContent = JSON.stringify(sym, null, 2);
        break;
      }
      case 'dep': {
        const dep = item.extra || {};
        contextContent = `${dep.name} v${dep.version || ''}: ${dep.description || ''}`;
        break;
      }
      case 'web': {
        const web = item.extra || {};
        contextContent = web.snippet || web.content || JSON.stringify(web);
        break;
      }
    }

    setMentions(prev => [...prev, { type: item.type, label: mentionLabel, value: mentionValue, content: contextContent }]);
    setMentionOpen(false);
    setMentionResults([]);

    const value = input;
    const pos = cursorPosRef.current;
    const lastAt = value.lastIndexOf('@', pos - 1);
    if (lastAt >= 0) {
      const endOfAt = value.indexOf(' ', lastAt);
      const newInput = value.slice(0, lastAt) + value.slice(endOfAt >= 0 ? endOfAt : pos);
      setInput(newInput);
      setMentionQuery('');
    }
  }, [input, debouncedMentionSearch, addMessage]);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    if (!wsClient) {
      addMessage({ id: `err-${Date.now()}`, role: 'system', content: '⚠️ WebSocket 尚未连接，请稍后重试', timestamp: Date.now() });
      return;
    }

    // ── /mcp 命令 ──
    if (text.startsWith('/mcp ')) {
      const parts = text.slice(5).trim().split(/\s+/);
      const subcmd = parts[0];
      setInput('');

      if (subcmd === 'list' || subcmd === 'ls') {
        addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
        wsClient.sendJson({ type: 'mcp_list' });
        return;
      }

      if (subcmd === 'call') {
        const toolName = parts[1];
        if (!toolName) {
          addMessage({ id: `err-${Date.now()}`, role: 'system', content: '用法: /mcp call <工具名> [JSON参数]', timestamp: Date.now() });
          return;
        }
        let args = {};
        try {
          const rest = text.slice(5).trim().slice(parts[0].length).slice(parts[1].length).trim();
          if (rest) args = JSON.parse(rest);
        } catch { /* 忽略解析错误，使用空参数 */ }
        addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
        wsClient.sendJson({ type: 'mcp_call', tool: toolName, args });
        return;
      }

      if (subcmd === 'connect') {
        const serverName = parts[1];
        const command = parts[2];
        const cmdArgs = parts.slice(3);
        if (!serverName || !command) {
          addMessage({ id: `err-${Date.now()}`, role: 'system', content: '用法: /mcp connect <名称> <命令> [参数...]', timestamp: Date.now() });
          return;
        }
        addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
        wsClient.sendJson({ type: 'mcp_connect', name: serverName, command, args: cmdArgs });
        return;
      }

      if (subcmd === 'disconnect') {
        const serverName = parts[1];
        if (!serverName) {
          addMessage({ id: `err-${Date.now()}`, role: 'system', content: '用法: /mcp disconnect <名称>', timestamp: Date.now() });
          return;
        }
        addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
        wsClient.sendJson({ type: 'mcp_disconnect', name: serverName });
        return;
      }

      // 未知子命令
      addMessage({ id: `err-${Date.now()}`, role: 'system', content: `未知 /mcp 子命令: ${subcmd}\n\n可用命令:\n- \`/mcp list\` — 列出所有 MCP 工具\n- \`/mcp call <工具名> [JSON参数]\` — 调用工具\n- \`/mcp connect <名称> <命令> [参数...]\` — 连接外部 MCP Server\n- \`/mcp disconnect <名称>\` — 断开 MCP Server`, timestamp: Date.now() });
      return;
    }

    // ── /v2 命令（V2 引擎操作）──
    if (text.startsWith('/v2 ')) {
      const parts = text.slice(4).trim().split(/\s+/);
      const subcmd = parts[0];
      setInput('');

      if (subcmd === 'list' || subcmd === 'ls' || subcmd === 'capabilities') {
        addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
        wsClient.sendJson({ type: 'v2_capabilities' });
        return;
      }

      if (subcmd === 'call') {
        const capId = parts[1];
        if (!capId) {
          addMessage({ id: `err-${Date.now()}`, role: 'system', content: '用法: /v2 call <能力ID> [JSON参数]', timestamp: Date.now() });
          return;
        }
        let params = {};
        try {
          const rest = text.slice(4).trim().slice(parts[0].length).slice(parts[1].length).trim();
          if (rest) params = JSON.parse(rest);
        } catch { /* */ }
        addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
        wsClient.sendJson({ type: 'v2_call', capability_id: capId, params });
        return;
      }

      addMessage({ id: `err-${Date.now()}`, role: 'system', content: `未知 /v2 子命令: ${subcmd}\n\n可用命令:\n- \`/v2 list\` — 列出 V2 引擎所有能力\n- \`/v2 call <能力ID> [JSON参数]\` — 直接调用能力`, timestamp: Date.now() });
      return;
    }

    const selectedModel = currentModel || 'auto';
    const sessionId = await ensureSession();
    if (sessionId) {
      updateSessionModel(sessionId, selectedModel);
    }

    // 构建上下文前缀 — Markdown 代码块格式（LLM 更易理解）
    let finalMessage = text;
    if (mentions.length > 0) {
      const contextPrefix = mentions
        .filter(m => m.content)
        .map(m => `## \uD83D\uDCC4 ${m.label}\n\n\`\`\`\n${m.content}\n\`\`\``)
        .join('\n\n---\n\n');
      if (contextPrefix) {
        finalMessage = `${contextPrefix}\n\n---\n\n**问题:** ${text}`;
      }
    }
    setMentions([]);

    addMessage({ id: `user-${Date.now()}`, role: 'user', content: finalMessage, timestamp: Date.now() });
    addMessage({ id: `ai-${Date.now()}`, role: 'assistant', content: '', timestamp: Date.now() });
    addTokenUsage(Math.ceil(finalMessage.length / 3));
    setInput('');
    // 清除上次执行的进度和插件事件
    clearAgentEvents();
    setStreaming(true);
    const { reasoningEffort, enableCache } = useAppStore.getState();
    wsClient?.sendJson({
      type: 'chat',
      message: finalMessage,
      model: selectedModel,
      reasoning_effort: reasoningEffort || 'medium',
      enable_cache: enableCache !== false,
    });
  }, [input, isStreaming, currentModel, ensureSession, updateSessionModel, mentions]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (mentionOpen && mentionResults.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionActiveIdx(prev => Math.min(prev + 1, mentionResults.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionActiveIdx(prev => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        handleMentionSelect(mentionResults[mentionActiveIdx]);
        return;
      }
      if (e.key === 'Escape') {
        setMentionOpen(false);
        setMentionResults([]);
        return;
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const [activeTab, setActiveTab] = useState<'chat' | 'tools' | 'review' | 'pipeline'>('chat');

  return (
    <div className="ai-panel" style={{ width: `${layout.aiPanelWidth}px` }}>
      {/* ── Agent 标签导航 ── */}
      <div className="ai-tabs">
        <div className={`ai-tab ${activeTab === 'chat' ? 'active' : ''}`} onClick={() => setActiveTab('chat')}>
          <span className="tab-icon">💬</span> 对话
        </div>
        <div className={`ai-tab ${activeTab === 'tools' ? 'active' : ''}`} onClick={() => setActiveTab('tools')}>
          <span className="tab-icon">🔧</span> 工具链
        </div>
        <div className={`ai-tab ${activeTab === 'review' ? 'active' : ''}`} onClick={() => setActiveTab('review')}>
          <span className="tab-icon">🔍</span> 审查
        </div>
        <div className={`ai-tab ${activeTab === 'pipeline' ? 'active' : ''}`} onClick={() => setActiveTab('pipeline')}>
          <span className="tab-icon">⚡</span> 流水线
        </div>
      </div>

      {/* ── 紧凑控制栏 ── */}
      <div className="ai-control-bar">
        <select
          className="ai-panel-session-select"
          value={activeSessionId || ''}
          aria-label="切换会话"
          onChange={async (e) => {
            const nextSessionId = e.target.value || null;
            if (!nextSessionId) {
              clearChat();
              wsClient?.sendJson({ type: 'create_session' });
              return;
            }
            setActiveSession(nextSessionId);
            const res = await BackendAPI.sessions.list();
            const found = res?.sessions?.find((s: any) => s.id === nextSessionId);
            if (found?.model) {
              useAppStore.getState().setCurrentModel(found.model);
            }
            clearChat();
            wsClient?.sendJson({ type: 'history', session_id: nextSessionId });
          }}
        >
          <option value="">+ 新会话</option>
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {session.title || session.id.slice(0, 8)}
            </option>
          ))}
        </select>
        <button
          className="ai-panel-manage-btn"
          onClick={() => setShowSessionManager(!showSessionManager)}
          title="管理会话"
        >
          {showSessionManager ? '💬' : '📋'}
        </button>
        <button
          className="hermes-toggle active"
          title="AI 自动判断工作模式"
        >
          {'🤖'}
        </button>
        <button className="ai-panel-close" onClick={toggleAIPanel}>✕</button>
      </div>

      {/* 模式切换条 — 统一由后端自动路由 */}
      <div className="ai-mode-switcher">
        <span className="ai-mode-btn active" style={{ cursor: 'default', padding: '4px 10px' }}>
          🤖 AI 自动调度 (chat·hermes·agent)
        </span>
      </div>

      {/* 模型选择条 */}
      {models.length > 0 && (
        <div className="ai-model-bar">
          <select
            className="ai-model-select"
            value={currentModel}
            onChange={(e) => {
              const modelId = e.target.value;
              useAppStore.getState().setCurrentModel(modelId);
              // 持久化到后端
              BackendAPI.model.select(modelId);
            }}
          >
            {models.map((m: any) => (
              <option key={m.id} value={m.id} disabled={!m.available}>
                {m.available ? '✅ ' : '❌ '}{m.name || m.id}
              </option>
            ))}
          </select>
          <span className="tag-bubble purple" title="BYOK - 使用自有 API Key">
            {(models as any[]).find((m: any) => m.id === currentModel)?.available ? '🟢' : '⛔'}
          </span>
        </div>
      )}

      {/* ── Agent 执行进度条（独立于消息列表） ── */}
      <AgentProgressBar
        progress={agentProgress}
        pluginEvents={pluginEvents}
        isStreaming={isStreaming}
        onClear={clearAgentEvents}
      />

      <div className="ai-panel-messages">
        <SessionManager
          visible={showSessionManager}
          sessions={sessions}
          activeSessionId={activeSessionId}
          selectedSessions={selectedSessions}
          showDeleteConfirm={showDeleteConfirm}
          deleteMode={deleteMode}
          onClose={() => setShowSessionManager(false)}
          onSelect={(id) => {
            setShowSessionManager(false);
            setActiveSession(id);
            clearChat();
            wsClient?.sendJson({ type: 'history', session_id: id });
          }}
          onNewSession={() => {
            wsClient?.sendJson({ type: 'new_session' });
            clearChat();
          }}
          onToggleSelect={(id) => {
            const next = new Set(selectedSessions);
            next.has(id) ? next.delete(id) : next.add(id);
            setSelectedSessions(next);
          }}
          onBatchDelete={() => setShowDeleteConfirm(true)}
          onDeleteModeChange={(m) => setDeleteMode(m)}
          onDeleteConfirm={async () => {
            try {
              if (deleteMode === 'selected') {
                await BackendAPI.sessions.batchDelete(Array.from(selectedSessions));
              } else {
                await BackendAPI.sessions.deleteAll();
              }
              wsClient?.sendJson({ type: 'list_sessions' });
              setSelectedSessions(new Set());
              clearChat();
            } catch {
              // delete failed silently
            }
            setShowDeleteConfirm(false);
          }}
          onDeleteCancel={() => setShowDeleteConfirm(false)}
        />
        {!showSessionManager && chatMessages.map((msg) => {
          if (msg.role === 'agent_event') {
            try {
              const ev = JSON.parse(msg.content);
              switch (ev.type) {
                case 'status':
                  return (
                    <div key={msg.id} className="agent-status-card">
                      <span className="agent-status-icon">
                        {ev.status === 'analyzing' ? '🧠' : ev.status === 'thinking' ? '💭' : '⚙️'}
                      </span>
                      <span className="agent-status-text">{ev.message}</span>
                    </div>
                  );
                case 'tool_execute':
                  return (
                    <div key={msg.id} className="agent-tool-card">
                      <div className="agent-tool-header">
                        🔧 执行 <code>{ev.tool}</code>
                        {ev.params && <span className="agent-tool-params">{JSON.stringify(ev.params)}</span>}
                      </div>
                    </div>
                  );
                case 'tool_result':
                  return (
                    <details key={msg.id} className="agent-tool-result">
                      <summary>📋 {ev.tool} 执行结果</summary>
                      <pre><code>{ev.result}</code></pre>
                    </details>
                  );
                case 'result':
                  return (
                    <div key={msg.id} className="agent-result-card">
                      <div className="agent-result-header">
                        {ev.status === 'done' ? '✅' : '⚠️'} 执行完成
                        <span className="agent-result-iterations">({ev.iterations} 轮)</span>
                      </div>
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{ev.summary}</ReactMarkdown>
                    </div>
                  );
              }
            } catch { }
          }
          return (
            <div key={msg.id} className={`chat-message chat-${msg.role}`}>
              <div className="chat-role">
                {msg.role === 'user' ? '🧑 你' : msg.role === 'assistant' ? '🤖 AI' : '⚙️ 系统'}
              </div>
              <div className="chat-content">
                {msg.role === 'assistant' ? (
                  <>
                    {reasoningText && isStreaming && msg === chatMessages.filter(m => m.role === 'assistant').slice(-1)[0] && (
                      <AgentThinkingBlock
                        steps={[{ text: reasoningText.slice(0, 80) + (reasoningText.length > 80 ? '...' : ''), status: 'active' }]}
                        isThinking={true}
                      />
                    )}                    {isStreaming && !msg.content && (
                      <div className="typing-indicator">
                        <span className="typing-dot"></span>
                        <span className="typing-dot"></span>
                        <span className="typing-dot"></span>
                        <span style={{ marginLeft: 8, opacity: 0.6 }}>AI 正在思考...</span>
                      </div>
                    )}                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content || (isStreaming ? '▊' : '')}
                    </ReactMarkdown>
                  </>
                ) : (
                  <p>{msg.content}</p>
                )}
              </div>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      <div className="ai-panel-input">
        {/* 快捷指令 */}
        <div className="ai-quick-commands">
          <button className="ai-quick-cmd" onClick={() => setInput(prev => prev + (prev ? ' ' : '') + '/explain')}>
            {'\u{1F4D6} \u89E3\u91CA\u4EE3\u7801'}
          </button>
          <button className="ai-quick-cmd" onClick={() => setInput(prev => prev + (prev ? ' ' : '') + '/fix')}>
            {'\u{1F527} \u4FEE\u590D\u7F3A\u9677'}
          </button>
          <button className="ai-quick-cmd" onClick={() => setInput(prev => prev + (prev ? ' ' : '') + '/test')}>
            {'\u{1F9EA} \u751F\u6210\u6D4B\u8BD5'}
          </button>
          <button className="ai-quick-cmd" onClick={() => setInput(prev => prev + (prev ? ' ' : '') + '/refactor')}>
            {'\u{1F5C2}\uFE0F \u91CD\u6784'}
          </button>
          <button className="ai-quick-cmd" onClick={() => setInput(prev => prev + (prev ? ' ' : '') + '/doc')}>
            {'\u{1F4DD} \u6587\u6863'}
          </button>
        </div>
        <div className="ai-panel-input-area">
          {mentions.length > 0 && (
            <div className="mention-chips">
              {mentions.map((m, i) => (
                <span key={i} className="mention-chip">
                  {m.label}
                  <button className="mention-chip-remove" onClick={() => {
                    setMentions(prev => prev.filter((_, idx) => idx !== i));
                  }}>✕</button>
                </span>
              ))}
            </div>
          )}

          <textarea
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... @ 引用文件/符号/网页（AI 自动判断工作模式）"
            rows={2}
            disabled={isStreaming}
            ref={mentionInputRef}
          />

          {mentionOpen && mentionResults.length > 0 && (
            <div className="mention-dropdown">
              {mentionResults.map((item, i) => (
                <div
                  key={i}
                  className={`mention-item ${i === mentionActiveIdx ? 'mention-item-active' : ''}`}
                  onClick={() => handleMentionSelect(item)}
                  onMouseEnter={() => setMentionActiveIdx(i)}
                >
                  <span className="mention-item-label">{item.label}</span>
                  {item.detail && <span className="mention-item-detail">{item.detail}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="ai-panel-input-actions">
          <button className="btn-generate" onClick={() => { setInput('/generate '); }} title="一键生成项目">
            🚀
          </button>
          <button className="btn-mcp" onClick={() => {
            setInput('/mcp list');
            setTimeout(() => {
              const text = '/mcp list';
              if (!isStreaming && wsClient) {
                addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
                wsClient.sendJson({ type: 'mcp_list' });
                setInput('');
              }
            }, 50);
          }} title="列出 MCP 工具">
            🔧
          </button>
          <button className="btn-mcp" onClick={() => {
            setInput('/v2 list');
            setTimeout(() => {
              const text = '/v2 list';
              if (!isStreaming && wsClient) {
                addMessage({ id: `user-${Date.now()}`, role: 'user', content: text, timestamp: Date.now() });
                wsClient.sendJson({ type: 'v2_capabilities' });
                setInput('');
              }
            }, 50);
          }} title="列出 V2 引擎能力">
            ⚡
          </button>
          {isStreaming && (
            <button className="btn-stop" onClick={() => { wsClient?.sendJson({ type: 'stop' }); setStreaming(false); }}>
              ⏹
            </button>
          )}
          <button className="btn-send" onClick={sendMessage} disabled={!input.trim() || isStreaming}>
            {isStreaming ? '生成中...' : '发送'}
          </button>
          <span className="ai-panel-model-indicator" title={`当前模型: ${activeModelLabel}`}>{activeModelLabel}</span>
        </div>
      </div>
    </div>
  );
};
