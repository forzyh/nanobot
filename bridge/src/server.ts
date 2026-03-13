/**
 * WebSocket 服务器 - 用于 Python 和 Node.js 之间的桥接通信
 *
 * 安全设计：
 * - 仅绑定到 127.0.0.1（本地回环），不暴露到外部网络
 * - 可选的 BRIDGE_TOKEN 认证（通过环境变量配置）
 *
 * 消息类型：
 * - message: WhatsApp 消息（从 Node.js 发送到 Python）
 * - status: 状态更新（如"已连接"、"正在重连"）
 * - qr: 二维码数据（用于 WhatsApp 登录）
 * - error: 错误信息
 * - send: 发送命令（从 Python 发送到 Node.js）
 */

import { WebSocketServer, WebSocket } from 'ws';
import { WhatsAppClient, InboundMessage } from './whatsapp.js';

/**
 * 发送命令接口 - 从 Python 后端发送到 Node.js 桥接服务
 */
interface SendCommand {
  type: 'send';      // 命令类型：发送消息
  to: string;        // 目标电话号码或群 ID
  text: string;      // 消息文本内容
}

/**
 * 桥接消息接口 - 从 Node.js 桥接服务发送到 Python 后端
 */
interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error';  // 消息类型
  [key: string]: unknown;                        // 其他任意字段
}

/**
 * 桥接服务器类
 *
 * 功能：
 * 1. 创建 WebSocket 服务器供 Python 后端连接
 * 2. 初始化 WhatsApp 客户端（使用 Baileys 库）
 * 3. 转发 WhatsApp 消息到 Python 后端
 * 4. 接收 Python 后端的发送命令并执行
 */
export class BridgeServer {
  // WebSocket 服务器实例
  private wss: WebSocketServer | null = null;
  // WhatsApp 客户端实例
  private wa: WhatsAppClient | null = null;
  // 已连接的 WebSocket 客户端集合（通常只有一个 Python 客户端）
  private clients: Set<WebSocket> = new Set();

  /**
   * 创建桥接服务器
   * @param port - WebSocket 服务器端口
   * @param authDir - WhatsApp 认证目录
   * @param token - 可选的认证令牌
   */
  constructor(private port: number, private authDir: string, private token?: string) {}

  /**
   * 启动桥接服务器
   *
   * 启动流程：
   * 1. 创建 WebSocket 服务器并监听端口
   * 2. 初始化 WhatsApp 客户端
   * 3. 设置 WebSocket 连接处理器
   * 4. 连接到 WhatsApp 网络
   */
  async start(): Promise<void> {
    // 仅绑定到本地回环地址，确保外部网络无法访问
    this.wss = new WebSocketServer({ host: '127.0.0.1', port: this.port });
    console.log(`🌉 Bridge server listening on ws://127.0.0.1:${this.port}`);
    if (this.token) console.log('🔒 Token authentication enabled');

    // 初始化 WhatsApp 客户端
    // 配置三个回调函数：收到消息、收到二维码、状态变化
    this.wa = new WhatsAppClient({
      authDir: this.authDir,
      onMessage: (msg) => this.broadcast({ type: 'message', ...msg }),  // 收到消息时广播给 Python
      onQR: (qr) => this.broadcast({ type: 'qr', qr }),                  // 收到二维码时广播给 Python
      onStatus: (status) => this.broadcast({ type: 'status', status }),  // 状态变化时广播给 Python
    });

    // 处理 WebSocket 连接
    this.wss.on('connection', (ws) => {
      if (this.token) {
        // 需要认证握手：客户端必须在 5 秒内发送正确的 token
        const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
        ws.once('message', (data) => {
          clearTimeout(timeout);
          try {
            const msg = JSON.parse(data.toString());
            if (msg.type === 'auth' && msg.token === this.token) {
              console.log('🔗 Python client authenticated');
              this.setupClient(ws);
            } else {
              ws.close(4003, 'Invalid token');
            }
          } catch {
            ws.close(4003, 'Invalid auth message');
          }
        });
      } else {
        // 无需 token，直接允许连接
        console.log('🔗 Python client connected');
        this.setupClient(ws);
      }
    });

    // 连接到 WhatsApp 网络
    await this.wa.connect();
  }

  /**
   * 设置 WebSocket 客户端
   *
   * 功能：
   * 1. 将客户端添加到集合中
   * 2. 监听消息事件（接收 Python 后端的发送命令）
   * 3. 监听关闭事件（客户端断开连接）
   * 4. 监听错误事件（客户端异常）
   *
   * @param ws - WebSocket 客户端实例
   */
  private setupClient(ws: WebSocket): void {
    // 添加到客户端集合
    this.clients.add(ws);

    // 监听来自 Python 的消息
    // Python 发送的命令格式：{ type: 'send', to: '1234567890', text: 'Hello' }
    ws.on('message', async (data) => {
      try {
        const cmd = JSON.parse(data.toString()) as SendCommand;
        await this.handleCommand(cmd);
        // 发送确认响应
        ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
      } catch (error) {
        console.error('Error handling command:', error);
        ws.send(JSON.stringify({ type: 'error', error: String(error) }));
      }
    });

    // 监听客户端断开连接
    ws.on('close', () => {
      console.log('🔌 Python client disconnected');
      this.clients.delete(ws);
    });

    // 监听 WebSocket 错误
    ws.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.clients.delete(ws);
    });
  }

  /**
   * 处理来自 Python 后端的命令
   *
   * 支持的命令：
   * - send: 发送 WhatsApp 消息到指定号码或群
   *
   * @param cmd - 命令对象
   */
  private async handleCommand(cmd: SendCommand): Promise<void> {
    if (cmd.type === 'send' && this.wa) {
      await this.wa.sendMessage(cmd.to, cmd.text);
    }
  }

  /**
   * 广播消息到所有已连接的 Python 客户端
   *
   * 用于发送：
   * - WhatsApp 收到消息
   * - 二维码更新
   * - 连接状态变化
   * - 错误信息
   *
   * @param msg - 要广播的消息对象
   */
  private broadcast(msg: BridgeMessage): void {
    const data = JSON.stringify(msg);
    for (const client of this.clients) {
      // 只发送到状态为 OPEN 的客户端
      if (client.readyState === WebSocket.OPEN) {
        client.send(data);
      }
    }
  }

  /**
   * 停止桥接服务器
   *
   * 清理流程：
   * 1. 关闭所有 WebSocket 客户端连接
   * 2. 清空客户端集合
   * 3. 关闭 WebSocket 服务器
   * 4. 断开 WhatsApp 连接
   */
  async stop(): Promise<void> {
    // 关闭所有客户端连接
    for (const client of this.clients) {
      client.close();
    }
    this.clients.clear();

    // 关闭 WebSocket 服务器
    if (this.wss) {
      this.wss.close();
      this.wss = null;
    }

    // 断开 WhatsApp 连接
    if (this.wa) {
      await this.wa.disconnect();
      this.wa = null;
    }
  }
}
