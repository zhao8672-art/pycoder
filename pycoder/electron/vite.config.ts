import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  root: path.resolve(__dirname, 'src/renderer'),
  base: './',
  build: {
    outDir: path.resolve(__dirname, 'dist/renderer'),
    emptyOutDir: true,
    sourcemap: true,
    cssCodeSplit: true,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          // 编辑器核心
          if (id.includes('monaco-editor')) return 'monaco';
          // React 运行时
          if (id.includes('react-dom') || id.includes('react/') || id.includes('scheduler')) return 'react';
          if (id.includes('react')) return 'react';
          // 终端
          if (id.includes('xterm')) return 'xterm';
          // 图标库
          if (id.includes('lucide-react')) return 'icons';
          // 工具库
          if (id.includes('lodash') || id.includes('date-fns') || id.includes('moment')) return 'vendor';
          // 组件懒加载 — 按功能模块拆分
          if (id.includes('SkillsMarketV2')) return 'skills-market';
          if (id.includes('AIPanel') || id.includes('AgentEventsRenderer')) return 'ai-panel';
          if (id.includes('GitPanel') || id.includes('DiffPreview')) return 'git-panel';
          if (id.includes('ExtensionsPanel')) return 'extensions';
          if (id.includes('TeamPanel')) return 'team';
          if (id.includes('SettingsPanel')) return 'settings';
          if (id.includes('CloudPanel')) return 'cloud';
          if (id.includes('DebugPanel')) return 'debug';
          if (id.includes('TestGenPanel')) return 'test-gen';
          if (id.includes('RunFixPanel')) return 'run-fix';
          if (id.includes('BrowserPanel') || id.includes('WebPreview')) return 'browser';
          if (id.includes('TerminalPanel')) return 'terminal';
          if (id.includes('PythonRunnerPanel')) return 'runner';
          if (id.includes('EvolutionPanel')) return 'evolution';
          if (id.includes('CommandPalette')) return 'command-palette';
          // common 组件合并
          if (id.includes('components/common/')) return 'common';
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src/renderer'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
