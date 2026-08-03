/**
 * 数据库可视化 API 客户端 — F6
 *
 * 通过 fetch 调用后端 `/api/db/*` 系列端点。
 * 所有方法返回统一响应 { success, data, error }，请求失败时返回 null。
 *
 * 后端路由源: pycoder/server/routers/db_api.py
 */

import { getApiBase, getApiKey } from './config';

// ═══════════════════════════════════════════════════════════
// 类型定义
// ═══════════════════════════════════════════════════════════

/** 连接信息（url 已脱敏，不含明文密码） */
export interface DbConnection {
    name: string;
    driver: string;
    url: string;
    created_at: number;
}

/** 表/视图列表项 */
export interface DbTable {
    name: string;
    type: 'table' | 'view';
}

/** 列定义 */
export interface DbColumn {
    name: string;
    type: string;
    nullable: boolean;
    default: string | null;
    primary_key: boolean;
}

/** 索引定义 */
export interface DbIndex {
    name: string | null;
    columns: string[];
    unique: boolean;
}

/** 外键定义 */
export interface DbForeignKey {
    columns: string[];
    referred_table: string;
    referred_columns: string[];
}

/** 表结构详情 */
export interface DbTableSchema {
    table: string;
    columns: DbColumn[];
    primary_key: string[];
    indexes: DbIndex[];
    foreign_keys: DbForeignKey[];
}

/** 查询执行结果 */
export interface DbQueryResult {
    columns: string[];
    rows: unknown[][];
    row_count: number;
    elapsed_ms: number;
    truncated: boolean;
}

/** ER 图节点（表 + 列） */
export interface ErNode {
    name: string;
    columns: Array<{ name: string; type: string; primary_key: boolean }>;
}

/** ER 图边（外键关系） */
export interface ErEdge {
    from_table: string;
    from_columns: string[];
    to_table: string;
    to_columns: string[];
}

/** ER 图数据 */
export interface ErData {
    nodes: ErNode[];
    edges: ErEdge[];
}

/** 统一响应格式 */
export interface DbApiResponse<T = unknown> {
    success: boolean;
    data?: T;
    error?: string;
    /** true 表示被只读模式拒绝 */
    readonly?: boolean;
}

// ═══════════════════════════════════════════════════════════
// 请求封装
// ═══════════════════════════════════════════════════════════

async function request<T = unknown>(
    path: string,
    options: RequestInit = {},
): Promise<DbApiResponse<T> | null> {
    try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 60000);
        const base = await getApiBase();
        const apiKey = await getApiKey();
        const headers: Record<string, string> = {
            ...((options.headers as Record<string, string>) || {}),
        };
        if (options.body && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }
        if (apiKey) {
            headers['X-API-Key'] = apiKey;
        }
        const res = await fetch(`${base}${path}`, {
            ...options,
            headers,
            signal: controller.signal,
        });
        clearTimeout(timeout);
        return (await res.json()) as DbApiResponse<T>;
    } catch (err) {
        if ((err as Error).name !== 'AbortError') {
            console.error(`[dbApi] ${path} failed:`, err);
        }
        return null;
    }
}

// ═══════════════════════════════════════════════════════════
// API 方法
// ═══════════════════════════════════════════════════════════

export const dbApi = {
    /** 新建连接：SQLite 传 { name, driver: 'sqlite', params: { path } }，或完整 url */
    connect(payload: {
        name: string;
        url?: string;
        driver?: string;
        params?: Record<string, unknown>;
    }) {
        return request<DbConnection>('/api/db/connect', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    },

    /** 连接列表（脱敏） */
    listConnections() {
        return request<DbConnection[]>('/api/db/connections');
    },

    /** 删除连接 */
    disconnect(name: string) {
        return request<{ name: string }>(
            `/api/db/connections/${encodeURIComponent(name)}`,
            { method: 'DELETE' },
        );
    },

    /** 数据库/schema 列表 */
    listDatabases(conn: string) {
        return request<string[]>(`/api/db/${encodeURIComponent(conn)}/databases`);
    },

    /** 表/视图列表 */
    listTables(conn: string) {
        return request<DbTable[]>(`/api/db/${encodeURIComponent(conn)}/tables`);
    },

    /** 表结构（列/主键/索引/外键） */
    describeTable(conn: string, table: string) {
        return request<DbTableSchema>(
            `/api/db/${encodeURIComponent(conn)}/tables/${encodeURIComponent(table)}/schema`,
        );
    },

    /** ER 图数据（基于外键） */
    getEr(conn: string) {
        return request<ErData>(`/api/db/${encodeURIComponent(conn)}/er`);
    },

    /** 执行查询（参数化、默认只读） */
    query(
        conn: string,
        payload: {
            sql: string;
            params?: Record<string, unknown>;
            limit?: number;
            allow_write?: boolean;
        },
    ) {
        return request<DbQueryResult>(
            `/api/db/${encodeURIComponent(conn)}/query`,
            { method: 'POST', body: JSON.stringify(payload) },
        );
    },
};
