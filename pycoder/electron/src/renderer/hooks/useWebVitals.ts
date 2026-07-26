/**
 * useWebVitals — Web Vitals 性能监控
 *
 * 监控 Core Web Vitals（LCP、FID、CLS）及自定义指标，
 * 在开发模式下输出到控制台，生产环境可上报到分析服务。
 */
import { useEffect, useRef } from 'react';

interface WebVitalsMetric {
  name: string;
  value: number;
  rating: 'good' | 'needs-improvement' | 'poor';
}

const RATINGS: Record<string, { good: number; poor: number }> = {
  LCP: { good: 2500, poor: 4000 },
  FID: { good: 100, poor: 300 },
  CLS: { good: 0.1, poor: 0.25 },
  FCP: { good: 1800, poor: 3000 },
  TTFB: { good: 800, poor: 1800 },
  INP: { good: 200, poor: 500 },
};

function getRating(name: string, value: number): 'good' | 'needs-improvement' | 'poor' {
  const thresholds = RATINGS[name];
  if (!thresholds) return 'good';
  if (value <= thresholds.good) return 'good';
  if (value <= thresholds.poor) return 'needs-improvement';
  return 'poor';
}

/** 上报指标 */
function reportMetric(metric: WebVitalsMetric) {
  const emoji = metric.rating === 'good' ? '🟢' : metric.rating === 'needs-improvement' ? '🟡' : '🔴';
  console.log(`[WebVitals] ${emoji} ${metric.name}: ${metric.value.toFixed(1)} (${metric.rating})`);

  // 可在此扩展：上报到分析服务
  // navigator.sendBeacon('/api/analytics/vitals', JSON.stringify(metric));
}

export function useWebVitals() {
  const reported = useRef(new Set<string>());

  useEffect(() => {
    if (typeof window === 'undefined') return;

    // 使用 PerformanceObserver 监控 Web Vitals
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const name = entry.name;
        // 避免重复上报
        const key = `${name}-${entry.startTime}`;
        if (reported.current.has(key)) continue;
        reported.current.add(key);

        const metric = {
          name,
          value: 'value' in entry ? (entry.value as number) : entry.startTime,
          rating: getRating(name, 'value' in entry ? (entry.value as number) : entry.startTime),
        };
        reportMetric(metric);
      }
    });

    try {
      observer.observe({ type: 'largest-contentful-paint', buffered: true });
      observer.observe({ type: 'first-input', buffered: true });
      observer.observe({ type: 'layout-shift', buffered: true });
    } catch {
      // 浏览器不支持某些指标类型
    }
    return () => observer.disconnect();
  }, []);
}