/**
 * 数据库可视化面板 — F6
 *
 * 功能:
 * - 连接管理（新建 / 列表 / 删除，SQLite 支持文件路径）
 * - 表树与表结构查看（列 / 类型 / 主键 / 索引 / 外键）
 * - SQL 编辑器 + 参数化执行 + 结果网格（截断提示）
 * - ER 视图（纯 SVG 节点-连线布局，基于外键）
 *
 * 后端 API: /api/db/*（见 services/dbApi.ts）
 * 安全: 后端默认只读，写操作需显式勾选 allow_write
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    dbApi,
    DbColumn,
    DbConnection,
    DbQueryResult,
    DbTable,
    DbTableSchema,
    ErData,
} from '../services/dbApi';
import { Icon } from './common/Icon';

type MainView = 'tables' | 'query' | 'er';

/** 列类型图标（按 SQL 类型字符串归类） */
function typeIcon(type: string): string {
    const t = type.toLowerCase();
    if (/int|serial|number|decimal|numeric|float|double|real/.test(t)) return '🔢';
    if (/char|text|clob|enum/.test(t)) return '🔤';
    if (/date|time|year/.test(t)) return '📅';
    if (/bool/.test(t)) return '☑️';
    if (/blob|binary|byte/.test(t)) return '📦';
    if (/json|xml/.test(t)) return '🧾';
    return '❔';
}

const panelStyle: React.CSSProperties = {
    display: 'flex', flexDirection: 'column', height: '100%',
    fontSize: 12, color: 'var(--fg-primary, inherit)', overflow: 'hidden',
};
const sectionStyle: React.CSSProperties = {
    padding: '6px 8px', borderBottom: '1px solid var(--border-color, #333)',
};
const tabBarStyle: React.CSSProperties = { display: 'flex', gap: 2, padding: '4px 6px' };
const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1, padding: '4px 0', border: 'none', cursor: 'pointer', borderRadius: 4,
    background: active ? 'var(--bg-tertiary, #3a3a3a)' : 'transparent',
    color: 'inherit', fontSize: 12,
});
const inputStyle: React.CSSProperties = {
    width: '100%', padding: '4px 6px', marginBottom: 4, boxSizing: 'border-box',
    background: 'var(--bg-secondary, #2a2a2a)', color: 'inherit',
    border: '1px solid var(--border-color, #444)', borderRadius: 4, fontSize: 12,
};
const btnStyle: React.CSSProperties = {
    padding: '4px 8px', cursor: 'pointer', borderRadius: 4, fontSize: 12,
    background: 'var(--bg-tertiary, #3a3a3a)', color: 'inherit',
    border: '1px solid var(--border-color, #444)',
};
const errStyle: React.CSSProperties = {
    padding: '4px 8px', color: 'var(--error, #f66)', fontSize: 12, wordBreak: 'break-all',
};

export const DatabasePanel: React.FC = () => {
    // ── 连接状态 ──
    const [connections, setConnections] = useState<DbConnection[]>([]);
    const [activeConn, setActiveConn] = useState<string>('');
    const [showCreate, setShowCreate] = useState(false);
    const [newName, setNewName] = useState('');
    const [newDriver, setNewDriver] = useState<'sqlite' | 'url'>('sqlite');
    const [newPath, setNewPath] = useState('');
    const [newUrl, setNewUrl] = useState('');
    // ── 数据状态 ──
    const [tables, setTables] = useState<DbTable[]>([]);
    const [schema, setSchema] = useState<DbTableSchema | null>(null);
    const [expandedTable, setExpandedTable] = useState<string | null>(null);
    const [view, setView] = useState<MainView>('tables');
    const [sql, setSql] = useState('SELECT * FROM ');
    const [sqlParams, setSqlParams] = useState('');
    const [limit, setLimit] = useState(200);
    const [allowWrite, setAllowWrite] = useState(false);
    const [result, setResult] = useState<DbQueryResult | null>(null);
    const [erData, setErData] = useState<ErData | null>(null);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    // ── 连接管理 ──
    const loadConnections = useCallback(async () => {
        const res = await dbApi.listConnections();
        if (res?.success && res.data) {
            setConnections(res.data);
            if (res.data.length > 0 && !res.data.find((c) => c.name === activeConn)) {
                setActiveConn(res.data[0].name);
            }
        }
    }, [activeConn]);

    useEffect(() => { loadConnections(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const loadTables = useCallback(async (conn: string) => {
        if (!conn) { setTables([]); return; }
        const res = await dbApi.listTables(conn);
        setTables(res?.success && res.data ? res.data : []);
        setSchema(null);
        setExpandedTable(null);
    }, []);

    useEffect(() => {
        loadTables(activeConn);
        setResult(null);
        setErData(null);
        setError('');
    }, [activeConn, loadTables]);

    const handleConnect = async () => {
        setError('');
        if (!newName.trim()) { setError('请填写连接名'); return; }
        const payload = newDriver === 'sqlite'
            ? { name: newName.trim(), driver: 'sqlite', params: { path: newPath.trim() || ':memory:' } }
            : { name: newName.trim(), url: newUrl.trim() };
        const res = await dbApi.connect(payload);
        if (res?.success) {
            setShowCreate(false);
            setNewName(''); setNewPath(''); setNewUrl('');
            await loadConnections();
            setActiveConn(newName.trim());
        } else {
            setError(res?.error || '连接失败');
        }
    };

    const handleDisconnect = async (name: string) => {
        const res = await dbApi.disconnect(name);
        if (res?.success) {
            if (activeConn === name) setActiveConn('');
            await loadConnections();
        }
    };

    // ── 表结构 ──
    const toggleTable = async (table: string) => {
        if (expandedTable === table) { setExpandedTable(null); setSchema(null); return; }
        const res = await dbApi.describeTable(activeConn, table);
        if (res?.success && res.data) {
            setSchema(res.data);
            setExpandedTable(table);
        } else {
            setError(res?.error || '获取表结构失败');
        }
    };

    // ── 查询执行 ──
    const runQuery = async () => {
        setError('');
        setLoading(true);
        setResult(null);
        let params: Record<string, unknown> | undefined;
        if (sqlParams.trim()) {
            try {
                params = JSON.parse(sqlParams);
            } catch {
                setError('参数必须是 JSON 对象，如 {"name": "value"}');
                setLoading(false);
                return;
            }
        }
        const res = await dbApi.query(activeConn, {
            sql, params, limit, allow_write: allowWrite,
        });
        setLoading(false);
        if (res?.success && res.data) {
            setResult(res.data);
        } else {
            setError(res?.error || '查询失败（后端不可达）');
        }
    };

    // ── ER 视图 ──
    const loadEr = async () => {
        setError('');
        const res = await dbApi.getEr(activeConn);
        if (res?.success && res.data) {
            setErData(res.data);
        } else {
            setError(res?.error || '获取 ER 数据失败');
        }
    };

    useEffect(() => {
        if (view === 'er' && activeConn && !erData) loadEr();
    }, [view, activeConn]); // eslint-disable-line react-hooks/exhaustive-deps

    /** ER 布局：节点沿圆周均匀分布，连线为节点中心直线（纯 SVG，无重库） */
    const erLayout = useMemo(() => {
        if (!erData || erData.nodes.length === 0) return null;
        const nodeW = 140;
        const headerH = 22;
        const rowH = 15;
        const nodes = erData.nodes.map((n, i) => {
            const h = headerH + n.columns.length * rowH + 6;
            if (erData.nodes.length === 1) {
                return { ...n, x: 20, y: 20, w: nodeW, h, cx: 20 + nodeW / 2, cy: 20 + h / 2 };
            }
            // 圆周布局
            const radius = Math.max(160, erData.nodes.length * 46);
            const angle = (2 * Math.PI * i) / erData.nodes.length - Math.PI / 2;
            const cx = radius + 160 + radius * Math.cos(angle) * 0.9;
            const cy = radius + 40 + radius * Math.sin(angle) * 0.55;
            return { ...n, x: cx - nodeW / 2, y: cy - h / 2, w: nodeW, h, cx, cy };
        });
        const byName = new Map(nodes.map((n) => [n.name, n]));
        const edges = erData.edges
            .map((e) => {
                const from = byName.get(e.from_table);
                const to = byName.get(e.to_table ?? '');
                if (!from || !to) return null;
                return { x1: from.cx, y1: from.cy, x2: to.cx, y2: to.cy,
                    label: `${e.from_columns.join(',')}→${e.to_columns.join(',')}` };
            })
            .filter((e): e is NonNullable<typeof e> => e !== null);
        const width = Math.max(...nodes.map((n) => n.x + n.w), 0) + 30;
        const height = Math.max(...nodes.map((n) => n.y + n.h), 0) + 30;
        return { nodes, edges, width, height, headerH, rowH };
    }, [erData]);

    // ── 渲染 ──
    const renderColumn = (col: DbColumn) => (
        <div key={col.name} style={{ display: 'flex', gap: 4, padding: '1px 0 1px 14px', alignItems: 'center' }}>
            <span title={col.type}>{typeIcon(col.type)}</span>
            <span style={{ fontWeight: col.primary_key ? 600 : 400 }}>
                {col.primary_key ? '🔑' : ''}{col.name}
            </span>
            <span style={{ opacity: 0.6 }}>{col.type}{col.nullable ? '' : ' NOT NULL'}</span>
        </div>
    );

    return (
        <div style={panelStyle}>
            {/* ── 连接管理区 ── */}
            <div style={sectionStyle}>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
                    <select
                        style={{ ...inputStyle, marginBottom: 0, flex: 1 }}
                        value={activeConn}
                        onChange={(e) => setActiveConn(e.target.value)}
                    >
                        <option value="">（未选择连接）</option>
                        {connections.map((c) => (
                            <option key={c.name} value={c.name}>{c.name} ({c.driver})</option>
                        ))}
                    </select>
                    <button style={btnStyle} title="新建连接" onClick={() => setShowCreate(!showCreate)}>
                        <Icon name="plus" size={13} />
                    </button>
                    {activeConn && (
                        <button style={btnStyle} title="删除当前连接" onClick={() => handleDisconnect(activeConn)}>
                            <Icon name="delete" size={13} />
                        </button>
                    )}
                </div>
                {showCreate && (
                    <div style={{ marginTop: 4 }}>
                        <input style={inputStyle} placeholder="连接名（如 mydb）" value={newName}
                            onChange={(e) => setNewName(e.target.value)} />
                        <select style={inputStyle} value={newDriver}
                            onChange={(e) => setNewDriver(e.target.value as 'sqlite' | 'url')}>
                            <option value="sqlite">SQLite 文件</option>
                            <option value="url">连接 URL（postgres/mysql/sqlite）</option>
                        </select>
                        {newDriver === 'sqlite' ? (
                            <input style={inputStyle} placeholder="数据库文件路径（.db，:memory: 为内存库）"
                                value={newPath} onChange={(e) => setNewPath(e.target.value)} />
                        ) : (
                            <input style={inputStyle} placeholder="如 postgresql://user:***@host:5432/db"
                                value={newUrl} onChange={(e) => setNewUrl(e.target.value)} />
                        )}
                        <button style={{ ...btnStyle, width: '100%' }} onClick={handleConnect}>连接</button>
                    </div>
                )}
            </div>

            {/* ── 视图切换 ── */}
            <div style={tabBarStyle}>
                <button style={tabStyle(view === 'tables')} onClick={() => setView('tables')}>表</button>
                <button style={tabStyle(view === 'query')} onClick={() => setView('query')}>查询</button>
                <button style={tabStyle(view === 'er')} onClick={() => { setView('er'); setErData(null); }}>ER 图</button>
            </div>
            {error && <div style={errStyle}>⚠ {error}</div>}

            {/* ── 表树 ── */}
            {view === 'tables' && (
                <div style={{ flex: 1, overflow: 'auto', padding: '4px 8px' }}>
                    {tables.length === 0 && <div style={{ opacity: 0.6, padding: 8 }}>
                        {activeConn ? '无表或视图' : '请先新建连接'}</div>}
                    {tables.map((t) => (
                        <div key={t.name}>
                            <div
                                style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer', padding: '2px 0' }}
                                onClick={() => toggleTable(t.name)}
                            >
                                <Icon name={expandedTable === t.name ? 'chevron-down' : 'panel-right'} size={11} />
                                <span>{t.type === 'view' ? '👁' : '🗄'} {t.name}</span>
                            </div>
                            {expandedTable === t.name && schema && (
                                <div style={{ marginBottom: 6 }}>
                                    {schema.columns.map(renderColumn)}
                                    {schema.indexes.length > 0 && (
                                        <div style={{ paddingLeft: 14, opacity: 0.7, marginTop: 2 }}>
                                            {schema.indexes.map((i) => (
                                                <div key={i.name ?? i.columns.join()}>📇 {i.name}: ({i.columns.join(', ')}){i.unique ? ' UNIQUE' : ''}</div>
                                            ))}
                                        </div>
                                    )}
                                    {schema.foreign_keys.length > 0 && (
                                        <div style={{ paddingLeft: 14, opacity: 0.7 }}>
                                            {schema.foreign_keys.map((fk, i) => (
                                                <div key={i}>🔗 ({fk.columns.join(',')}) → {fk.referred_table}({fk.referred_columns.join(',')})</div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {/* ── SQL 查询 ── */}
            {view === 'query' && (
                <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', padding: '4px 8px', gap: 4 }}>
                    <textarea
                        style={{ ...inputStyle, minHeight: 72, fontFamily: 'monospace', resize: 'vertical' }}
                        value={sql} onChange={(e) => setSql(e.target.value)}
                        placeholder="SELECT * FROM table WHERE col = :param"
                        spellCheck={false}
                    />
                    <input style={{ ...inputStyle, fontFamily: 'monospace' }} value={sqlParams}
                        onChange={(e) => setSqlParams(e.target.value)}
                        placeholder='参数（可选 JSON）: {"param": "value"}' spellCheck={false} />
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <label style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
                            上限
                            <input type="number" style={{ ...inputStyle, width: 64, marginBottom: 0 }}
                                value={limit} min={1} max={1000}
                                onChange={(e) => setLimit(Number(e.target.value) || 200)} />
                        </label>
                        <label style={{ display: 'flex', gap: 2, alignItems: 'center' }} title="默认只读，勾选后允许 INSERT/UPDATE/DDL">
                            <input type="checkbox" checked={allowWrite}
                                onChange={(e) => setAllowWrite(e.target.checked)} />
                            允许写
                        </label>
                        <button style={{ ...btnStyle, flex: 1 }} onClick={runQuery}
                            disabled={loading || !activeConn}>
                            {loading ? '执行中…' : '▶ 运行'}
                        </button>
                    </div>
                    {result && (
                        <div style={{ marginTop: 4 }}>
                            <div style={{ opacity: 0.7, marginBottom: 4 }}>
                                {result.row_count} 行 · {result.elapsed_ms} ms
                                {result.truncated && <span style={{ color: 'var(--warning, #fa0)' }}>（已达上限 {limit} 行，结果已截断）</span>}
                            </div>
                            {result.columns.length > 0 && (
                                <div style={{ overflow: 'auto', maxHeight: 320, border: '1px solid var(--border-color, #444)', borderRadius: 4 }}>
                                    <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 11 }}>
                                        <thead>
                                            <tr>
                                                {result.columns.map((c) => (
                                                    <th key={c} style={{
                                                        position: 'sticky', top: 0, textAlign: 'left', padding: '3px 6px',
                                                        background: 'var(--bg-tertiary, #3a3a3a)',
                                                        borderBottom: '1px solid var(--border-color, #444)',
                                                    }}>{c}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {result.rows.map((row, ri) => (
                                                <tr key={ri}>
                                                    {row.map((cell, ci) => (
                                                        <td key={ci} style={{
                                                            padding: '2px 6px', maxWidth: 180, overflow: 'hidden',
                                                            textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                            borderBottom: '1px solid var(--border-color, #333)',
                                                        }} title={cell === null ? 'NULL' : String(cell)}>
                                                            {cell === null ? <span style={{ opacity: 0.5 }}>NULL</span> : String(cell)}
                                                        </td>
                                                    ))}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* ── ER 视图（纯 SVG） ── */}
            {view === 'er' && (
                <div style={{ flex: 1, overflow: 'auto', padding: 4 }}>
                    {(!erLayout || erLayout.nodes.length === 0) && (
                        <div style={{ opacity: 0.6, padding: 8 }}>
                            {activeConn ? '无表数据' : '请先新建连接'}</div>
                    )}
                    {erLayout && erLayout.nodes.length > 0 && (
                        <svg width={erLayout.width} height={erLayout.height}>
                            <defs>
                                <marker id="er-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                                    markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                                    <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--fg-secondary, #888)" />
                                </marker>
                            </defs>
                            {erLayout.edges.map((e, i) => (
                                <g key={i}>
                                    <line x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
                                        stroke="var(--fg-secondary, #888)" strokeWidth={1.2}
                                        strokeDasharray="4 3" markerEnd="url(#er-arrow)" />
                                    <text x={(e.x1 + e.x2) / 2} y={(e.y1 + e.y2) / 2 - 4}
                                        fontSize={9} textAnchor="middle"
                                        fill="var(--fg-secondary, #999)">{e.label}</text>
                                </g>
                            ))}
                            {erLayout.nodes.map((n) => (
                                <g key={n.name}>
                                    <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={5}
                                        fill="var(--bg-secondary, #252526)"
                                        stroke="var(--border-color, #454545)" />
                                    <rect x={n.x} y={n.y} width={n.w} height={erLayout.headerH} rx={5}
                                        fill="var(--bg-tertiary, #37373d)" />
                                    <text x={n.x + n.w / 2} y={n.y + 15} fontSize={11} fontWeight={600}
                                        textAnchor="middle" fill="var(--fg-primary, #ccc)">
                                        🗄 {n.name}
                                    </text>
                                    {n.columns.map((c, ci) => (
                                        <text key={c.name} x={n.x + 8}
                                            y={n.y + erLayout.headerH + 12 + ci * erLayout.rowH}
                                            fontSize={10} fill="var(--fg-primary, #bbb)">
                                            {c.primary_key ? '🔑 ' : ''}{c.name}
                                            <tspan fill="var(--fg-secondary, #888)"> : {c.type}</tspan>
                                        </text>
                                    ))}
                                </g>
                            ))}
                        </svg>
                    )}
                </div>
            )}
        </div>
    );
};

export default DatabasePanel;
