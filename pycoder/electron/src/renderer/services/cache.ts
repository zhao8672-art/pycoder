/**
 * ApiCache — 前端 API 响应缓存
 *
 * 为高频请求（文件树、扩展列表、技能市场等）提供内存缓存，
 * 减少面板切换时的重复 API 请求。
 */
interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

class ApiCache {
  private store = new Map<string, CacheEntry<unknown>>();

  /** 获取缓存数据 */
  get<T>(key: string): T | null {
    const entry = this.store.get(key);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > entry.ttl) {
      this.store.delete(key);
      return null;
    }
    return entry.data as T;
  }

  /** 设置缓存 */
  set<T>(key: string, data: T, ttl = 30000): void {
    this.store.set(key, { data, timestamp: Date.now(), ttl });
  }

  /** 删除缓存 */
  delete(key: string): void {
    this.store.delete(key);
  }

  /** 清除所有缓存 */
  clear(): void {
    this.store.clear();
  }

  /** 清除匹配前缀的缓存 */
  clearByPrefix(prefix: string): void {
    for (const key of this.store.keys()) {
      if (key.startsWith(prefix)) this.store.delete(key);
    }
  }
}

export const apiCache = new ApiCache();