import React, { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '../stores/appStore';
import { BackendAPI } from '../services/backend';
import type { ModelInfo } from '../types';

export const SettingsPanel: React.FC = () => {
  const { currentModel, models, setCurrentModel, setModels } = useAppStore();
  const [apiKey, setApiKey] = useState('');
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({});
  const [saveMsg, setSaveMsg] = useState('');
  const [selectedModelInfo, setSelectedModelInfo] = useState<ModelInfo | null>(null);
  const [customApiBase, setCustomApiBase] = useState('');
  const [customApiBaseMsg, setCustomApiBaseMsg] = useState('');
  const [permissions, setPermissions] = useState<Record<string, string>>({
    shell: 'ask', file_write: 'ask', file_read: 'allow', network: 'ask',
  });
  const [permMsg, setPermMsg] = useState('');

  // 分组模型
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([]);
  const [unavailableModels, setUnavailableModels] = useState<ModelInfo[]>([]);

  useEffect(() => {
    loadModels();
    loadKeyStatus();
    BackendAPI.config.permissions().then((res: any) => {
      if (res?.policy) setPermissions(res.policy);
    });
  }, []);

  const loadModels = async () => {
    const res = await BackendAPI.models();
    if (res?.models) {
      setModels(res.models);
      setAvailableModels(res.models.filter((m: ModelInfo) => m.available));
      setUnavailableModels(res.models.filter((m: ModelInfo) => !m.available));
    }
    // 加载用户已保存的模型偏好
    const currentRes = await BackendAPI.model.current();
    if (currentRes?.model) {
      const savedId = currentRes.model.id;
      if (savedId && !currentModel) {
        setCurrentModel(savedId);
      }
      setSelectedModelInfo(currentRes.model as unknown as ModelInfo);
      if (currentRes.model.api_base) {
        setCustomApiBase(currentRes.model.api_base);
      }
    }
  };

  const loadKeyStatus = async () => {
    const res = await BackendAPI.config.keys();
    if (res?.providers) {
      const status: Record<string, boolean> = {};
      Object.entries(res.providers).forEach(([k, v]) => { status[k] = !!v.configured; });
      setKeyStatus(status);
    }
  };

  // 选择模型并持久化
  const handleModelSelect = useCallback(async (modelId: string) => {
    setCurrentModel(modelId);
    const info = models.find((m: ModelInfo) => m.id === modelId);
    setSelectedModelInfo(info || null);
    if (info?.api_base) setCustomApiBase(info.api_base);
    // 持久化到后端
    const res = await BackendAPI.model.select(modelId);
    setSaveMsg(res?.success ? `✅ 已切换至 ${info?.name || modelId}` : '❌ 切换失败');
    setTimeout(() => setSaveMsg(''), 3000);
  }, [models, setCurrentModel]);

  // 保存自定义 API Base
  const handleSaveCustomApiBase = useCallback(async () => {
    if (!currentModel || !customApiBase.trim()) return;
    const res = await BackendAPI.model.setCustomApiBase(currentModel, customApiBase.trim());
    setCustomApiBaseMsg(res?.success ? `✅ 自定义 API 地址已保存` : '❌ 保存失败');
    setTimeout(() => setCustomApiBaseMsg(''), 3000);
  }, [currentModel, customApiBase]);

  const handleSaveKey = async () => {
    if (!apiKey.trim()) return;
    let provider = 'deepseek';
    if (currentModel.startsWith('qwen')) provider = 'qwen';
    else if (currentModel.startsWith('glm')) provider = 'glm';
    else if (currentModel.startsWith('gpt') || currentModel.startsWith('o')) provider = 'openai';
    else if (currentModel.startsWith('claude')) provider = 'anthropic';
    else if (currentModel.startsWith('agnes')) provider = 'agnes';
    else if (currentModel.startsWith('deepseek')) provider = 'deepseek';
    else if (apiKey.startsWith('sk-') && apiKey.length > 10) provider = 'openai';

    const res = await BackendAPI.config.setup(provider, apiKey, currentModel);
    if (res?.success) {
      setSaveMsg('✅ Key 保存成功');
      setKeyStatus({ ...keyStatus, [provider]: true });
      loadModels(); // 刷新模型可用状态
    } else {
      setSaveMsg('❌ Key 保存失败');
    }
    setTimeout(() => setSaveMsg(''), 3000);
  };

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

  return (
    <div className="settings-panel">
      {/* ═══ 模型选择 ═══ */}
      <div className="settings-section">
        <div className="settings-label">🤖 AI 模型选择</div>
        <select
          className="settings-select"
          value={currentModel || ''}
          onChange={(e) => handleModelSelect(e.target.value)}
          aria-label="选择 AI 模型"
        >
          <optgroup label="✅ 可用（已配置 Key）">
            {availableModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.provider}) — ${m.pricing_input}/${m.pricing_output}
              </option>
            ))}
          </optgroup>
          <optgroup label="❌ 未配置 Key">
            {unavailableModels.map((m) => (
              <option key={m.id} value={m.id} disabled>
                {m.name} ({m.provider})
              </option>
            ))}
          </optgroup>
        </select>
        <div className="settings-hint" style={{ marginTop: 4, fontSize: 11, opacity: 0.7 }}>
          选中的模型会自动保存为默认模型
        </div>
        {saveMsg && <div className="settings-msg">{saveMsg}</div>}
      </div>

      {/* ═══ 当前模型详情 ═══ */}
      {selectedModelInfo && (
        <div className="settings-section">
          <div className="settings-label">当前模型信息</div>
          <div className="settings-model-info">
            <div><strong>ID:</strong> {selectedModelInfo.id}</div>
            <div><strong>提供商:</strong> {selectedModelInfo.provider}</div>
            <div><strong>状态:</strong> {selectedModelInfo.available ? '✅ 可用' : '❌ 需配置 Key'}</div>
            <div><strong>上下文:</strong> {(selectedModelInfo.contextWindow ?? 0).toLocaleString()} tokens</div>
            <div><strong>定价:</strong> 输入 ${selectedModelInfo.pricing_input}/M · 输出 ${selectedModelInfo.pricing_output}/M</div>
            <div><strong>特性:</strong> {selectedModelInfo.features?.join(' · ') || '—'}</div>
            <div><strong>API 地址:</strong> <code style={{ fontSize: 10, wordBreak: 'break-all' }}>{selectedModelInfo.api_base || '默认'}</code></div>
          </div>
        </div>
      )}

      {/* ═══ 自定义 API 地址 ═══ */}
      <div className="settings-section">
        <div className="settings-label">🔗 自定义 API 地址</div>
        <div className="settings-hint" style={{ marginBottom: 6, fontSize: 11, opacity: 0.7 }}>
          为当前模型设置自定义 API 端点（兼容 OpenAI 格式），留空使用默认地址
        </div>
        <div className="settings-key-input" style={{ display: 'flex', gap: 6 }}>
          <input
            type="text"
            value={customApiBase}
            onChange={(e) => setCustomApiBase(e.target.value)}
            placeholder="https://api.example.com/v1"
            className="settings-input"
          />
          <button className="settings-btn" onClick={handleSaveCustomApiBase}>保存</button>
        </div>
        {customApiBaseMsg && <div className="settings-msg">{customApiBaseMsg}</div>}
      </div>

      {/* ═══ API Key ═══ */}
      <div className="settings-section">
        <div className="settings-label">🔑 API Key 管理</div>
        <div className="settings-hint" style={{ marginBottom: 6, fontSize: 11, opacity: 0.7 }}>
          配置任意模型的 API Key 后即可解锁使用
        </div>
        <div className="settings-key-status" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
          {Object.entries(keyStatus).map(([provider, ok]) => (
            <span key={provider} className={`key-badge ${ok ? 'key-ok' : 'key-missing'}`}
              style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4 }}>
              {provider}: {ok ? '✅' : '❌'}
            </span>
          ))}
        </div>
        <div className="settings-key-input" style={{ display: 'flex', gap: 6 }}>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
            className="settings-input"
          />
          <button className="settings-btn" onClick={handleSaveKey}>保存</button>
        </div>
      </div>

      {/* ═══ 推理设置 ═══ */}
      <div className="settings-section">
        <div className="settings-label">🧠 推理设置</div>
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
            <span>🔋 KV Cache 降本 <span className="settings-hint">(节省 50-90% 输入费)</span></span>
          </label>
        </div>
      </div>

      {/* ═══ 权限控制 ═══ */}
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

      {/* ═══ 可用模型完整列表 ═══ */}
      <div className="settings-section">
        <div className="settings-label">📋 所有可用模型（{models.length} 个）</div>
        <div style={{ maxHeight: 300, overflowY: 'auto', fontSize: 11 }}>
          {models.map((m) => (
            <div key={m.id} className="settings-row" style={{
              padding: '6px 8px', cursor: 'pointer', borderRadius: 4,
              background: m.id === currentModel ? 'rgba(99,102,241,0.15)' : 'transparent',
              borderLeft: m.id === currentModel ? '3px solid #6366f1' : '3px solid transparent',
            }} onClick={() => handleModelSelect(m.id)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span><strong>{m.name}</strong></span>
                <span>{m.available ? '✅' : '❌'}</span>
              </div>
              <div style={{ opacity: 0.6, fontSize: 10 }}>
                {m.provider} · {(m.contextWindow ?? 0).toLocaleString()} ctx · ${m.pricing_input}/M in
              </div>
              {m.features && m.features.length > 0 && (
                <div style={{ opacity: 0.5, fontSize: 9, marginTop: 2 }}>
                  {m.features.join(' · ')}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
