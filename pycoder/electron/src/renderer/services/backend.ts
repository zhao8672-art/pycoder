/**
 * Backend API — 兼容层，从 api/ 模块重新导出
 *
 * 新代码建议直接导入独立模块：
 *   import { sessionApi } from './api/sessions';
 *   import { healthApi } from './api/health';
 */
export { BackendAPI } from './api/index';