// i18n service — locale switching for PyCoder (React 版本)
import en from './en.json';
import zh from './zh.json';

type LocaleKey = 'zh-CN' | 'en';
type NestedMessages = Record<string, any>;

let currentLocale: LocaleKey = 'zh-CN';

function flatten(obj: NestedMessages, prefix = ''): Record<string, string> {
  let result: Record<string, string> = {};
  for (const key of Object.keys(obj)) {
    const val = obj[key];
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof val === 'object' && val !== null) {
      result = { ...result, ...flatten(val as NestedMessages, path) };
    } else {
      result[path] = String(val);
    }
  }
  return result;
}

const flatMessages: Record<LocaleKey, Record<string, string>> = {
  en: flatten(en as NestedMessages),
  'zh-CN': flatten(zh as NestedMessages),
};

export function setLocale(locale: LocaleKey): void {
  currentLocale = locale;
}

export function t(key: string, fallback?: string): string {
  return flatMessages[currentLocale]?.[key] || flatMessages['en']?.[key] || fallback || key;
}

export function getCurrentLocale(): LocaleKey {
  return currentLocale;
}
