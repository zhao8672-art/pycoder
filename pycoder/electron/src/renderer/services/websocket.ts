/**
 * WebSocket connection manager with auto-reconnect and exponential backoff.
 * Used by the Electron renderer process for resilient PyCoder backend connections.
 */

const MAX_RECONNECT_DELAY_MS = 30000;
const INITIAL_DELAY_MS = 1000;
const BACKOFF_MULTIPLIER = 2;

export interface WSMessage {
  type: string;
  [key: string]: any;
}

type MessageHandler = (msg: WSMessage) => void;
type StatusHandler = (status: ConnectionStatus) => void;

export interface ConnectionStatus {
  connected: boolean;
  retryCount: number;
  nextRetryMs: number | null;
}

export class WSConnectionManager {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: Set<MessageHandler> = new Set();
  private statusHandlers: Set<StatusHandler> = new Set();
  private retryCount = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private disconnected = false;
  private pendingMessages: string[] = [];
  private messageQueue: string[] = [];
  private _incomingBuffer: WSMessage[] = [];

  /** 认证失败时回调 — 用于重新获取 api_key 并重建连接 URL */
  public onAuthFail: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.disconnected = false;
    this._createConnection();
  }

  private _createConnection(): void {
    try {
      this.ws = new WebSocket(this.url);
    } catch (e) {
      this._scheduleRetry();
      return;
    }

    this.ws.onopen = () => {
      this.retryCount = 0;
      this._notifyStatus({ connected: true, retryCount: 0, nextRetryMs: null });
      // Flush pending messages
      while (this.pendingMessages.length > 0) {
        const msg = this.pendingMessages.shift();
        if (msg) this.send(msg);
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage;
        // 如果没有 handler 注册，暂存到 buffer
        if (this.handlers.size === 0) {
          this._incomingBuffer.push(msg);
        } else {
          this.handlers.forEach((h) => h(msg));
        }
      } catch {
        // Ignore non-JSON messages
      }
    };

    this.ws.onclose = (event: CloseEvent) => {
      this._notifyStatus({ connected: false, retryCount: this.retryCount, nextRetryMs: this._getDelay() });
      // 认证失败 (1008) 或握手失败 (1006/403): 重新获取 api_key 并重连
      if (!this.disconnected) {
        const authFailed = event.code === 1008 || event.code === 1006;
        if (authFailed && this.onAuthFail) {
          // 触发重新获取 Key 并重建 URL
          this.onAuthFail();
        } else {
          this._scheduleRetry();
        }
      }
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror, so retry is handled there
    };
  }

  private _getDelay(): number {
    const delay = INITIAL_DELAY_MS * Math.pow(BACKOFF_MULTIPLIER, this.retryCount);
    return Math.min(delay, MAX_RECONNECT_DELAY_MS);
  }

  private _scheduleRetry(): void {
    const delay = this._getDelay();
    this.retryCount++;
    this.retryTimer = setTimeout(() => {
      this._createConnection();
    }, delay);
  }

  send(data: string): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    } else {
      this.pendingMessages.push(data);
      if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
        this.connect();
      }
    }
  }

  sendJson(obj: object): void {
    this.send(JSON.stringify(obj));
  }

  onMessage(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    // 如果有积压的消息，立即回放给新注册的 handler
    if (this._incomingBuffer.length > 0) {
      const buffer = [...this._incomingBuffer];
      this._incomingBuffer = [];
      buffer.forEach((msg) => handler(msg));
    }
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /** onStatusChange — 别名，保持命名一致性 */
  onStatusChange(handler: StatusHandler): () => void {
    return this.onStatus(handler);
  }

  private _notifyStatus(status: ConnectionStatus): void {
    this.statusHandlers.forEach((h) => h(status));
  }

  disconnect(): void {
    this.disconnected = true;
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  getStatus(): ConnectionStatus {
    return {
      connected: this.ws?.readyState === WebSocket.OPEN,
      retryCount: this.retryCount,
      nextRetryMs: this.disconnected ? null : this._getDelay(),
    };
  }
}
