/**
 * WhatsApp 客户端包装器 - 使用 Baileys 库
 *
 * 这个文件实现了 WhatsAppClient 类，用于：
 * 1. 连接到 WhatsApp Web（通过 Baileys 库）
 * 2. 处理扫码登录（二维码显示在终端）
 * 3. 接收和发送消息
 * 4. 自动重连（断线后自动恢复）
 *
 * 基于 OpenClaw 的成功实现。
 *
 * Baileys 库简介：
 * --------------
 * Baileys 是一个轻量级的 WhatsApp Web API 库，特点：
 * - 无需 Puppeteer 等重型依赖
 * - 支持多线程/多设备
 * - 自动处理加密和认证
 * - 支持群组、媒体消息等高级功能
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
// 导入 Baileys 库的主要函数
// makeWASocket: 创建 WhatsApp Socket 连接
// DisconnectReason: 断开连接的原因枚举
// useMultiFileAuthState: 多设备认证状态管理
// fetchLatestBaileysVersion: 获取最新的 Baileys 版本
// makeCacheableSignalKeyStore: 创建可缓存的密钥存储
// downloadMediaMessage: 下载媒体消息
// extractMessageContent: 提取消息内容
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
  downloadMediaMessage,
  extractMessageContent as baileysExtractMessageContent,
} from '@whiskeysockets/baileys';

// 导入 Boom 错误处理库（用于解析错误状态码）
import { Boom } from '@hapi/boom';
// 导入二维码生成库（在终端显示二维码）
import qrcode from 'qrcode-terminal';
// 导入 Pino 日志库（Baileys 需要）
import pino from 'pino';
// 导入文件系统模块（用于保存认证信息）
import { writeFile, mkdir } from 'fs/promises';
// 导入路径模块
import { join } from 'path';
// 导入加密模块（生成随机消息 ID）
import { randomBytes } from 'crypto';

// 桥接服务版本号
const VERSION = '0.1.0';

/**
 * 入站消息接口 - 从 WhatsApp 接收到的消息
 */
export interface InboundMessage {
  id: string;           // 消息唯一标识符
  sender: string;       // 发送者 ID
  pn: string;           // 发送者电话号码
  content: string;      // 消息文本内容
  timestamp: number;    // 时间戳（毫秒）
  isGroup: boolean;     // 是否为群聊消息
  media?: string[];     // 可选的媒体 URL 数组
}

/**
 * WhatsApp 客户端配置选项
 */
export interface WhatsAppClientOptions {
  authDir: string;                              // 认证目录（存储登录凭证）
  onMessage: (msg: InboundMessage) => void;     // 收到消息时的回调
  onQR: (qr: string) => void;                   // 收到二维码时的回调
  onStatus: (status: string) => void;           // 状态变化时的回调
}

/**
 * WhatsApp 客户端类
 *
 * 功能：
 * 1. 连接 WhatsApp 网络（使用 Baileys 库）
 * 2. 处理扫码登录
 * 3. 接收消息并转发到回调函数
 * 4. 发送消息到指定号码
 * 5. 自动重连（断线后自动恢复）
 */
export class WhatsAppClient {
  // Baileys Socket 实例
  private sock: any = null;
  // 配置选项
  private options: WhatsAppClientOptions;
  // 是否正在重连中（防止重复重连）
  private reconnecting = false;

  /**
   * 创建 WhatsApp 客户端
   * @param options - 配置选项
   */
  constructor(options: WhatsAppClientOptions) {
    this.options = options;
  }

  /**
   * 连接到 WhatsApp 网络
   *
   * 连接流程：
   * 1. 创建日志记录器（静默模式）
   * 2. 加载认证状态（从 authDir 目录）
   * 3. 获取最新的 Baileys 版本
   * 4. 创建 Socket 连接
   * 5. 注册事件处理器
   */
  async connect(): Promise<void> {
    // 创建静默日志记录器（不输出 Baileys 的内部日志）
    const logger = pino({ level: 'silent' });
    // 加载认证状态（包括凭证和密钥）
    const { state, saveCreds } = await useMultiFileAuthState(this.options.authDir);
    // 获取 Baileys 最新版本
    const { version } = await fetchLatestBaileysVersion();

    console.log(`Using Baileys version: ${version.join('.')}`);

    // 创建 Socket 连接（遵循 OpenClaw 的模式）
    this.sock = makeWASocket({
      auth: {
        creds: state.creds,                    // 认证凭证
        keys: makeCacheableSignalKeyStore(state.keys, logger),  // 密钥存储
      },
      version,                                  // Baileys 版本
      logger,                                   // 日志记录器
      printQRInTerminal: false,                 // 不自动打印二维码（我们手动处理）
      browser: ['nanobot', 'cli', VERSION],     // 浏览器标识
      syncFullHistory: false,                   // 不同步完整历史
      markOnlineOnConnect: false,               // 连接时不标记为在线
    });

    // 处理 WebSocket 错误
    if (this.sock.ws && typeof this.sock.ws.on === 'function') {
      this.sock.ws.on('error', (err: Error) => {
        console.error('WebSocket error:', err.message);
      });
    }

    // 处理连接状态更新
    // 这个事件处理器会接收：二维码、连接状态、断开原因等
    this.sock.ev.on('connection.update', async (update: any) => {
      const { connection, lastDisconnect, qr } = update;

      // 收到二维码：显示在终端并通知回调
      if (qr) {
        console.log('\n📱 Scan this QR code with WhatsApp (Linked Devices):\n');
        qrcode.generate(qr, { small: true });
        this.options.onQR(qr);
      }

      // 连接关闭：判断是否需要重连
      if (connection === 'close') {
        // 从错误对象中提取状态码
        const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
        // 除了"已登出"外，其他情况都尝试重连
        const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

        console.log(`Connection closed. Status: ${statusCode}, Will reconnect: ${shouldReconnect}`);
        this.options.onStatus('disconnected');

        // 需要重连且当前不在重连中
        if (shouldReconnect && !this.reconnecting) {
          this.reconnecting = true;
          console.log('Reconnecting in 5 seconds...');
          setTimeout(() => {
            this.reconnecting = false;
            this.connect();
          }, 5000);
        }
      } else if (connection === 'open') {
        // 连接成功
        console.log('✅ Connected to WhatsApp');
        this.options.onStatus('connected');
      }
    });

    // 保存认证凭证更新
    // 当凭证发生变化时（如刷新 token），自动保存到文件
    this.sock.ev.on('creds.update', saveCreds);

    // 处理收到的消息
    // messages.upsert 事件：当有新消息或消息更新时触发
    this.sock.ev.on('messages.upsert', async ({ messages, type }: { messages: any[]; type: string }) => {
      // 只处理 notify 类型的消息（新消息通知）
      if (type !== 'notify') return;

      for (const msg of messages) {
        // 跳过自己发送的消息
        if (msg.key.fromMe) continue;
        // 跳过状态广播（WhatsApp Status）
        if (msg.key.remoteJid === 'status@broadcast') continue;

        // 提取消息内容
        const unwrapped = baileysExtractMessageContent(msg.message);
        if (!unwrapped) continue;

        // 获取文本内容
        const content = this.getTextContent(unwrapped);
        let fallbackContent: string | null = null;
        const mediaPaths: string[] = [];

        // 处理图片消息
        if (unwrapped.imageMessage) {
          fallbackContent = '[Image]';
          const path = await this.downloadMedia(msg, unwrapped.imageMessage.mimetype ?? undefined);
          if (path) mediaPaths.push(path);
        } else if (unwrapped.documentMessage) {
          fallbackContent = '[Document]';
          const path = await this.downloadMedia(msg, unwrapped.documentMessage.mimetype ?? undefined,
            unwrapped.documentMessage.fileName ?? undefined);
          if (path) mediaPaths.push(path);
        } else if (unwrapped.videoMessage) {
          fallbackContent = '[Video]';
          const path = await this.downloadMedia(msg, unwrapped.videoMessage.mimetype ?? undefined);
          if (path) mediaPaths.push(path);
        }

        const finalContent = content || (mediaPaths.length === 0 ? fallbackContent : '') || '';
        if (!finalContent && mediaPaths.length === 0) continue;

        const isGroup = msg.key.remoteJid?.endsWith('@g.us') || false;

        // 构建入站消息对象并通知回调
        this.options.onMessage({
          id: msg.key.id || '',
          sender: msg.key.remoteJid || '',
          pn: msg.key.remoteJidAlt || '',
          content: finalContent,
          timestamp: msg.messageTimestamp as number,
          isGroup,
          ...(mediaPaths.length > 0 ? { media: mediaPaths } : {}),
        });
      }
    });
  }

  /**
   * 下载媒体文件
   *
   * 流程：
   * 1. 创建媒体目录（~/.nanobot/whatsapp-auth/media）
   * 2. 下载媒体到内存缓冲区
   * 3. 生成唯一文件名（带时间戳和随机前缀）
   * 4. 保存到文件系统
   *
   * @param msg - Baileys 消息对象
   * @param mimetype - MIME 类型（可选）
   * @param fileName - 文件名（可选，仅文档消息有）
   * @returns 保存的文件路径，失败返回 null
   */
  private async downloadMedia(msg: any, mimetype?: string, fileName?: string): Promise<string | null> {
    try {
      // 媒体文件保存目录
      const mediaDir = join(this.options.authDir, '..', 'media');
      await mkdir(mediaDir, { recursive: true });

      // 下载媒体到内存缓冲区
      const buffer = await downloadMediaMessage(msg, 'buffer', {}) as Buffer;

      let outFilename: string;
      if (fileName) {
        // 文档消息有文件名 - 添加唯一前缀防止冲突
        const prefix = `wa_${Date.now()}_${randomBytes(4).toString('hex')}_`;
        outFilename = prefix + fileName;
      } else {
        // 从 MIME 类型推导扩展名（如 "image/png" → ".png"）
        const mime = mimetype || 'application/octet-stream';
        const ext = '.' + (mime.split('/').pop()?.split(';')[0] || 'bin');
        outFilename = `wa_${Date.now()}_${randomBytes(4).toString('hex')}${ext}`;
      }

      const filepath = join(mediaDir, outFilename);
      await writeFile(filepath, buffer);

      return filepath;
    } catch (err) {
      console.error('Failed to download media:', err);
      return null;
    }
  }

  /**
   * 从 Baileys 消息对象中提取文本内容
   *
   * 检查顺序：
   * 1. conversation - 普通文本消息
   * 2. extendedTextMessage - 扩展文本（包含回复、链接预览等）
   * 3. imageMessage.caption - 图片配文
   * 4. videoMessage.caption - 视频配文
   * 5. documentMessage.caption - 文档配文
   * 6. audioMessage - 语音消息（返回固定文本）
   *
   * @param message - Baileys 消息对象
   * @returns 文本内容，如果没有文本则返回 null
   */
  private getTextContent(message: any): string | null {
    // 普通文本消息
    if (message.conversation) {
      return message.conversation;
    }

    // 扩展文本（包含回复、链接预览等元数据）
    if (message.extendedTextMessage?.text) {
      return message.extendedTextMessage.text;
    }

    // 图片消息（可能有配文）
    if (message.imageMessage) {
      return message.imageMessage.caption || '';
    }

    // 视频消息（可能有配文）
    if (message.videoMessage) {
      return message.videoMessage.caption || '';
    }

    // 文档消息（可能有配文）
    if (message.documentMessage) {
      return message.documentMessage.caption || '';
    }

    // 语音/音频消息
    if (message.audioMessage) {
      return `[Voice Message]`;
    }

    return null;
  }

  /**
   * 发送消息到指定的 WhatsApp 号码或群
   *
   * @param to - 目标号码（格式：国家码 + 号码，如 "8613800000000"）或群 ID（以 "@g.us" 结尾）
   * @param text - 消息文本内容
   * @throws 如果未连接则抛出错误
   */
  async sendMessage(to: string, text: string): Promise<void> {
    if (!this.sock) {
      throw new Error('Not connected');
    }

    await this.sock.sendMessage(to, { text });
  }

  /**
   * 断开 WhatsApp 连接
   *
   * 调用此方法会：
   * 1. 结束 WebSocket 连接
   * 2. 清空 sock 引用
   */
  async disconnect(): Promise<void> {
    if (this.sock) {
      this.sock.end(undefined);
      this.sock = null;
    }
  }
}
