<!--
来源：SECURITY.md
翻译日期：2026-03-13
-->

# 安全政策

## 报告漏洞

如果你在 nanobot 中发现安全漏洞，请通过以下方式报告：

1. **不要** 公开创建 GitHub Issue
2. 在 GitHub 上创建私人安全公告或联系仓库维护者 (xubinrencs@gmail.com)
3. 包含以下信息：
   - 漏洞描述
   - 复现步骤
   - 潜在影响
   - 建议的修复方案（如果有）

我们目标在 48 小时内响应安全报告。

## 安全最佳实践

### 1. API 密钥管理

**关键**：永远不要将 API 密钥提交到版本控制系统。

```bash
# ✅ 良好做法：存储在配置文件中并设置受限权限
chmod 600 ~/.nanobot/config.json

# ❌ 错误做法：在代码中硬编码密钥或提交它们
```

**建议：**
- 将 API 密钥存储在 `~/.nanobot/config.json` 中，文件权限设置为 `0600`
- 考虑使用环境变量存储敏感密钥
- 生产环境部署使用操作系统密钥环/凭据管理器
- 定期轮换 API 密钥
- 开发和生产环境使用不同的 API 密钥

### 2. 渠道访问控制

**重要**：生产环境务必配置 `allowFrom` 列表。

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789", "987654321"]
    },
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

**安全说明：**
- 在 `v0.1.4.post3` 及更早版本中，空的 `allowFrom` 允许所有用户访问。自 `v0.1.4.post4` 起，空的 `allowFrom` 默认拒绝所有访问 —— 设置为 `["*"]` 显式允许所有人。
- 通过 `@userinfobot` 获取你的 Telegram 用户 ID
- WhatsApp 使用带有国家代码的完整电话号码
- 定期审查访问日志，查找未授权的访问尝试

### 3. Shell 命令执行

`exec` 工具可以执行 shell 命令。虽然危险的命令模式已被阻止，但你应该：

- ✅ 审查 agent 日志中的所有工具使用
- ✅ 理解 agent 正在运行的命令
- ✅ 使用具有有限权限的专用用户账户
- ✅ 永远不要以 root 身份运行 nanobot
- ❌ 不要禁用安全检查
- ❌ 不要在没有仔细审查的情况下在包含敏感数据的系统上运行

**被阻止的模式：**
- `rm -rf /` - 根文件系统删除
- Fork 炸弹
- 文件系统格式化 (`mkfs.*`)
- 原始磁盘写入
- 其他破坏性操作

### 4. 文件系统访问

文件操作具有路径遍历保护，但：

- ✅ 使用专用用户账户运行 nanobot
- ✅ 使用文件系统权限保护敏感目录
- ✅ 定期审计日志中的文件操作
- ❌ 不要对敏感文件授予无限制的访问权限

### 5. 网络安全

**API 调用：**
- 所有外部 API 调用默认使用 HTTPS
- 配置超时以防止请求挂起
- 如果需要，考虑使用防火墙限制出站连接

**WhatsApp 桥接服务：**
- 桥接服务绑定到 `127.0.0.1:3001`（仅限本地回环，外部网络无法访问）
- 在配置中设置 `bridgeToken` 以启用 Python 和 Node.js 之间的共享密钥认证
- 保持 `~/.nanobot/whatsapp-auth` 中的认证数据安全（权限模式 0700）

### 6. 依赖安全

**关键**：保持依赖项更新！

```bash
# 检查易受攻击的依赖项
pip install pip-audit
pip-audit

# 更新到最新的安全版本
pip install --upgrade nanobot-ai
```

对于 Node.js 依赖项（WhatsApp 桥接服务）：
```bash
cd bridge
npm audit
npm audit fix
```

**重要说明：**
- 保持 `litellm` 更新到最新版本以获取安全修复
- 我们已更新 `ws` 到 `>=8.17.1` 以修复 DoS 漏洞
- 定期运行 `pip-audit` 或 `npm audit`
- 订阅 nanobot 及其依赖项的安全公告

### 7. 生产环境部署

生产环境使用：

1. **隔离环境**
   ```bash
   # 在容器或虚拟机中运行
   docker run --rm -it python:3.11
   pip install nanobot-ai
   ```

2. **使用专用用户**
   ```bash
   sudo useradd -m -s /bin/bash nanobot
   sudo -u nanobot nanobot gateway
   ```

3. **设置适当的权限**
   ```bash
   chmod 700 ~/.nanobot
   chmod 600 ~/.nanobot/config.json
   chmod 700 ~/.nanobot/whatsapp-auth
   ```

4. **启用日志记录**
   ```bash
   # 配置日志监控
   tail -f ~/.nanobot/logs/nanobot.log
   ```

5. **使用速率限制**
   - 在 API 提供商处配置速率限制
   - 监控使用情况以查找异常
   - 在 LLM API 上设置支出限制

6. **定期更新**
   ```bash
   # 每周检查更新
   pip install --upgrade nanobot-ai
   ```

### 8. 开发与生产环境

**开发环境：**
- 使用独立的 API 密钥
- 使用非敏感数据进行测试
- 启用详细日志记录
- 使用测试 Telegram 机器人

**生产环境：**
- 使用带有支出限制的专用 API 密钥
- 限制文件系统访问
- 启用审计日志记录
- 定期安全审查
- 监控异常活动

### 9. 数据隐私

- **日志可能包含敏感信息** - 妥善保管日志文件
- **LLM 提供商会看到你的提示** - 审查他们的隐私政策
- **聊天记录本地存储** - 保护 `~/.nanobot` 目录
- **API 密钥明文存储** - 生产环境使用操作系统密钥环

### 10. 事件响应

如果你怀疑发生安全漏洞：

1. **立即吊销被泄露的 API 密钥**
2. **审查日志查找未授权的访问**
   ```bash
   grep "Access denied" ~/.nanobot/logs/nanobot.log
   ```
3. **检查意外的文件修改**
4. **轮换所有凭据**
5. **更新到最新版本**
6. **向维护者报告事件**

## 安全特性

### 内置安全控制

✅ **输入验证**
- 文件操作的路径遍历保护
- 危险命令模式检测
- HTTP 请求的输入长度限制

✅ **认证**
- 基于白名单的访问控制 —— 在 `v0.1.4.post3` 及更早版本中空 `allowFrom` 允许所有访问；自 `v0.1.4.post4` 起拒绝所有访问（`["*"]` 显式允许所有访问）
- 失败的身份验证尝试记录

✅ **资源保护**
- 命令执行超时（默认 60 秒）
- 输出截断（10KB 限制）
- HTTP 请求超时（10-30 秒）

✅ **安全通信**
- 所有外部 API 调用使用 HTTPS
- Telegram API 使用 TLS
- WhatsApp 桥接服务：仅限本地回环绑定 + 可选的令牌认证

## 已知限制

⚠️ **当前的安全限制：**

1. **无速率限制** - 用户可以发送无限数量的消息（根据需要自行添加）
2. **明文配置** - API 密钥以明文形式存储（生产环境使用密钥环）
3. **无会话管理** - 无自动会话过期
4. **有限的命令过滤** - 仅阻止明显的危险模式
5. **无审计追踪** - 有限的安全事件日志记录（根据需要增强）

## 安全检查清单

部署 nanobot 之前：

- [ ] API 密钥安全存储（不在代码中）
- [ ] 配置文件权限设置为 0600
- [ ] 所有渠道都配置了 `allowFrom` 列表
- [ ] 以非 root 用户身份运行
- [ ] 文件系统权限适当限制
- [ ] 依赖项更新到最新安全版本
- [ ] 监控日志中的安全事件
- [ ] API 提供商配置了速率限制
- [ ] 备份和灾难恢复计划到位
- [ ] 自定义技能/工具的安全审查

## 更新

**最后更新**：2026-02-03

查看最新的安全更新和公告：
- GitHub 安全公告：https://github.com/HKUDS/nanobot/security/advisories
- 发布说明：https://github.com/HKUDS/nanobot/releases

## 许可证

详见 LICENSE 文件。

---

## 英文原版

```markdown
# Security Policy
[... full English original content ...]
```
