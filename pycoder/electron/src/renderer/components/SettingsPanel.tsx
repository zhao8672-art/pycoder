import React, { useState, useEffect } from 'react';
import { useAppStore } from '../stores/appStore';
import { BackendAPI } from '../services/backend';

export const SettingsPanel: React.FC = () => {
  const { currentModel, models, setCurrentModel, setModels } = useAppStore();
  const [apiKey, setApiKey] = useState('');
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({});
  const [saveMsg, setSaveMsg] = useState('');
  const [permissions, setPermissions] = useState<Record<string, string>>({
    shell: 'ask', file_write: 'ask', file_read: 'allow', network: 'ask',
  });
  const [permMsg, setPermMsg] = useState('');

  useEffect(() => {
    BackendAPI.models().then((res) => {
      if (res?.models) {
        setModels(res.models);
        const recommended = res.recommended_model || res.models[0]?.id || '';
        if (recommended) {
          setCurrentModel(recommended);
        }
      }
    });
    BackendAPI.config.keys().then((res) => {
      if (res?.providers) {
        const status: Record<string, boolean> = {};
        Object.entries(res.providers).forEach(([k, v]) => { status[k] = !!v.configured; });
        setKeyStatus(status);
      }
    });
    // 加载权限策略
    BackendAPI.config.permissions().then((res: any) => {
      if (res?.policy) setPermissions(res.policy);
    });
  }, []);

  const handlePermChange = async (key: string, value: string) => {
    const updated = { ...permissions, [key]: value };
    setPermissions(updated);
    const res = await BackendAPI.config.updatePermissions({ [key]: value });
    if (res?.success) {
      setPermMsg('✅ 权限已更新');
    } else {
      setPermMsg('❌ 权限更新失败');
    }
    setTimeout(() => setPermMsg(''), 2000);
  };

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return;
    // 自动识别提供商（按 currentModel 优先，避免 sk- 前缀误判）
    let provider = 'deepseek';
    if (currentModel.startsWith('qwen')) provider = 'qwen';
    else if (currentModel.startsWith('glm')) provider = 'glm';
    else if (currentModel.startsWith('gpt') || currentModel.startsWith('o')) provider = 'openai';
    else if (currentModel.startsWith('agnes')) provider = 'agnes';
    else if (currentModel.startsWith('deepseek')) provider = 'deepseek';
    // 兜底: 根据 Key 格式猜测（sk- 可能是 openai 或 deepseek）
    else if (apiKey.startsWith('sk-') && apiKey.length > 10) provider = 'openai';

    const res = await BackendAPI.config.setup(provider, apiKey, currentModel);
    if (res?.success) {
      setSaveMsg('✅ 保存成功');
      setKeyStatus({ ...keyStatus, [provider]: true });
    } else {
      setSaveMsg('❌ 保存失败');
    }
    setTimeout(() => setSaveMsg(''), 3000);
  };

  return (
    <div className="settings-panel">
      {/* 模型选择 */}
      <div className="settings-section">
        <div className="settings-label">AI 模型</div>
        <select
          className="settings-select"
          value={currentModel || ''}
          onChange={(e) => setCurrentModel(e.target.value)}
          aria-label="选择 AI 模型"
        >
          {models.map((m) => (
            <option key={m.id} value={m.id}>{m.name} ({m.provider})</option>
          ))}
        </select>
      </div>

      {/* API Key */}
      <div className="settings-section">
        <div className="settings-label">API Key</div>
        <div className="settings-key-status">
          {Object.entries(keyStatus).map(([provider, ok]) => (
            <span key={provider} className={`key-badge ${ok ? 'key-ok' : 'key-missing'}`}>
              {provider}: {ok ? '✅ 已配置' : '❌ 未配置'}
            </span>
          ))}
        </div>
        <div className="settings-key-input">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="输入 API Key..."
            className="settings-input"
          />
          <button className="settings-btn" onClick={handleSaveKey}>保存</button>
        </div>
        {saveMsg && <div className="settings-msg">{saveMsg}</div>}
      </div>

      {/* 推理设置 */}
      <div className="settings-section">
        <div className="settings-label">🧠 DeepSeek 推理设置</div>
        <div className="settings-row">
          <span className="settings-row-label">推理强度</span>
          <div className="settings-btn-group">
            {[
              { value: 'low', label: '快速' },
              { value: 'medium', label: '均衡' },
              { value: 'max', label: '深度' },
            ].map((opt) => (
              <button
                key={opt.value}
                className={`settings-btn-sm ${(useAppStore.getState() as any).reasoningEffort === opt.value ? 'active' : ''}`}
                onClick={() => {
                  const s = useAppStore.getState() as any;
                  if (s.setReasoningEffort) s.setReasoningEffort(opt.value);
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <div className="settings-row">
          <label className="settings-toggle">
            <input
              type="checkbox"
              checked={(useAppStore.getState() as any).enableCache !== false}
              onChange={(e) => {
                const s = useAppStore.getState() as any;
                if (s.setEnableCache) s.setEnableCache(e.target.checked);
              }}
            />
            <span>🔋 KV Cache 降本 <span className="settings-hint">(可节省 50-90% 输入 token 费)</span></span>
          </label>
        </div>
      </div>

      {/* 模型信息 */}
      <div className="settings-section">
        <div className="settings-label">当前模型信息</div>
        {models.find((m) => m.id === currentModel) ? (
          <div className="settings-model-info">
            <div>ID: {currentModel}</div>
            <div>上下文: {(models.find((m) => m.id === currentModel)?.contextWindow ?? 0).toLocaleString()} tokens</div>
          </div>
        ) : (
          <div className="settings-placeholder">加载中...</div>
        )}
      </div>

      {/* 权限控制 */}
      <div className="settings-section">
        <div className="settings-label">🔒 权限控制</div>
        <div className="settings-perm-grid">
          {[
            { key: 'shell', label: 'Shell 命令' },
            { key: 'file_write', label: '文件写入' },
            { key: 'file_read', label: '文件读取' },
            { key: 'network', label: '网络请求' },
            { key: 'clipboard', label: '剪贴板' },
          ].map(({ key, label }) => (
            <div key={key} className="settings-perm-row">
              <span className="settings-perm-label">{label}</span>
              <select
                className="settings-perm-select"
                value={permissions[key] || 'ask'}
                aria-label={label}
                onChange={(e) => handlePermChange(key, e.target.value)}
              >
                <option value="allow">✅ 始终允许</option>
                <option value="ask">❓ 每次询问</option>
                <option value="deny">🚫 拒绝</option>
              </select>
            </div>
          ))}
        </div>
        {permMsg && <div className="settings-msg">{permMsg}</div>}
      </div>
    </div>
  );
};
