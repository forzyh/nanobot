#!/usr/bin/env node
/**
 * nanobot WhatsApp Bridge - WhatsApp Web 与 nanobot Python 后端的桥接服务
 *
 * 这个桥接服务通过 WebSocket 将 WhatsApp Web 连接到 nanobot 的 Python 后端。
 * 它处理以下功能：
 * - 身份验证（扫码登录）
 * - 消息转发（WhatsApp ←→ Python）
 * - 断线重连逻辑
 *
 * 使用方法：
 *   npm run build && npm start
 *
 * 或者使用自定义配置：
 *   BRIDGE_PORT=3001 AUTH_DIR=~/.nanobot/whatsapp npm start
 *
 * 环境变量：
 * - BRIDGE_PORT: 桥接服务端口（默认 3001）
 * - AUTH_DIR: WhatsApp 认证目录（默认 ~/.nanobot/whatsapp-auth）
 * - BRIDGE_TOKEN: 可选的认证令牌
 */

// 为 Baileys 库填充 crypto（ESM 模块需要）
// 在 Node.js 环境中，crypto.webcrypto 提供了 Web Crypto API 的实现
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

// 导入桥接服务器类
import { BridgeServer } from './server.js';
// 导入获取用户主目录的函数
import { homedir } from 'os';
// 导入路径拼接函数
import { join } from 'path';

// 配置常量：桥接服务端口，默认 3001
// 可以通过环境变量 BRIDGE_PORT 覆盖
const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);

// 配置常量：WhatsApp 认证目录
// 存储登录凭证、会话信息等
// 默认位置：~/.nanobot/whatsapp-auth
// 可以通过环境变量 AUTH_DIR 覆盖
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.nanobot', 'whatsapp-auth');

// 配置常量：桥接认证令牌（可选）
// 用于保护 WebSocket 连接，防止未授权访问
const TOKEN = process.env.BRIDGE_TOKEN || undefined;

// 打印欢迎信息
console.log('🐈 nanobot WhatsApp Bridge');
console.log('========================\n');

// 创建桥接服务器实例
const server = new BridgeServer(PORT, AUTH_DIR, TOKEN);

// 处理 SIGINT 信号（Ctrl+C）
// 实现优雅关闭：停止服务器并退出进程
process.on('SIGINT', async () => {
  console.log('\n\nShutting down...');
  await server.stop();
  process.exit(0);
});

// 处理 SIGTERM 信号（系统终止信号）
// 实现优雅关闭
process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

// 启动桥接服务器
// 如果启动失败，打印错误信息并以状态码 1 退出
server.start().catch((error) => {
  console.error('Failed to start bridge:', error);
  process.exit(1);
});
