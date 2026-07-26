/**
 * Icon — 统一 SVG 图标组件
 *
 * 使用 Lucide React 图标库替代 Emoji，确保跨平台渲染一致性。
 * 支持主题色自动适配（currentColor）。
 */
import React from 'react';
import type { LucideProps } from 'lucide-react';
import {
  Folder, FolderOpen, Search, GitBranch, Bot, MessageSquare,
  Users, Dna, Puzzle, Wrench, ClipboardList, Globe,
  Play, Command, Cloud, Settings, AlertTriangle, ChevronDown,
  X, Plus, Minus, RefreshCw, Upload, Download, Check, Copy,
  Trash2, Edit3, MoreHorizontal, ExternalLink, FileCode,
  FileText, Terminal, Bug, TestTube, Package, Database,
  Monitor, Sun, Moon, Zap, Shield, Bell, BookOpen, Star,
  GitCompare, GitBranchPlus, GitPullRequest, Blocks, Layout,
  PanelLeft, PanelRight, PanelBottom, Maximize2, Minimize2,
} from 'lucide-react';

export type IconName =
  | 'folder' | 'folder-open' | 'search' | 'git' | 'bot' | 'chat'
  | 'team' | 'evolution' | 'skills' | 'extensions' | 'snippets'
  | 'browser' | 'run' | 'command' | 'cloud' | 'settings'
  | 'alert' | 'chevron-down' | 'close' | 'plus' | 'minus'
  | 'refresh' | 'upload' | 'download' | 'check' | 'copy'
  | 'delete' | 'edit' | 'more' | 'external' | 'file-code'
  | 'file-text' | 'terminal' | 'bug' | 'test' | 'package'
  | 'database' | 'monitor' | 'sun' | 'moon' | 'zap'
  | 'shield' | 'bell' | 'book' | 'star' | 'diff'
  | 'branches' | 'pull-request' | 'blocks' | 'layout'
  | 'panel-left' | 'panel-right' | 'panel-bottom'
  | 'maximize' | 'minimize';

const iconMap: Record<IconName, React.FC<LucideProps>> = {
  folder: Folder,
  'folder-open': FolderOpen,
  search: Search,
  git: GitBranch,
  bot: Bot,
  chat: MessageSquare,
  team: Users,
  evolution: Dna,
  skills: Puzzle,
  extensions: Wrench,
  snippets: ClipboardList,
  browser: Globe,
  run: Play,
  command: Command,
  cloud: Cloud,
  settings: Settings,
  alert: AlertTriangle,
  'chevron-down': ChevronDown,
  close: X,
  plus: Plus,
  minus: Minus,
  refresh: RefreshCw,
  upload: Upload,
  download: Download,
  check: Check,
  copy: Copy,
  delete: Trash2,
  edit: Edit3,
  more: MoreHorizontal,
  external: ExternalLink,
  'file-code': FileCode,
  'file-text': FileText,
  terminal: Terminal,
  bug: Bug,
  test: TestTube,
  package: Package,
  database: Database,
  monitor: Monitor,
  sun: Sun,
  moon: Moon,
  zap: Zap,
  shield: Shield,
  bell: Bell,
  book: BookOpen,
  star: Star,
  diff: GitCompare,
  branches: GitBranchPlus,
  'pull-request': GitPullRequest,
  blocks: Blocks,
  layout: Layout,
  'panel-left': PanelLeft,
  'panel-right': PanelRight,
  'panel-bottom': PanelBottom,
  maximize: Maximize2,
  minimize: Minimize2,
};

interface IconProps extends Omit<LucideProps, 'name'> {
  name: IconName;
}

export const Icon: React.FC<IconProps> = ({ name, size = 16, ...props }) => {
  const IconComponent = iconMap[name];
  if (!IconComponent) {
    console.warn(`[Icon] 未知图标: ${name}`);
    return null;
  }
  return <IconComponent size={size} {...props} />;
};