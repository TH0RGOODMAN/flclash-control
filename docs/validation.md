# 验收与测试说明

本项目区分自动化契约测试、上游补丁静态/单元检查与 Windows 实机往返验收。普通上游安装包不包含控制桥，实机使用须先安装与引擎严格匹配的集成构建。

## 自动化验证（`0.2.0`）

- **Python 客户端与 MCP 契约测试**：覆盖真实 Windows DPAPI 加解密、本机回环请求映射、25 个固定控制桥错误码映射、未知响应与密钥零回显、系统代理环境变量隔离、HTTP 重定向拒绝、响应体积上限、客户端前置参数校验、`health` / `doctor` PID 一致性诊断、`exit --wait` 轮询退出、CLI 参数解析与全部 10 个 MCP 工具的 Schema / `ToolAnnotations` / `ToolError` 包装。
- **GitHub Actions 持续集成**：
  - Windows `python-version` 矩阵（`3.11` / `3.12` / `3.13`）运行完整测试套件；
  - 构建 sdist 与 wheel，审计 wheel 包内文件列表并在全新隔离虚拟环境中验证安装；
  - 自动拉取上游 `chen08209/FlClash` `v0.8.93` 并执行 `git apply --check integration/flclash/integration.patch` 验证补丁无冲突。
- **Dart 原生层测试（`0.1.0` 控制桥基线）**：34 项测试通过（上游控制器 24 项、缺失原生 IPC 响应 6 项、配置与监听并发完成/失败时序 4 项），静态分析无告警。

## 实机运行验收结果

在 Windows x64、FlClash `0.8.93`、Flutter `3.41.9` 本机环境中已完成以下实测：

- **控制桥在线自检**：Python `3.13.11` 环境下实测 `doctor`、`health`、`status` 与 stdio MCP 握手、工具列举及调用通过，`state_pid` 与活动 GUI `bridge_pid` 一致。
- **开关往返与持久化（`0.1.0` 实机基线）**：
  - TUN、Windows 系统代理、`global` / `direct` / `rule` 模式往返与界面保存状态一致；系统代理已核对 Windows 注册表/系统设置，TUN 已核对 Meta Tunnel 网卡与路由表。
  - `stop` 后混合监听端口关闭而 GUI 与控制桥保持在线；`start` 后恢复端口监听与 TUN。
  - 运行态与停止态下的 `restart` 均走原生 Helper/IPC 重连并保持各自原状态。
  - 正常 `exit` 观察到进程退出，重开后模式与系统代理偏好持久保留。
  - 系统代理关闭、TUN 开启条件下，启用证书校验的直发 HTTPS 请求访问 Google `204`、YouTube `200`、百度 `200` 均正常。

## 可靠性设计要点

- 控制桥在后台或窗口隐藏期间保持 `realTunEnableProvider` 订阅存活，防止 Riverpod 自动释放临时授权状态造成误报。
- 原生 IPC 返回空值（`null`）时显式抛出异常，避免将超时误判为配置或监听成功。
- 严格启动/重连路径同时等待配置写入与监听启动两个 `Future` 并观察双方异常，失败时清理残留运行计时器。
- `status` 与 `/health` 绕过变更串行队列，在等待原生权限确认期间仍可无阻塞观测 `operation_pending`、`active_action` 与 `pending_commands`。

## 已知边界

- 当前仅针对 Windows x64 + FlClash `0.8.93`（上游提交 `45015f856b44cb52cca755c04c885d73c45ae6b9`、Flutter 引擎 `42d3d75a56efe1a2e9902f52dc8006099c45d937`、已验证 `app.so` SHA-256 `423a8666c2b0ae5c70160d8645c406cc50d73ad1e4094c00ce5313aa351da4eb`）完成单机实测，不承诺跨版本自动兼容。
- 现场弹窗点击“拒绝 UAC”及 Helper 服务彻底损坏后的端到端人工恢复未做破坏性现场演练（缺失响应与失败传播由单元测试覆盖）。
- 本项目为非官方扩展；分发包含集成补丁的 GUI 成品时须遵守 **GPL-3.0-or-later** 许可证并提供对应源码。
