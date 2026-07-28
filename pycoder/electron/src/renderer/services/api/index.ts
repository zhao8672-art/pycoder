/**
 * API Index — 聚合所有 API 模块，导出 BackendAPI 兼容接口
 *
 * 新代码可直接导入独立模块：
 *   import { healthApi } from './api/health';
 *   import { sessionApi } from './api/sessions';
 *
 * 旧代码仍可使用 BackendAPI：
 *   import { BackendAPI } from './services/backend';
 */

import { healthApi } from './health';
import { modelApi } from './models';
import { sessionApi } from './sessions';
import { workspaceApi } from './workspace';
import { extensionApi } from './extensions';
import { fileApi } from './files';
import { gitApi } from './git';
import { searchApi, configApi, contextApi, codeExecApi, cloudApi, evolutionApi, pipelineApi, scaffoldApi, teamApi, undoApi, envApi } from './misc';

/** 向后兼容的 BackendAPI 聚合对象 */
export const BackendAPI = {
  health: healthApi.check,
  models: modelApi.list,
  model: {
    select: modelApi.select,
    current: modelApi.current,
    setCustomApiBase: modelApi.setCustomApiBase,
    getCustomApiBases: modelApi.getCustomApiBases,
  },
  env: workspaceApi.env,
  sessions: sessionApi,
  workspace: {
    switch: workspaceApi.switch,
    current: workspaceApi.current,
    recent: workspaceApi.recent,
    restore: workspaceApi.restore,
    detect: workspaceApi.detect,
    setDetectPath: workspaceApi.setDetectPath,
    status: workspaceApi.status,
    getConfig: workspaceApi.getConfig,
    saveConfig: workspaceApi.saveConfig,
    history: workspaceApi.history,
    manage: workspaceApi.manage,
  },
  extensions: extensionApi,
  files: fileApi,
  git: gitApi,
  github: gitApi.github,
  team: teamApi,
  diff: gitApi.diffApi,
  search: searchApi,
  config: configApi,
  context: contextApi,
  codeExec: codeExecApi,
  cloud: cloudApi,
  evolution: evolutionApi,
  pipeline: pipelineApi,
  scaffold: scaffoldApi,
  envCapabilities: envApi.capabilities,
  undo: undoApi,
};