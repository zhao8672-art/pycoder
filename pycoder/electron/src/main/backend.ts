import { ChildProcess, spawn, execSync } from 'child_process';
import path from 'path';
import http from 'http';
import { EventEmitter } from 'events';

export type BackendStatus = 'starting' | 'running' | 'stopped' | 'crashed' | 'error';

export class PythonBackendManager extends EventEmitter {
  private process: ChildProcess | null = null;
  private status: BackendStatus = 'stopped';
  private restartCount = 0;
  private readonly maxRestarts = 3;
  private healthCheckTimer: NodeJS.Timeout | null = null;
  private isRestarting = false;
  private _lastStderr = '';

  constructor(
    private readonly port: number = parseInt(process.env.PYCODER_BACKEND_PORT || '8423', 10),
    private readonly pythonPath: string = 'python'
  ) {
    super();
  }

  get serverUrl(): string {
    return `http://127.0.0.1:${this.port}`;
  }

  getStatus(): BackendStatus {
    return this.status;
  }

  async start(): Promise<boolean> {
    // 如果设置了 SKIP_EMBEDDED_BACKEND=1，则不启动内嵌后端，仅检查外部后端
    if (process.env.SKIP_EMBEDDED_BACKEND === '1') {
      const alreadyRunning = await this.checkHealth();
      if (alreadyRunning) {
        this.status = 'running';
        this.startHealthCheck();
        return true;
      }
      this.status = 'error';
      this.emit('status-change', 'error');
      return false;
    }

    if (this.status === 'running') {
      return true;
    }

    // 先快速检查端口是否已被外部后端占用
    const quickCheck = await this.checkHealth();
    if (quickCheck) {
      this.status = 'running';
      this.restartCount = 0;
      this.emit('status-change', 'running');
      this.startHealthCheck();
      return true;
    }

    // 延长重试: 最多等 30s (外部后端可能在启动中)
    for (let i = 0; i < 30; i++) {
      const alreadyRunning = await this.checkHealth();
      if (alreadyRunning) {
        this.status = 'running';
        this.restartCount = 0;
        this.emit('status-change', 'running');
        this.startHealthCheck();
        return true;
      }
      await new Promise(r => setTimeout(r, 1000));
    }

    return this.startProcess();
  }

  private startProcess(): Promise<boolean> {
    return new Promise((resolve) => {
      this.status = 'starting';
      this.emit('status-change', 'starting');

      const projectRoot = path.resolve(__dirname, '..', '..', '..', '..');

      // ════════════════════════════════════════════════════
      // P0: 启动前强制杀掉占用目标端口的进程（防止重启循环）
      // ════════════════════════════════════════════════════
      if (this.process) {
        try { this.process.kill('SIGKILL'); } catch { }
        this.process = null;
      }
      // 使用系统命令找到并杀死占用端口的进程
      try {
        const netstatOut = execSync(
          `netstat -ano | findstr :${this.port}`,
          { timeout: 3000, encoding: 'utf-8' }
        );
        const lines = netstatOut.trim().split('\n');
        const killedPids = new Set<number>();
        for (const line of lines) {
          const parts = line.trim().split(/\s+/);
          if (parts.length >= 5) {
            const pid = parseInt(parts[parts.length - 1], 10);
            if (pid && pid > 0 && !killedPids.has(pid)) {
              try {
                process.kill(pid, 'SIGTERM');
                killedPids.add(pid);
                console.log(
                  `[PyCoder Backend] Killed PID ${pid} on port ${this.port}`
                );
              } catch { }
            }
          }
        }
        // 等 1.5 秒让 TIME_WAIT 释放
        setTimeout(() => this._doSpawn(resolve, projectRoot), 1500);
      } catch {
        // netstat 没找到占用进程 → 直接启动
        this._doSpawn(resolve, projectRoot);
      }
    });
  }

  private _doSpawn(
    resolve: (ready: boolean) => void,
    projectRoot: string
  ): void {
    this._lastStderr = '';  // 重置错误缓冲

    this.process = spawn(
      this.pythonPath,
      ['-m', 'pycoder', '--server', '--server-port', String(this.port)],
      {
        cwd: projectRoot,
        stdio: 'pipe',
        windowsHide: true,
        env: { ...process.env, PYTHONUTF8: '1' },
      }
    );

    this.process.stdout?.on('data', (data: Buffer) => {
      const text = data.toString('utf-8').replace(/\x00/g, '').trim();
      if (text) console.log(`[PyCoder Backend] ${text}`);
    });

    this.process.stderr?.on('data', (data: Buffer) => {
      const text = data.toString('utf-8').replace(/\x00/g, '').trim();
      if (text) {
        console.error(`[PyCoder Backend Error] ${text}`);
        this._lastStderr += text + '\n';
      }
    });

    this.process.on('error', (err: Error) => {
      console.error(`[PyCoder Backend] Process error:`, err.message);
      this.status = 'error';
      this.emit('status-change', 'error');
      resolve(false);
    });

    this.process.on('exit', (code: number | null) => {
      console.log(`[PyCoder Backend] Process exited with code ${code}`);
      if (this.status !== 'stopped') {
        this.status = 'crashed';
        this.emit('status-change', 'crashed');

        const stderrLower = (this._lastStderr || '').toLowerCase();
        const isPortConflict = stderrLower.includes('bind') ||
          stderrLower.includes('10048') ||
          stderrLower.includes('eaddrinuse') ||
          stderrLower.includes('address already in use');
        if (isPortConflict) {
          console.log(
            '[PyCoder Backend] Port occupied, checking existing backend...'
          );
          this._tryConnectExisting(resolve);
          return;
        }

        if (this.restartCount < this.maxRestarts && !this.isRestarting) {
          this.restartCount++;
          this.isRestarting = true;
          console.log(
            '[PyCoder Backend] Auto-restarting'
            + ` (${this.restartCount}/${this.maxRestarts})...`
          );
          // 直接重启（旧进程已退出，不再 kill）
          setTimeout(
            () => this._doSpawn(resolve, projectRoot),
            2000
          );
        } else if (this.restartCount >= this.maxRestarts) {
          console.error(
            '[PyCoder Backend] Max restart attempts reached'
          );
          this.isRestarting = false;
          this.status = 'error';
          this.emit('status-change', 'error');
          resolve(false);
        }
      }
    });

    this.waitForReady(resolve);
  }

  private waitForReady(resolve: (ready: boolean) => void, retries = 30): void {
    const attempt = () => {
      this.checkHealth().then((ready) => {
        if (ready) {
          this.status = 'running';
          this.restartCount = 0;  // 成功启动后重置重启计数
          this.isRestarting = false;
          this.emit('status-change', 'running');
          this.startHealthCheck();
          resolve(true);
        } else if (retries > 0) {
          setTimeout(() => this.waitForReady(resolve, retries - 1), 1000);
        } else {
          console.error('[PyCoder Backend] Timeout waiting for backend to start');
          this.isRestarting = false;
          resolve(false);
        }
      });
    };
    attempt();
  }

  /** 端口被占用时: 轮询健康检查来代替启动新进程 */
  private async _tryConnectExisting(
    resolve: (ready: boolean) => void
  ): Promise<void> {
    this.isRestarting = true;
    for (let i = 0; i < 10; i++) {
      const ok = await this.checkHealth();
      if (ok) {
        console.log('[PyCoder Backend] Connected to existing backend');
        this.status = 'running';
        this.restartCount = 0;
        this.isRestarting = false;
        this.emit('status-change', 'running');
        this.startHealthCheck();
        resolve(true);
        return;
      }
      await new Promise(r => setTimeout(r, 1000));
    }
    // 10 秒后仍未连接 → 强制清理僵尸进程并重新启动
    console.log(
      '[PyCoder Backend] No existing backend, killing stale processes...'
    );
    try {
      execSync('taskkill /f /im python.exe 2>nul', {
        timeout: 5000,
        encoding: 'utf-8',
      });
    } catch { }
    // 等 2 秒让端口释放，然后重试启动
    setTimeout(() => {
      this.isRestarting = false;
      this.restartCount = 0;
      this.startProcess().then(resolve);
    }, 2000);
  }

  private checkHealth(): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.get(`${this.serverUrl}/api/health`, (res) => {
        let body = '';
        res.on('data', (chunk: Buffer) => { body += chunk.toString(); });
        res.on('end', () => {
          try {
            const data = JSON.parse(body);
            resolve(data.status === 'ok');
          } catch {
            resolve(false);
          }
        });
      });
      req.on('error', () => resolve(false));
      req.setTimeout(2000, () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  private startHealthCheck(): void {
    // 清除旧定时器，防止重复创建导致健康检查井喷
    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
    }
    this.healthCheckTimer = setInterval(async () => {
      const healthy = await this.checkHealth();
      if (!healthy && this.status === 'running' && !this.isRestarting) {
        console.warn('[PyCoder Backend] Health check failed');
        this.status = 'crashed';
        this.emit('status-change', 'crashed');
        if (this.restartCount < this.maxRestarts) {
          this.restartCount++;
          this.isRestarting = true;
          this.startProcess();
        }
      }
    }, 30000);
  }

  stop(): void {
    this.status = 'stopped';
    this.emit('status-change', 'stopped');

    if (this.healthCheckTimer) {
      clearInterval(this.healthCheckTimer);
      this.healthCheckTimer = null;
    }

    if (this.process) {
      this.process.kill('SIGTERM');
      setTimeout(() => {
        if (this.process && !this.process.killed) {
          this.process.kill('SIGKILL');
        }
      }, 3000);
      this.process = null;
    }
  }
}
