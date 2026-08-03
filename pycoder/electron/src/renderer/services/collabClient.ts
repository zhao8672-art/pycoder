/**
 * CollabClient — 实时协同编辑客户端
 *
 * 与服务端 RealtimeCollabEngine（服务端权威房间状态 + OT 操作转换）配套：
 * - 连接 /ws/collab，join 时获取当前文档 + revision + 成员列表（断线恢复）
 * - 本地 Monaco 编辑 → insert/delete 操作打包发送（携带 base_revision）
 * - 接收远端操作（服务端已做 OT 变换）→ executeEdits 应用并更新 revision
 * - ack/nack 确认对齐本地 revision
 * - 断线自动重连后重新 join，以服务端文档为准完成恢复
 * - 远端光标/选区装饰（按成员颜色渲染，附用户名标签）
 */

import * as monaco from 'monaco-editor';
import { WSConnectionManager } from './websocket';
import { getWsUrl, getApiKey } from './config';

export interface CollabOperation {
  type: 'insert' | 'delete' | 'replace';
  position?: number;
  text?: string;
  length?: number;
  content?: string;
}

export interface CollabMember {
  client_id: string;
  username: string;
  color: string;
  role: string;
  online: boolean;
}

interface RemoteCursor {
  position: { lineNumber: number; column: number; selectionEndLineNumber?: number; selectionEndColumn?: number };
  username: string;
  color: string;
}

type CollabEvent = 'joined' | 'left' | 'members' | 'error';
type EventHandler = (payload?: any) => void;

/** 生成稳定客户端 ID（同源多标签页也不冲突） */
function genClientId(): string {
  return 'c-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

export class CollabClient {
  private ws: WSConnectionManager | null = null;
  private clientId = genClientId();

  roomId = '';
  username = '';
  role = 'editor';
  revision = 0;
  members: CollabMember[] = [];

  private editor: monaco.editor.IStandaloneCodeEditor | null = null;
  private contentDisposable: monaco.IDisposable | null = null;
  private cursorDisposable: monaco.IDisposable | null = null;
  /** 正在应用远端操作 → 跳过本地 change 回传，防止回声 */
  private applyingRemote = false;
  private remoteCursors = new Map<string, RemoteCursor>();
  private decorations: monaco.editor.IEditorDecorationsCollection | null = null;
  private styleEl: HTMLStyleElement | null = null;
  private handlers = new Map<CollabEvent, Set<EventHandler>>();
  /** 最近一次从服务端同步的权威文档（用于绑定编辑器时对齐） */
  private lastDocument = '';

  /** 是否已加入房间（协作开关，默认关闭） */
  get active(): boolean {
    return this.roomId !== '';
  }

  on(event: CollabEvent, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
    return () => this.handlers.get(event)?.delete(handler);
  }

  private emit(event: CollabEvent, payload?: any): void {
    this.handlers.get(event)?.forEach((h) => h(payload));
  }

  /** 加入（或创建）协作房间；返回是否成功 */
  async joinRoom(roomId: string, username: string, role = 'editor'): Promise<boolean> {
    this.leave();
    this.roomId = roomId;
    this.username = username;
    this.role = role;

    const [url, apiKey] = await Promise.all([getWsUrl('/ws/collab'), getApiKey()]);
    const wsUrl = apiKey ? `${url}?api_key=${encodeURIComponent(apiKey)}` : url;
    this.ws = new WSConnectionManager(wsUrl);

    this.ws.onMessage((msg) => this.handleMessage(msg));
    // 断线重连成功后重新 join，以服务端权威状态恢复
    this.ws.onStatus((s) => {
      if (s.connected && this.roomId) this.sendJoin();
    });
    this.ws.connect();

    // 等待 join_result（joined/error 事件），超时视为失败
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => { cleanup(); resolve(false); }, 8000);
      const cleanup = () => {
        clearTimeout(timer);
        unsubJoined();
        unsubError();
      };
      const unsubJoined = this.on('joined', () => { cleanup(); resolve(true); });
      const unsubError = this.on('error', () => { cleanup(); resolve(false); });
    });
  }

  private sendJoin(): void {
    this.ws?.sendJson({
      type: 'join',
      room_id: this.roomId,
      client_id: this.clientId,
      username: this.username,
      role: this.role,
    });
  }

  /** 离开房间并断开连接 */
  leave(): void {
    if (this.ws) {
      this.ws.disconnect();
      this.ws = null;
    }
    this.detachEditor();
    this.roomId = '';
    this.revision = 0;
    this.members = [];
    this.remoteCursors.clear();
  }

  // ─────────────────────────────────────────────
  // Monaco 绑定
  // ─────────────────────────────────────────────

  /** 绑定 Monaco 编辑器（加入房间后调用） */
  attachEditor(editor: monaco.editor.IStandaloneCodeEditor): void {
    this.detachEditor();
    this.editor = editor;
    this.decorations = editor.createDecorationsCollection();

    // 本地编辑 → 操作发送
    this.contentDisposable = editor.onDidChangeModelContent((e) => {
      if (this.applyingRemote || !this.active) return;
      this.sendLocalChanges(e.changes);
    });

    // 本地光标 → 广播
    this.cursorDisposable = editor.onDidChangeCursorSelection((e) => {
      if (!this.active || !this.ws) return;
      const sel = e.selection;
      this.ws.sendJson({
        type: 'cursor',
        position: {
          lineNumber: sel.positionLineNumber,
          column: sel.positionColumn,
          selectionEndLineNumber: sel.endLineNumber,
          selectionEndColumn: sel.endColumn,
        },
      });
    });

    this.renderRemoteCursors();

    // 绑定后若本地文档与服务端权威文档不一致 → 对齐
    const model = editor.getModel();
    if (model && model.getValue() !== this.lastDocument) {
      this.applyingRemote = true;
      try {
        model.pushEditOperations(
          [],
          [{ range: model.getFullModelRange(), text: this.lastDocument }],
          () => null,
        );
      } finally {
        this.applyingRemote = false;
      }
    }
  }

  /** 解绑编辑器 */
  detachEditor(): void {
    this.contentDisposable?.dispose();
    this.cursorDisposable?.dispose();
    this.contentDisposable = null;
    this.cursorDisposable = null;
    this.decorations?.clear();
    this.decorations = null;
    this.editor = null;
  }

  /** 将 Monaco contentChanges 转为操作逐条发送
   *
   * e.changes 按文档位置降序给出（从后往前），逐条应用时
   * 后续操作不影响前序 offset，故按原顺序直接转换发送即可。
   */
  private sendLocalChanges(changes: monaco.editor.IModelContentChange[]): void {
    if (!this.ws) return;
    for (const change of changes) {
      let op: CollabOperation;
      if (change.text && change.rangeLength > 0) {
        // 替换 = 删除 + 插入两条操作
        this.sendEdit({ type: 'delete', position: change.rangeOffset, length: change.rangeLength });
        op = { type: 'insert', position: change.rangeOffset, text: change.text };
      } else if (change.text) {
        op = { type: 'insert', position: change.rangeOffset, text: change.text };
      } else {
        op = { type: 'delete', position: change.rangeOffset, length: change.rangeLength };
      }
      this.sendEdit(op);
    }
    // 同步权威文档快照（供新绑定编辑器对齐）
    const model = this.editor?.getModel();
    if (model) this.lastDocument = model.getValue();
  }

  private sendEdit(op: CollabOperation): void {
    this.ws?.sendJson({ type: 'edit', operation: op, base_revision: this.revision });
  }

  // ─────────────────────────────────────────────
  // 服务端消息处理
  // ─────────────────────────────────────────────

  private handleMessage(msg: any): void {
    switch (msg.type) {
      case 'join_result':
        this.handleJoinResult(msg);
        break;
      case 'ack':
        // 操作确认：以服务端变换后的 revision 为准对齐
        this.revision = msg.revision;
        break;
      case 'nack':
        this.emit('error', msg.error || '操作被拒绝');
        // 被拒绝后主动全量同步，避免本地/服务端漂移
        this.ws?.sendJson({ type: 'sync', room_id: this.roomId });
        break;
      case 'collab_operation':
        this.applyRemoteOperation(msg.operation, msg.revision);
        break;
      case 'cursor_update':
        this.remoteCursors.set(msg.client_id, {
          position: msg.position,
          username: msg.username || msg.client_id,
          color: msg.color || '#ffeaa7',
        });
        this.renderRemoteCursors();
        break;
      case 'sync_result':
        if (msg.success) this.syncDocument(msg.document, msg.revision, msg.members);
        break;
    }
  }

  private handleJoinResult(msg: any): void {
    if (!msg.success) {
      this.emit('error', msg.error || '加入房间失败');
      return;
    }
    this.members = msg.members || [];
    this.syncDocument(msg.document ?? '', msg.revision ?? 0, msg.members);
    this.emit('joined', { roomId: this.roomId, self: msg.self });
    this.emit('members', this.members);
  }

  /** 以服务端权威文档对齐本地（断线恢复/加入房间） */
  private syncDocument(document: string, revision: number, members?: CollabMember[]): void {
    this.lastDocument = document;
    if (members) {
      this.members = members;
      this.emit('members', this.members);
    }
    const model = this.editor?.getModel();
    if (model && model.getValue() !== document) {
      this.applyingRemote = true;
      try {
        // 全量替换但保留 undo 栈
        model.pushEditOperations(
          [],
          [{ range: model.getFullModelRange(), text: document }],
          () => null,
        );
      } finally {
        this.applyingRemote = false;
      }
    }
    this.revision = revision;
  }

  /** 应用远端操作（服务端已完成 OT 变换，直接按位置应用） */
  private applyRemoteOperation(op: CollabOperation & { position?: number }, revision: number): void {
    const model = this.editor?.getModel();
    if (!model) {
      this.revision = revision;
      return;
    }
    this.applyingRemote = true;
    try {
      if (op.type === 'insert') {
        const pos = model.getPositionAt(op.position ?? model.getValueLength());
        this.editor!.executeEdits('collab-remote', [{
          range: new monaco.Range(pos.lineNumber, pos.column, pos.lineNumber, pos.column),
          text: op.text || '',
        }]);
      } else if (op.type === 'delete') {
        const start = model.getPositionAt(op.position ?? 0);
        const end = model.getPositionAt((op.position ?? 0) + (op.length ?? 0));
        this.editor!.executeEdits('collab-remote', [{
          range: new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column),
          text: '',
        }]);
      } else if (op.type === 'replace') {
        this.editor!.executeEdits('collab-remote', [{
          range: model.getFullModelRange(),
          text: op.content ?? '',
        }]);
      }
    } finally {
      this.applyingRemote = false;
    }
    this.revision = revision;
    this.lastDocument = model.getValue();
  }

  // ─────────────────────────────────────────────
  // 远端光标渲染
  // ─────────────────────────────────────────────

  private ensureStyleEl(): HTMLStyleElement {
    if (!this.styleEl) {
      this.styleEl = document.createElement('style');
      document.head.appendChild(this.styleEl);
    }
    return this.styleEl;
  }

  /** 渲染远端光标竖线 + 选区高亮（按成员颜色） */
  private renderRemoteCursors(): void {
    if (!this.editor || !this.decorations) return;
    const styleEl = this.ensureStyleEl();
    const rules: string[] = [];
    const decos: monaco.editor.IModelDeltaDecoration[] = [];

    for (const [cid, cursor] of this.remoteCursors) {
      const safeClass = `collab-remote-${cid.replace(/[^a-zA-Z0-9_-]/g, '')}`;
      rules.push(
        `.${safeClass}-cursor { border-left: 2px solid ${cursor.color}; }`,
        `.${safeClass}-sel { background: ${cursor.color}33; }`,
        `.${safeClass}-cursor::after { content: '${cursor.username.replace(/'/g, '')}';` +
        ` position: absolute; top: -1.2em; left: -2px; font-size: 9px; color: #fff;` +
        ` background: ${cursor.color}; padding: 0 3px; border-radius: 2px; white-space: nowrap; }`,
      );
      const p = cursor.position;
      // 光标竖线
      decos.push({
        range: new monaco.Range(p.lineNumber, p.column, p.lineNumber, p.column),
        options: { className: `${safeClass}-cursor`, stickiness: 1 },
      });
      // 选区高亮（若有）
      if (p.selectionEndLineNumber && p.selectionEndColumn &&
        (p.selectionEndLineNumber !== p.lineNumber || p.selectionEndColumn !== p.column)) {
        decos.push({
          range: new monaco.Range(p.lineNumber, p.column, p.selectionEndLineNumber, p.selectionEndColumn),
          options: { className: `${safeClass}-sel`, stickiness: 1 },
        });
      }
    }

    styleEl.textContent = rules.join('\n');
    this.decorations.set(decos);
  }
}

// ── 模块级单例（TeamPanel 创建/加入房间，MonacoEditor 绑定） ──
let _collabClient: CollabClient | null = null;

export function getCollabClient(): CollabClient {
  if (!_collabClient) _collabClient = new CollabClient();
  return _collabClient;
}
