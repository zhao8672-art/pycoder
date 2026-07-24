/**
 * SkillDetailV2 — 技能详情页组件
 *
 * 左右分栏布局：
 * - 左侧 60%：截图轮播 / 名称 / Markdown 描述 / 标签 / 评分提交 / 操作按钮
 * - 右侧 40%：统计卡片 / 依赖列表 / 版本历史 / 评分分布 / 评论列表（分页）
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { skillsApi } from '../../services/skillsApi';
import type {
    Review,
    SkillDetail,
} from '../../services/skillsApi';

interface Props {
    skill: SkillDetail;
    onBack: () => void;
    onInstall: (skillId: string) => void;
    onUninstall: (skillId: string) => void;
    onToggleFavorite: (skillId: string) => void;
    onUpdate: (skillId: string) => void;
}

type ReviewSortBy = 'recent' | 'helpful' | 'rating_desc' | 'rating_asc';

export const SkillDetailV2: React.FC<Props> = ({
    skill,
    onBack,
    onInstall,
    onUninstall,
    onToggleFavorite,
    onUpdate,
}) => {
    // ── 截图轮播 ──
    const [screenshotIndex, setScreenshotIndex] = useState(0);
    useEffect(() => {
        setScreenshotIndex(0);
    }, [skill.id]);

    const screenshots = skill.screenshots || [];
    const hasScreenshots = screenshots.length > 0;

    const prevScreenshot = useCallback(() => {
        setScreenshotIndex((i) => (i - 1 + screenshots.length) % screenshots.length);
    }, [screenshots.length]);
    const nextScreenshot = useCallback(() => {
        setScreenshotIndex((i) => (i + 1) % screenshots.length);
    }, [screenshots.length]);

    // ── 评分提交 ──
    const [hoverRating, setHoverRating] = useState(0);
    const [selectedRating, setSelectedRating] = useState(0);
    const [reviewText, setReviewText] = useState('');
    const [submittingReview, setSubmittingReview] = useState(false);
    const [reviewError, setReviewError] = useState('');
    const [reviewSuccess, setReviewSuccess] = useState(false);

    const handleSubmitReview = useCallback(async () => {
        if (selectedRating < 1 || selectedRating > 5) {
            setReviewError('请选择 1-5 星评分');
            return;
        }
        setSubmittingReview(true);
        setReviewError('');
        setReviewSuccess(false);
        try {
            const res = await skillsApi.submitReview(skill.id, {
                rating: selectedRating,
                review_text: reviewText,
                user_id: 'anonymous',
                user_name: 'anonymous',
            });
            if (res?.success) {
                setReviewSuccess(true);
                setReviewText('');
                setSelectedRating(0);
                // 重新拉取评论
                fetchReviews(1);
            } else {
                setReviewError(res?.error || '提交评价失败');
            }
        } catch (err) {
            setReviewError((err as Error)?.message || '提交评价失败');
        } finally {
            setSubmittingReview(false);
        }
    }, [skill.id, selectedRating, reviewText]);

    // ── 评论列表（分页） ──
    const [reviews, setReviews] = useState<Review[]>([]);
    const [reviewsTotal, setReviewsTotal] = useState(0);
    const [reviewsPage, setReviewsPage] = useState(1);
    const [reviewsPageSize] = useState(5);
    const [reviewsSortBy, setReviewsSortBy] = useState<ReviewSortBy>('recent');
    const [reviewsLoading, setReviewsLoading] = useState(false);

    const fetchReviews = useCallback(
        async (targetPage: number) => {
            setReviewsLoading(true);
            try {
                const res = await skillsApi.reviews(
                    skill.id,
                    reviewsSortBy,
                    targetPage,
                    reviewsPageSize,
                );
                if (res?.success && res.data) {
                    setReviews(res.data.reviews || []);
                    setReviewsTotal(res.meta?.total ?? 0);
                    setReviewsPage(res.meta?.page ?? targetPage);
                } else {
                    setReviews([]);
                    setReviewsTotal(0);
                }
            } catch {
                setReviews([]);
                setReviewsTotal(0);
            } finally {
                setReviewsLoading(false);
            }
        },
        [skill.id, reviewsSortBy, reviewsPageSize],
    );

    useEffect(() => {
        // 优先用详情接口附带的评论，再触发分页查询以获取最新
        setReviews((skill.reviews || []).slice(0, reviewsPageSize));
        setReviewsTotal((skill.reviews || []).length);
        fetchReviews(1);
    }, [skill.id, skill.reviews, reviewsPageSize, fetchReviews]);

    const reviewsTotalPages = Math.max(1, Math.ceil(reviewsTotal / reviewsPageSize));

    // ── 评分分布（5/4/3/2/1） ──
    const ratingDistribution = skill.rating_distribution || {};
    const ratingMax = useMemo(() => {
        const values = [1, 2, 3, 4, 5].map((n) => ratingDistribution[String(n)] || 0);
        return Math.max(1, ...values);
    }, [ratingDistribution]);

    // ── 版本历史（最多 20 条） ──
    const versions = (skill.versions || []).slice(0, 20);

    // ── 依赖列表 ──
    const dependencies = skill.dependencies || [];

    // ── Markdown 内容 ──
    const markdown = skill.markdown_content || `# ${skill.name}\n\n${skill.description || ''}`;

    return (
        <div className="skills-v2-detail">
            <button className="skills-v2-btn skills-v2-btn-back" onClick={onBack}>
                ← 返回列表
            </button>

            <div className="skills-v2-detail-layout">
                {/* ══════════ 左侧 60% ══════════ */}
                <div className="skills-v2-detail-left">
                    {/* 截图轮播 */}
                    <div className="skills-v2-screenshots">
                        {hasScreenshots ? (
                            <>
                                <div className="skills-v2-screenshot-stage">
                                    <img
                                        src={screenshots[screenshotIndex].url}
                                        alt={screenshots[screenshotIndex].caption || ''}
                                        className="skills-v2-screenshot-img"
                                    />
                                    {screenshots[screenshotIndex].caption && (
                                        <div className="skills-v2-screenshot-caption">
                                            {screenshots[screenshotIndex].caption}
                                        </div>
                                    )}
                                </div>
                                {screenshots.length > 1 && (
                                    <>
                                        <button
                                            className="skills-v2-screenshot-nav prev"
                                            onClick={prevScreenshot}
                                        >
                                            ‹
                                        </button>
                                        <button
                                            className="skills-v2-screenshot-nav next"
                                            onClick={nextScreenshot}
                                        >
                                            ›
                                        </button>
                                        <div className="skills-v2-screenshot-dots">
                                            {screenshots.map((_, idx) => (
                                                <span
                                                    key={idx}
                                                    className={`skills-v2-screenshot-dot ${
                                                        idx === screenshotIndex ? 'active' : ''
                                                    }`}
                                                    onClick={() => setScreenshotIndex(idx)}
                                                />
                                            ))}
                                        </div>
                                    </>
                                )}
                            </>
                        ) : (
                            <div className="skills-v2-screenshot-placeholder">
                                <span className="skills-v2-screenshot-placeholder-icon">
                                    {skill.icon_url ? (
                                        <img src={skill.icon_url} alt="" width={80} height={80} />
                                    ) : (
                                        '🧩'
                                    )}
                                </span>
                                <span className="skills-v2-screenshot-placeholder-text">
                                    暂无截图
                                </span>
                            </div>
                        )}
                    </div>

                    {/* 名称 + 已验证 */}
                    <div className="skills-v2-detail-title">
                        <h2>{skill.name}</h2>
                        {skill.verified && (
                            <span
                                className="skills-v2-badge skills-v2-badge-verified"
                                title="已验证"
                            >
                                ✓ 已验证
                            </span>
                        )}
                        {skill.has_update && (
                            <span className="skills-v2-badge skills-v2-badge-update">
                                🔄 有更新
                            </span>
                        )}
                    </div>

                    {/* 描述 Markdown */}
                    <div className="skills-v2-detail-markdown">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
                    </div>

                    {/* 标签 */}
                    {skill.tags && skill.tags.length > 0 && (
                        <div className="skills-v2-detail-tags">
                            {skill.tags.map((t) => (
                                <span key={t} className="skills-v2-tag">
                                    {t}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* 评分提交 */}
                    <div className="skills-v2-rate-form">
                        <h4>📝 提交评价</h4>
                        <div className="skills-v2-stars-input">
                            {[1, 2, 3, 4, 5].map((n) => (
                                <span
                                    key={n}
                                    className={`skills-v2-star ${
                                        (hoverRating || selectedRating) >= n ? 'active' : ''
                                    }`}
                                    onMouseEnter={() => setHoverRating(n)}
                                    onMouseLeave={() => setHoverRating(0)}
                                    onClick={() => setSelectedRating(n)}
                                >
                                    {(hoverRating || selectedRating) >= n ? '★' : '☆'}
                                </span>
                            ))}
                        </div>
                        <textarea
                            className="skills-v2-review-textarea"
                            placeholder="写下你的评论（可选，最多 2000 字）"
                            value={reviewText}
                            onChange={(e) => setReviewText(e.target.value.slice(0, 2000))}
                            rows={4}
                        />
                        {reviewError && (
                            <div className="skills-v2-error">❌ {reviewError}</div>
                        )}
                        {reviewSuccess && (
                            <div className="skills-v2-success">✅ 评价已提交</div>
                        )}
                        <button
                            className="skills-v2-btn skills-v2-btn-install"
                            onClick={handleSubmitReview}
                            disabled={submittingReview || selectedRating === 0}
                        >
                            {submittingReview ? '提交中...' : '提交评价'}
                        </button>
                    </div>

                    {/* 操作按钮 */}
                    <div className="skills-v2-detail-actions">
                        {!skill.installed ? (
                            <button
                                className="skills-v2-btn skills-v2-btn-install"
                                onClick={() => onInstall(skill.id)}
                            >
                                📥 安装
                            </button>
                        ) : (
                            <button
                                className="skills-v2-btn skills-v2-btn-uninstall"
                                onClick={() => onUninstall(skill.id)}
                            >
                                📤 卸载
                            </button>
                        )}
                        {skill.has_update && (
                            <button
                                className="skills-v2-btn skills-v2-btn-update"
                                onClick={() => onUpdate(skill.id)}
                            >
                                🔄 更新到最新
                            </button>
                        )}
                        <button
                            className="skills-v2-btn skills-v2-btn-favorite"
                            onClick={() => onToggleFavorite(skill.id)}
                        >
                            ⭐ 收藏
                        </button>
                    </div>
                </div>

                {/* ══════════ 右侧 40% ══════════ */}
                <div className="skills-v2-detail-right">
                    {/* 统计卡片 */}
                    <div className="skills-v2-stats-card">
                        <div className="skills-v2-stat-row">
                            <span className="skills-v2-stat-icon">⭐</span>
                            <span className="skills-v2-stat-label">评分</span>
                            <span className="skills-v2-stat-value">
                                {skill.rating.toFixed(1)} ({skill.rating_count} 评)
                            </span>
                        </div>
                        <div className="skills-v2-stat-row">
                            <span className="skills-v2-stat-icon">⬇</span>
                            <span className="skills-v2-stat-label">下载量</span>
                            <span className="skills-v2-stat-value">{skill.downloads}</span>
                        </div>
                        <div className="skills-v2-stat-row">
                            <span className="skills-v2-stat-icon">📅</span>
                            <span className="skills-v2-stat-label">更新时间</span>
                            <span className="skills-v2-stat-value">
                                {skill.updated_at ? new Date(skill.updated_at).toLocaleDateString() : '-'}
                            </span>
                        </div>
                        <div className="skills-v2-stat-row">
                            <span className="skills-v2-stat-icon">🏷</span>
                            <span className="skills-v2-stat-label">版本</span>
                            <span className="skills-v2-stat-value">
                                v{skill.version || '-'}
                                {skill.has_update && (
                                    <span className="skills-v2-version-update">
                                        {' '}(→ v{skill.remote_version || '?'})
                                    </span>
                                )}
                            </span>
                        </div>
                        <div className="skills-v2-stat-row">
                            <span className="skills-v2-stat-icon">👤</span>
                            <span className="skills-v2-stat-label">发布者</span>
                            <span className="skills-v2-stat-value">
                                {skill.publisher || skill.author || '未知'}
                            </span>
                        </div>
                    </div>

                    {/* 依赖列表 */}
                    {dependencies.length > 0 && (
                        <div className="skills-v2-section">
                            <h4 className="skills-v2-section-title">🔗 依赖</h4>
                            <ul className="skills-v2-deps-list">
                                {dependencies.map((dep) => (
                                    <li key={dep} className="skills-v2-dep-item">
                                        <span>{dep}</span>
                                        <button
                                            className="skills-v2-btn skills-v2-btn-mini"
                                            onClick={() => onInstall(dep)}
                                        >
                                            安装依赖
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* 版本历史 */}
                    {versions.length > 0 && (
                        <div className="skills-v2-section">
                            <h4 className="skills-v2-section-title">🔖 版本历史</h4>
                            <ul className="skills-v2-versions-list">
                                {versions.map((v, idx) => (
                                    <li key={`${v.version}-${idx}`} className="skills-v2-version-item">
                                        <div className="skills-v2-version-header">
                                            <span className="skills-v2-version-tag">v{v.version}</span>
                                            <span className="skills-v2-version-date">
                                                {v.released_at
                                                    ? new Date(v.released_at).toLocaleDateString()
                                                    : '-'}
                                            </span>
                                            {v.download_count > 0 && (
                                                <span className="skills-v2-version-downloads">
                                                    ⬇ {v.download_count}
                                                </span>
                                            )}
                                        </div>
                                        {v.changelog && (
                                            <p className="skills-v2-version-changelog">{v.changelog}</p>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* 评分分布 */}
                    <div className="skills-v2-section">
                        <h4 className="skills-v2-section-title">📊 评分分布</h4>
                        <div className="skills-v2-rating-dist">
                            {[5, 4, 3, 2, 1].map((n) => {
                                const count = ratingDistribution[String(n)] || 0;
                                const pct = (count / ratingMax) * 100;
                                return (
                                    <div key={n} className="skills-v2-rating-dist-row">
                                        <span className="skills-v2-rating-dist-label">{n} 星</span>
                                        <div className="skills-v2-rating-dist-bar">
                                            <div
                                                className="skills-v2-rating-dist-fill"
                                                style={{ width: `${pct}%` }}
                                            />
                                        </div>
                                        <span className="skills-v2-rating-dist-count">{count}</span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {/* 评论列表 */}
                    <div className="skills-v2-section">
                        <div className="skills-v2-section-header">
                            <h4 className="skills-v2-section-title">
                                💬 评论 ({reviewsTotal})
                            </h4>
                            <select
                                className="skills-v2-select skills-v2-select-mini"
                                value={reviewsSortBy}
                                onChange={(e) => {
                                    setReviewsSortBy(e.target.value as ReviewSortBy);
                                    setReviewsPage(1);
                                }}
                            >
                                <option value="recent">最新</option>
                                <option value="helpful">最有用</option>
                                <option value="rating_desc">评分高→低</option>
                                <option value="rating_asc">评分低→高</option>
                            </select>
                        </div>

                        {reviewsLoading ? (
                            <div className="skills-v2-loading">加载中...</div>
                        ) : reviews.length === 0 ? (
                            <div className="skills-v2-empty">暂无评论</div>
                        ) : (
                            <ul className="skills-v2-reviews-list">
                                {reviews.map((r, idx) => (
                                    <li
                                        key={`${r.user_id}-${r.created_at}-${idx}`}
                                        className="skills-v2-review-item"
                                    >
                                        <div className="skills-v2-review-header">
                                            <span className="skills-v2-review-user">{r.user}</span>
                                            <span className="skills-v2-review-rating">
                                                {'★'.repeat(r.rating)}
                                                {'☆'.repeat(5 - r.rating)}
                                            </span>
                                            <span className="skills-v2-review-date">
                                                {r.created_at
                                                    ? new Date(r.created_at).toLocaleString()
                                                    : ''}
                                            </span>
                                        </div>
                                        {(r.review || r.review_text) && (
                                            <p className="skills-v2-review-text">
                                                {r.review || r.review_text}
                                            </p>
                                        )}
                                        {r.helpful_count > 0 && (
                                            <span className="skills-v2-review-helpful">
                                                👍 {r.helpful_count} 觉得有用
                                            </span>
                                        )}
                                    </li>
                                ))}
                            </ul>
                        )}

                        {/* 评论分页 */}
                        {reviewsTotalPages > 1 && (
                            <div className="skills-v2-reviews-pagination">
                                <button
                                    className="skills-v2-btn skills-v2-btn-mini"
                                    onClick={() => fetchReviews(reviewsPage - 1)}
                                    disabled={reviewsPage <= 1}
                                >
                                    上一页
                                </button>
                                <span>
                                    {reviewsPage} / {reviewsTotalPages}
                                </span>
                                <button
                                    className="skills-v2-btn skills-v2-btn-mini"
                                    onClick={() => fetchReviews(reviewsPage + 1)}
                                    disabled={reviewsPage >= reviewsTotalPages}
                                >
                                    下一页
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SkillDetailV2;
