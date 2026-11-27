# 使用说明

## 前提

当前适配目标为 **Windows x64** 与 **FlClash 0.8.93**（Flutter `3.41.9`）。控制端支持 **Python 3.11 / 3.12 / 3.13**。桥接版 GUI 必须已启动并完成初始化；普通上游安装包没有此控制接口。

> **当前版本 `0.2.0`**（协议版本 `protocol: 1`，兼容已安装的 `0.1.0` GUI 控制桥二进制）：新增 `doctor` / `health` 自检、25 项安全错误码精确诊断、`exit --wait` 退出确认、完整 MCP v2 `ToolAnnotations` 与模式枚举校验。

## 终端命令

在项目目录建立常驻 Python 虚拟环境后安装：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

以下命令通过本机 DPAPI 认证控制桥调用正在运行的 GUI：

```powershell
.\.venv\Scripts\flclash-control.exe doctor
.\.venv\Scripts\flclash-control.exe health
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
.\.venv\Scripts\flclash-control.exe exit --wait
```

全局可选参数：
- `--token-file <PATH>`（或环境变量 `FLCLASH_CONTROL_TOKEN_FILE`）：指定自定义 `gui-bridge.json` 路径。
- `--timeout <SECONDS>`（或环境变量 `FLCLASH_CONTROL_TIMEOUT`，默认 `45`）：设置单次控制请求超时秒数。

动作说明：
- `doctor`：综合检查本机状态文件、当前用户 DPAPI 解密能力、`127.0.0.1:47892/health` 连通性，以及状态文件记录的 PID 与活动桥进程 PID 是否一致（不输出任何明文令牌）。
- `stop`：停止代理端口监听但保留 GUI 与控制桥在线；`restart` 进入 FlClash 原生 Helper/IPC 重连流程并保持原运行或停止态；`show` 唤起已有窗口，不启动新进程。
- `exit`：保存设置后安排正常退出；加 `--wait`（默认最多等待 10 秒，可用 `--wait-timeout` 调整）会轮询 `/health` 直至控制桥关闭并返回 `"exited": true`。

命令输出标准 JSON，成功返回退出码 `0`，失败返回 `1`。TUN、系统代理和出站模式均通过 GUI 设置层持久化保存。外网连通性仍须结合网卡、路由和实际请求验证。

首次启用 TUN 或修复辅助服务时，FlClash 可能显示原生 UAC 权限请求，须由用户在桌面端确认。若命令超时，结果可能尚未确定，应先通过 `status` 检查 `operation_pending`、`active_action` 和 `pending_commands` 再决定是否重试。

## MCP 配置

客户端安装后提供独立入口脚本 `flclash-control-mcp.exe`（等价于 `python -m flclash_control.mcp_server`），采用 stdio 传输。以 Codex CLI 为例：

```powershell
codex mcp add flclash-control -- 'C:\Tools\FlClash-Control\.venv\Scripts\flclash-control-mcp.exe'
```

在 JSON 格式客户端（Claude Desktop、Cursor、Antigravity 等）中：

```json
{
  "mcpServers": {
    "flclash-control": {
      "command": "C:\\Tools\\FlClash-Control\\.venv\\Scripts\\flclash-control-mcp.exe",
      "args": []
    }
  }
}
```

共注册 **10 个 MCP 工具**：
- 只读诊断：`flclash_health`、`flclash_status`
- 状态与持久开关：`flclash_start`、`flclash_stop`、`flclash_restart_core`、`flclash_set_tun`、`flclash_set_system_proxy`、`flclash_set_mode`
- 窗口与退出：`flclash_show_window`、`flclash_exit`（支持 `wait_for_exit: bool = False`）

所有工具均附带 MCP v2 `ToolAnnotations`（`read_only_hint`、`destructive_hint`、`idempotent_hint`、`open_world_hint=False`），无需在配置文件中写入任何令牌。

## 与 Mihomo MCP 配合

FlClash 基本配置中的“外部控制器”可提供 `127.0.0.1:9090` Mihomo API。现有通用 Mihomo MCP 项目适合查询节点、延迟测速、DNS、日志及活动连接，并切换具体代理节点。

Mihomo 的 `PATCH /configs` 只改当前内核运行内存，不会同步回 FlClash 界面设置；Mihomo `/restart` 也不等于本项目的原生 Helper/IPC 重连。因此：**界面持久开关与核心生命周期使用本项目，节点选择与网络诊断使用 Mihomo 工具**。切勿将 FlClash 数据目录配置给 Clash Verge 专用文件管理工具。

## 从源码构建 GUI 补丁

准备 Flutter `3.41.9`、FlClash `v0.8.93` 源码、目标应用安装目录及本项目 `integration/flclash/` 目录下的集成文件：

```powershell
git clone --branch v0.8.93 --depth 1 https://github.com/chen08209/FlClash.git .local\FlClash
```

在 `.local\FlClash` 中核对基线提交 `45015f856b44cb52cca755c04c885d73c45ae6b9`，按 [集成说明](../integration/flclash/README.md) 复制 `control_bridge.dart` 至 `lib/common/control_bridge.dart` 并应用 `integration.patch`。保留上游 `pubspec.lock`、锁定子模块与生成的插件注册文件后，执行可复现 AOT 构建脚本：

```powershell
.\scripts\build_aot.ps1 `
  -SourcePath '.local\FlClash' `
  -FlutterRoot 'C:\SDK\flutter-3.41.9' `
  -InstalledFlClashPath 'C:\Apps\FlClash' `
  -OutputDirectory '.local\artifacts'
```

脚本强制核对 Flutter 引擎修订 `42d3d75a56efe1a2e9902f52dc8006099c45d937` 与已安装 `flutter_windows.dll` 的 SHA-256（已验证目标哈希 `92e7aa320afe026e90780e4049dc6f6a480696400a269c179b1cca0ef751d175`），不一致时立即终止，防止混用不同引擎版本的 `app.so` 与 `DLL`。脚本只产出 `app-enabled.so` 和 `build-manifest.json`，不自动覆盖安装目录。

## 安装与恢复原则

替换前先正常退出 FlClash，备份原 `data\app.so` 及用户设置并记录 SHA-256。不要覆盖 `FlClashCore.exe`、网卡驱动或用户订阅文件。如需回退或移除桥接能力，先正常退出客户端，保留新产生的订阅/配置变更后再恢复原版 `data\app.so` 备份。

## 认证与排障

每次 GUI 启动生成全新随机令牌，经当前 Windows 用户 DPAPI 加密后保存在 `%LOCALAPPDATA%\FlClash-Control\gui-bridge.json`。如遇连接报错，优先运行 `flclash-control doctor` 区分：
- `token_file_present=false`：尚未启动带控制桥的兼容版 FlClash；
- `dpapi_authorized=false`：跨 Windows 账户运行或状态文件损坏；
- `bridge_reachable=false`：FlClash 已退出（残留意向旧 PID 状态文件）或 `47892` 端口未监听；
- `pid_matches=false`：端口被非当前状态文件对应的进程占用。
