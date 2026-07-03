import { ChildProcess, spawn } from 'child_process';
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

  constructor(
    private readonly port: number = parseInt(process.env.PYCODER_BACKEND_PORT || '8423', 10),
    private readonly pythonPath: string = 'python'
  ) { super(); }

  get serverUrl(): string { return `http://127.0.0.1:${this.port}`; }
  getStatus(): BackendStatus { return this.status; }

  async start(): Promise<boolean> {
    if (this.status === 'running') return true;
    for (let i = 0; i < 15; i++) {
      const alreadyRunning = await this.checkHealth();
      if (alreadyRunning) {
        this.status = 'running';
        this.restartCount = 0;
        this.emit('status-change', 'running');
        this.startHealthCheck();
        return true;
      }
      if (i < 14) await new Promise(r => setTimeout(r, 1000));
    }
    return this.startProcess();
  }

  private startProcess(): Promise<boolean> {
    return new Promise((resolve) => {
      this.status = 'starting';
      this.emit('status-change', 'starting');
      const projectRoot = path.resolve(__dirname, '..', '..', '..', '..');
      this.process = spawn(this.pythonPath, ['-m', 'pycoder', '--server', '--server-port', String(this.port)], {
        cwd: projectRoot, stdio: 'pipe', windowsHide: true,
        env: { ...process.env, PYTHONUTF8: '1' },
      });
      this.process.stdout?.on('data', (d: Buffer) => { const t = d.toString('utf-8').replace(/\x00/g, '').trim(); if (t) console.log(`[PyCoder Backend] ${t}`); });
      this.process.stderr?.on('data', (d: Buffer) => { const t = d.toString('utf-8').replace(/\x00/g, '').trim(); if (t) console.error(`[PyCoder Backend Error] ${t}`); });
      this.process.on('error', (err: Error) => { console.error(`[PyCoder Backend] Process error:`, err.message); this.status = 'error'; this.emit('status-change', 'error'); resolve(false); });
      this.process.on('exit', (code: number | null) => {
        console.log(`[PyCoder Backend] Process exited with code ${code}`);
        if (this.status !== 'stopped') {
          this.status = 'crashed'; this.emit('status-change', 'crashed');
          if (this.restartCount < this.maxRestarts && !this.isRestarting) {
            this.restartCount++; this.isRestarting = true;
            console.log(`[PyCoder Backend] Auto-restarting (attempt ${this.restartCount}/${this.maxRestarts})...`);
            setTimeout(() => this.startProcess(), 2000);
          }
        }
      });
      this.waitForReady(resolve);
    });
  }

  private waitForReady(resolve: (ready: boolean) => void, retries = 30): void {
    const attempt = () => {
      this.checkHealth().then((ready) => {
        if (ready) { this.status = 'running'; this.restartCount = 0; this.isRestarting = false; this.emit('status-change', 'running'); this.startHealthCheck(); resolve(true); }
        else if (retries > 0) { setTimeout(() => this.waitForReady(resolve, retries - 1), 1000); }
        else { console.error('[PyCoder Backend] Timeout waiting for backend to start'); this.isRestarting = false; resolve(false); }
      });
    }; attempt();
  }

  private checkHealth(): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.get(`${this.serverUrl}/api/health`, (res) => {
        let body = ''; res.on('data', (c: Buffer) => { body += c.toString(); }); res.on('end', () => { try { resolve(JSON.parse(body).status === 'ok'); } catch { resolve(false); } });
      });
      req.on('error', () => resolve(false));
      req.setTimeout(2000, () => { req.destroy(); resolve(false); });
    });
  }

  private startHealthCheck(): void {
    this.healthCheckTimer = setInterval(async () => {
      const healthy = await this.checkHealth();
      if (!healthy && this.status === 'running' && !this.isRestarting) {
        console.warn('[PyCoder Backend] Health check failed');
        this.status = 'crashed'; this.emit('status-change', 'crashed');
        if (this.restartCount < this.maxRestarts) { this.restartCount++; this.isRestarting = true; this.startProcess(); }
      }
    }, 30000);
  }

  stop(): void {
    this.status = 'stopped'; this.emit('status-change', 'stopped');
    if (this.healthCheckTimer) { clearInterval(this.healthCheckTimer); this.healthCheckTimer = null; }
    if (this.process) {
      this.process.kill('SIGTERM');
      setTimeout(() => { if (this.process && !this.process.killed) { this.process.kill('SIGKILL'); } }, 3000);
      this.process = null;
    }
  }
}
