/**
 * SkillPublishFormV2 — 技能发布表单
 *
 * 完整字段表单，提交后调用 POST /api/v2/skills/publish。
 * 必填：id / name / description
 * 选填：author / publisher / category / tags / dependencies / version /
 *       source_url / homepage_url / license / icon_url / markdown_content / verified
 */

import React, { useState, useCallback, useMemo } from 'react';
import { skillsApi } from '../../services/skillsApi';
import type { Category } from '../../services/skillsApi';

interface Props {
    onCancel: () => void;
    onPublished: () => void;
    /** 可选：分类列表（用于下拉） */
    categories?: Category[];
}

interface FormState {
    id: string;
    name: string;
    description: string;
    author: string;
    publisher: string;
    category: string;
    tags: string; // 逗号分隔
    dependencies: string; // 逗号分隔
    version: string;
    markdown_content: string;
    source_url: string;
    homepage_url: string;
    license: string;
    icon_url: string;
    verified: boolean;
}

const INITIAL_FORM: FormState = {
    id: '',
    name: '',
    description: '',
    author: 'PyCoder',
    publisher: '',
    category: 'general',
    tags: '',
    dependencies: '',
    version: '1.0.0',
    markdown_content: '',
    source_url: '',
    homepage_url: '',
    license: '',
    icon_url: '',
    verified: false,
};

/** 默认分类下拉选项（若父组件未传入 categories 则使用） */
const DEFAULT_CATEGORIES = [
    'general',
    'code-quality',
    'database',
    'devops',
    'security',
    'architecture',
    'getting-started',
    'other',
];

export const SkillPublishFormV2: React.FC<Props> = ({ onCancel, onPublished, categories }) => {
    const [form, setForm] = useState<FormState>(INITIAL_FORM);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState('');
    const [touched, setTouched] = useState<Record<string, boolean>>({});

    // ── 分类选项 ──
    const categoryOptions = useMemo(() => {
        if (categories && categories.length > 0) {
            return categories.map((c) => c.name);
        }
        return DEFAULT_CATEGORIES;
    }, [categories]);

    // ── 自动生成 Markdown 默认内容（用户未编辑 markdown 时跟随 name/description） ──
    const autoMarkdown = useMemo(() => {
        return `# ${form.name || '技能名称'}\n\n${form.description || '技能描述'}`;
    }, [form.name, form.description]);

    // ── markdown 是否为空或与自动生成内容相同（视为「未编辑」） ──
    const markdownIsPristine = !form.markdown_content || form.markdown_content === autoMarkdown;

    // ── 字段更新 ──
    const updateField = useCallback((key: keyof FormState, value: string | boolean) => {
        setForm((prev) => ({ ...prev, [key]: value }));
    }, []);

    const handleBlur = useCallback((key: keyof FormState) => {
        setTouched((prev) => ({ ...prev, [key]: true }));
    }, []);

    // ── 校验 ──
    const validate = useCallback((): string => {
        if (!form.id.trim()) return '请填写技能 ID';
        if (!form.name.trim()) return '请填写技能名称';
        if (!form.description.trim()) return '请填写描述';
        // ID 仅允许字母数字、下划线、连字符
        if (!/^[a-zA-Z0-9_-]+$/.test(form.id.trim())) {
            return 'ID 仅允许字母、数字、下划线和连字符';
        }
        return '';
    }, [form.id, form.name, form.description]);

    const validationError = validate();
    const canSubmit = !validationError && !submitting;

    // ── 提交 ──
    const handleSubmit = useCallback(async () => {
        setError('');
        setTouched({ id: true, name: true, description: true });
        if (validationError) {
            setError(validationError);
            return;
        }

        const tags = form.tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean);
        const deps = form.dependencies
            .split(',')
            .map((d) => d.trim())
            .filter(Boolean);
        // 若 markdown 未编辑，使用自动生成内容
        const markdown = markdownIsPristine ? autoMarkdown : form.markdown_content;

        setSubmitting(true);
        try {
            const res = await skillsApi.publish({
                id: form.id.trim(),
                name: form.name.trim(),
                description: form.description.trim(),
                author: form.author.trim() || 'PyCoder',
                publisher: form.publisher.trim(),
                category: form.category,
                tags,
                dependencies: deps,
                version: form.version.trim() || '1.0.0',
                markdown_content: markdown,
                source_url: form.source_url.trim(),
                homepage_url: form.homepage_url.trim(),
                license: form.license.trim(),
                icon_url: form.icon_url.trim(),
                verified: form.verified,
            });

            if (res?.success) {
                setForm(INITIAL_FORM);
                onPublished();
            } else {
                setError(res?.error || res?.detail || '发布失败');
            }
        } catch (err) {
            setError((err as Error)?.message || '发布失败');
        } finally {
            setSubmitting(false);
        }
    }, [validationError, form, markdownIsPristine, autoMarkdown, onPublished]);

    // ── 字段错误提示 ──
    const fieldError = (key: keyof FormState): string => {
        if (!touched[key]) return '';
        if (key === 'id' && !form.id.trim()) return 'ID 不能为空';
        if (key === 'name' && !form.name.trim()) return '名称不能为空';
        if (key === 'description' && !form.description.trim()) return '描述不能为空';
        return '';
    };

    return (
        <div className="skills-v2-publish">
            <div className="skills-v2-publish-header">
                <h3 className="skills-v2-publish-title">📦 发布新技能</h3>
                <p className="skills-v2-publish-subtitle">
                    必填字段：ID / 名称 / 描述；其他字段可选。
                </p>
            </div>

            {error && <div className="skills-v2-error">❌ {error}</div>}

            <div className="skills-v2-form-grid">
                {/* ── 必填区 ── */}
                <div className="skills-v2-form-section">
                    <h4 className="skills-v2-form-section-title">必填信息</h4>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">
                            ID <span className="skills-v2-required">*</span>
                        </span>
                        <input
                            className="skills-v2-form-input"
                            value={form.id}
                            onChange={(e) => updateField('id', e.target.value)}
                            onBlur={() => handleBlur('id')}
                            placeholder="如：my-awesome-skill"
                        />
                        {fieldError('id') && (
                            <span className="skills-v2-form-error">{fieldError('id')}</span>
                        )}
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">
                            名称 <span className="skills-v2-required">*</span>
                        </span>
                        <input
                            className="skills-v2-form-input"
                            value={form.name}
                            onChange={(e) => updateField('name', e.target.value)}
                            onBlur={() => handleBlur('name')}
                            placeholder="技能显示名称"
                        />
                        {fieldError('name') && (
                            <span className="skills-v2-form-error">{fieldError('name')}</span>
                        )}
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">
                            描述 <span className="skills-v2-required">*</span>
                        </span>
                        <textarea
                            className="skills-v2-form-textarea"
                            rows={3}
                            value={form.description}
                            onChange={(e) => updateField('description', e.target.value)}
                            onBlur={() => handleBlur('description')}
                            placeholder="简短描述技能功能"
                        />
                        {fieldError('description') && (
                            <span className="skills-v2-form-error">{fieldError('description')}</span>
                        )}
                    </label>
                </div>

                {/* ── 选填区 ── */}
                <div className="skills-v2-form-section">
                    <h4 className="skills-v2-form-section-title">选填信息</h4>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">作者</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.author}
                            onChange={(e) => updateField('author', e.target.value)}
                            placeholder="默认 PyCoder"
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">发布者</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.publisher}
                            onChange={(e) => updateField('publisher', e.target.value)}
                            placeholder="发布者（默认与作者相同）"
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">分类</span>
                        <select
                            className="skills-v2-form-select"
                            value={form.category}
                            onChange={(e) => updateField('category', e.target.value)}
                        >
                            {categoryOptions.map((c) => (
                                <option key={c} value={c}>
                                    {c}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">标签（逗号分隔）</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.tags}
                            onChange={(e) => updateField('tags', e.target.value)}
                            placeholder="python, ai, code-quality"
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">依赖（逗号分隔）</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.dependencies}
                            onChange={(e) => updateField('dependencies', e.target.value)}
                            placeholder="其他技能 ID，逗号分隔"
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">版本</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.version}
                            onChange={(e) => updateField('version', e.target.value)}
                            placeholder="默认 1.0.0"
                        />
                    </label>
                </div>

                {/* ── 链接区 ── */}
                <div className="skills-v2-form-section">
                    <h4 className="skills-v2-form-section-title">链接与元信息</h4>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">源码 URL</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.source_url}
                            onChange={(e) => updateField('source_url', e.target.value)}
                            placeholder="https://github.com/..."
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">主页 URL</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.homepage_url}
                            onChange={(e) => updateField('homepage_url', e.target.value)}
                            placeholder="https://example.com"
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">许可证</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.license}
                            onChange={(e) => updateField('license', e.target.value)}
                            placeholder="如 MIT、Apache-2.0"
                        />
                    </label>

                    <label className="skills-v2-form-field">
                        <span className="skills-v2-form-label">图标 URL</span>
                        <input
                            className="skills-v2-form-input"
                            value={form.icon_url}
                            onChange={(e) => updateField('icon_url', e.target.value)}
                            placeholder="https://example.com/icon.png"
                        />
                    </label>

                    <label className="skills-v2-form-checkbox">
                        <input
                            type="checkbox"
                            checked={form.verified}
                            onChange={(e) => updateField('verified', e.target.checked)}
                        />
                        <span>已验证技能</span>
                    </label>
                </div>

                {/* ── Markdown 区 ── */}
                <div className="skills-v2-form-section skills-v2-form-section-full">
                    <h4 className="skills-v2-form-section-title">
                        Markdown 内容
                        {markdownIsPristine && (
                            <span className="skills-v2-form-hint">
                                （留空将自动生成 # {form.name || '技能名称'}）
                            </span>
                        )}
                    </h4>
                    <textarea
                        className="skills-v2-form-textarea skills-v2-form-markdown"
                        rows={12}
                        value={markdownIsPristine ? autoMarkdown : form.markdown_content}
                        onChange={(e) => updateField('markdown_content', e.target.value)}
                        placeholder="支持 Markdown 格式..."
                    />
                </div>
            </div>

            {/* ── 操作按钮 ── */}
            <div className="skills-v2-publish-actions">
                <button
                    className="skills-v2-btn skills-v2-btn-cancel"
                    onClick={onCancel}
                    disabled={submitting}
                >
                    取消
                </button>
                <button
                    className="skills-v2-btn skills-v2-btn-install"
                    onClick={handleSubmit}
                    disabled={!canSubmit}
                    title={validationError}
                >
                    {submitting ? '发布中...' : '📦 发布'}
                </button>
            </div>
        </div>
    );
};

export default SkillPublishFormV2;
