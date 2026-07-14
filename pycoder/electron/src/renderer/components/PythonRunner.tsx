import React, { useState } from 'react';
import { BackendAPI } from '../services/backend';
import { getApiBase } from '../services/config';

export const PythonRunner: React.FC = () => {
  const [code, setCode] = useState('');
  const [output, setOutput] = useState('');
  const [running, setRunning] = useState(false);

  const runCode = async () => {
    if (!code.trim()) return;
    setRunning(true);
    setOutput('运行中...');

    try {
      const res = await BackendAPI.files.write('__temp_run.py', code);
      if (res?.success) {
        // 通过后端 API 执行
        const base = await getApiBase();
        const execRes = await fetch(`${base}/api/code/run`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code, timeout: 10 }),
        });
        const result = await execRes.json();
        setOutput(result.output || result.error || '执行完成（无输出）');
      } else {
        setOutput('❌ 无法创建临时文件');
      }
    } catch (err: any) {
      setOutput(`❌ 错误: ${err.message}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="python-runner">
      <div className="runner-header">
        <span>🐍 Python 运行器</span>
        <button className="runner-btn" onClick={runCode} disabled={running || !code.trim()}>
          {running ? '⏳ 运行中...' : '▶ 运行'}
        </button>
      </div>
      <textarea
        className="runner-input"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="输入 Python 代码..."
        rows={6}
      />
      <div className="runner-output">
        <div className="runner-output-label">输出:</div>
        <pre className="runner-output-text">{output || '等待运行...'}</pre>
      </div>
    </div>
  );
};
