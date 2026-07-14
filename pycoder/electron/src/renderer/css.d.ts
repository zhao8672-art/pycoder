// CSS 模块类型声明 — 让 TypeScript 能识别 .css 的 side-effect import
declare module '*.css' {
  const content: Record<string, string>;
  export default content;
}

declare module '*.scss' {
  const content: Record<string, string>;
  export default content;
}
