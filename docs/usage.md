# 使用说明

## 前提

当前目标是 Windows x64 和 FlClash 0.8.93。客户端需要 Python 3.11 或更高版本；本机验证环境使用 Python 3.12。桥接版 GUI 必须已启动并完成初始化，普通上游安装包没有此控制接口。

> **版本 0.1.0：本机验收通过（2026-11-16）。** TUN、系统代理、出站模式往返，运行/停止状态下原生重连，正常退出重开及偏好保存均已验证。当前仍是面向固定版本的实验扩展。

## 终端命令

在项目目录建立独立环境后安装：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

以下命令通过本机认证控制桥调用正在运行的 GUI：

```powershell
.\.venv\Scripts\flclash-control.exe status
.\.venv\Scripts\flclash-control.exe start
.\.venv\Scripts\flclash-control.exe stop
.\.venv\Scripts\flclash-control.exe restart
.\.venv\Scripts\flclash-control.exe tun on
.\.venv\Scripts\flclash-control.exe tun off
.\.venv\Scripts\flclash-control.exe system-proxy on
.\.venv\Scripts\flclash-control.exe system-proxy off
.\.venv\Scripts\flclash-control.exe mode rule
.\.venv\Scripts\flclash-control.exe mode global
.\.venv\Scripts\flclash-control.exe mode direct
.\.venv\Scripts\flclash-control.exe show
.\.venv\Scripts\flclash-control.exe exit
```

`stop` 停止监听但保留 GUI；`restart` 进入 FlClash 原生重连流程；`show` 显示已有窗口，不启动新进程。`exit` 保存设置后安排正常退出，回复中的 `exit_scheduled` 表示退出已安排，仍需观察进程结束。退出后控制桥不可用，应先重新启动 GUI。

命令输出 JSON，成功返回零退出码，失败返回非零。TUN、系统代理和模式通过 GUI 设置层保存。网络访问是否成功仍须结合网卡、路由和实际请求验证。

首次启用 TUN 或修复辅助服务时，FlClash 可能显示原生权限请求。用户须处理该请求；工具不会自动点击 UAC。若命令超时，结果可能尚未确定，应检查状态与权限窗口再重试，避免重复触发重连。

`status` 可在变更命令等待权限时直接查询。`operation_pending`、`active_action` 和 `pending_commands` 表示尚未完成的操作；这时的开关值是中间快照。原生重连等待配置与监听启动完成，控制路径会传播失败。当前验收未实际拒绝 UAC，失败传播通过针对性测试检查。

## MCP 配置

客户端安装后，MCP 入口为 `flclash-control-mcp`，采用 stdio。以 Codex 为例：

```powershell
codex mcp add flclash-control -- 'C:\Tools\FlClash-Control\.venv\Scripts\python.exe' -m flclash_control.mcp_server
```

把示例路径改为实际独立环境路径。注册后按宿主的加载方式重新连接或开启新聊天。可用工具为：

- `flclash_status`
- `flclash_start`
- `flclash_stop`
- `flclash_restart_core`
- `flclash_set_tun`
- `flclash_set_system_proxy`
- `flclash_set_mode`
- `flclash_show_window`
- `flclash_exit`

只读状态工具带有 read-only 标记，其他工具会改变本机应用状态。它们使用相同客户端认证，不需要在 MCP 配置中填写令牌。

## 与 Mihomo MCP 配合

FlClash 基本配置中的“外部控制器”可提供 `127.0.0.1:9090` Mihomo API。现有 MCP 项目可以查询节点、测速、DNS、日志及连接，并选择代理节点。

Mihomo 的 `PATCH /configs` 只改当前内核运行状态，不自动写回 FlClash 界面设置；后续 GUI 应用配置可能覆盖它。Mihomo `/restart` 也不等于本项目的原生 Helper/IPC 重连。因此，持久设置和内核生命周期使用本项目，节点与网络诊断使用适用的 Mihomo 工具。

不要把 FlClash 数据目录设置成 Clash Verge 文件层的目录。两个客户端的配置结构不同，Clash Verge 专用订阅、合并、规则文件工具不适用。

## 从源码构建 GUI 补丁

先准备 Flutter 3.41.9、FlClash v0.8.93 源码、目标应用安装目录，以及项目提供的集成文件：

```powershell
git clone --branch v0.8.93 --depth 1 https://github.com/chen08209/FlClash.git .local\FlClash
```

在 `.local\FlClash` 中固定基线提交 `45015f856b44cb52cca755c04c885d73c45ae6b9`，按 [集成说明](../integration/flclash/README.md) 复制控制桥、应用 `integration.patch`。保留上游 `pubspec.lock`，不要升级依赖；还需获取锁定的 tray-manager 子模块及生成 Dart 插件注册文件。

集成测试文件另放在 `integration/flclash/`，可复制进上游 `test/core/` 后使用 `flutter test`。本项目的 GitHub workflow 只运行 Windows Python 客户端测试；它不构建 GUI，也不代替 TUN 和系统代理的本机验收。

SDK、包依赖及生成文件准备完成后，使用 AOT 脚本：

```powershell
.\scripts\build_aot.ps1 `
  -SourcePath '.local\FlClash' `
  -FlutterRoot 'C:\SDK\flutter-3.41.9' `
  -InstalledFlClashPath 'C:\Apps\FlClash' `
  -OutputDirectory '.local\artifacts'
```

脚本要求 Flutter 引擎修订为 `42d3d75a56efe1a2e9902f52dc8006099c45d937`，比较 SDK 与现有应用的 `flutter_windows.dll` SHA256。已验证目标引擎哈希为 `92e7aa320afe026e90780e4049dc6f6a480696400a269c179b1cca0ef751d175`。不匹配会停止构建，不能组合不同引擎的 AOT 和 DLL。

此路线只编译 Dart AOT，保留目标版本的 runner、原生插件、内核与 Helper。成品包含 `app-enabled.so` 和 `build-manifest.json`，清单记录成品、引擎、内核和源码哈希。脚本已在目标版本复现，但不会安装成品；部署仍需单独备份和运行验收。

## 安装与恢复原则

安装前正常退出 FlClash，备份现有 `data\app.so`、将被修改的 assets 和设置，记录文件哈希。只安装已经核对兼容性的成品；不要覆盖核心可执行文件、驱动或用户订阅。

出现启动失败时，先正常退出修改版，保留本次成品和设置，再恢复对应 AOT/asset 备份。后来更新的订阅或设置应按字段合并，不能整份覆盖。构建清单中 `installation_performed=false` 仅表示构建脚本没有安装，不能作为部署成功证明。

移除 MCP 注册可执行：

```powershell
codex mcp remove flclash-control
```

取消桥功能应恢复原版 GUI 产物，或构建时不启用 `FLCLASH_CONTROL`。关闭 Mihomo 的 9090 外部控制器不会关闭 GUI 原生桥，它们是两个接口。

## 认证与排障

每次 GUI 启动生成新令牌，DPAPI 密文位于 `%LOCALAPPDATA%\FlClash-Control\gui-bridge.json`。客户端自动在当前 Windows 用户上下文解密；不要打印明文、复制到聊天或提交此本机状态文件。切换 Windows 用户运行客户端会导致认证失败。

`GET http://127.0.0.1:47892/health` 可读取桥名称、协议和 GUI PID，不返回凭据。控制请求需要认证。服务器拒绝浏览器 Origin/Fetch Metadata、非预期 Host、非本机来源和过大请求。

若显示“bridge unavailable”，先确认运行的是桥接版、应用已完成初始化、47892 没有被其他程序占用。认证失败可等待 GUI 完成启动后查询状态。命令失败时工具不会回显响应正文、令牌或订阅，详细问题应结合应用现场和测试记录定位。

最终验收应完成状态、TUN 往返、系统代理往返、模式往返、原生重连、正常退出重开和偏好保存检查，并在系统代理关闭时验证 HTTPS 连通性。未经实际检查，不应将“开关已保存”写成“外网正常”。
