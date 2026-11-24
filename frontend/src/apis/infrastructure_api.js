import { apiSuperAdminGet, apiSuperAdminPost, apiSuperAdminPut } from './base'

/**
 * 基础设施 API 模块
 *
 * 对应后端 /api/infrastructure/*：
 * - connections: 各基础组件的连接地址读写（存数据库，保存后立即生效）
 * - services: 受管服务清单与可达性
 *
 * 连接地址的取值优先级为「数据库 → 部署环境变量 → 默认值」，
 * 因此页面上的地址既可能是管理员刚保存的，也可能是服务器部署时配置的。
 */
export const infrastructureApi = {
  /**
   * 获取连接地址（含量效值、来源与可达性）
   * @returns {Promise<{connections: Array}>}
   */
  getConnections: async () => {
    return apiSuperAdminGet('/api/infrastructure/connections')
  },

  /**
   * 保存可编辑的连接地址
   * @param {Object} values - { minio_uri: 'http://...', ... } 形式的地址集合
   */
  saveConnections: async (values) => {
    return apiSuperAdminPut('/api/infrastructure/connections', { values })
  },

  /**
   * 获取受管服务清单与当前状态
   */
  getServices: async () => {
    return apiSuperAdminGet('/api/infrastructure/services')
  },

  /**
   * 重新拉取连接地址（用于其他进程改动后的显式刷新）
   */
  refreshConnections: async () => {
    return apiSuperAdminPost('/api/infrastructure/connections/refresh')
  }
}
