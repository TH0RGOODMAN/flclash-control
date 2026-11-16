# FlClash Control

用命令行（CLI）和 MCP 控制 FlClash，界面（GUI）照常运行。开关设置写回界面并保存，重连直接走客户端原生流程，无需模拟鼠标或键盘。当前仅支持 Windows x64。

[功能](#功能) · [开始使用](#开始使用) · [使用与构建文档](docs/usage.md) · [FlClash 集成说明](integration/flclash/README.md) · [实测记录](docs/validation.md)

## 功能

- **状态查询**：读取代理运行状态、内核连接状态、当前模式、TUN 与系统代理开关，以及是否有待执行（`pending`）的操作。
- **启停与原生重连**：启动或停止代理监听（停止代理不会关闭界面）；`restart` 调用 FlClash 原生的 Helper/IPC 重连流程，并保持原来的运行或停止状态。
- **界面设置同步**：开启或关闭 TUN、开启或关闭系统代理、切换 `rule` / `global` / `direct` 模式，修改后直接更新界面开关并保存到配置。
- **窗口与退出**：唤起已有主窗口，或保存当前设置后正常退出程序。
- **MCP 服务**：提供 9 个 stdio MCP 工具，供支持 MCP 的 AI 客户端直接调用。

### 与 Mihomo API 的区别

直接通过 Mihomo API 修改运行模式或 TUN，只作用于内核运行时，不会同步回 FlClash 界面，重启后设置也会丢失；Windows 系统代理则由 FlClash 界面的原生插件管理，Mihomo API 无法直接控制；此外，Mihomo 的 `restart` 并不等同于 FlClash 原生的 Helper/IPC 重连。

FlClash Control 通过客户端内的本地控制桥补齐上述界面级操作。节点切换、测速、DNS 和日志查询，可继续使用 Mihomo API 或通用 MCP 工具。

## 开始使用

使用前须先从源码构建并安装带控制桥的兼容版 FlClash；官方原版安装包没有控制接口，单独安装本仓库的 Python 包无法工作。当前版本为 `0.1.0`（实验性），适配 Windows x64、FlClash `0.8.93`（Flutter `3.41.9`），构建与安装步骤见 [集成说明](integration/flclash/README.md) 与 [使用文档](docs/usage.md)。

### 1. 命令行安装与使用

启动带控制桥的 FlClash 后，克隆本仓库并安装 Python 控制端：

```powershell
git clone https://github.com/TH0RGOODMAN/flclash-control.git
cd flclash-control
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

常用命令示例：

```powershell
.\.venv\Scripts\flclash-control.exe status
.\.venv\Scripts\flclash-control.exe restart
.\.venv\Scripts\flclash-control.exe tun on
.\.venv\Scripts\flclash-control.exe system-proxy off
```

`mode`、`show`、`exit` 等其余命令与参数说明见 [docs/usage.md](docs/usage.md)。

### 2. 配置 MCP 客户端

在 MCP 客户端配置中添加以下服务（请将 `command` 路径改为本机实际位置）：

```json
{
  "mcpServers": {
    "flclash-control": {
      "command": "C:\\Tools\\flclash-control\\.venv\\Scripts\\python.exe",
      "args": ["-m", "flclash_control.mcp_server"]
    }
  }
}
```

配置中无需填写令牌。接入后可直接让 AI 执行操作，例如：“读取 FlClash 状态；如果内核连接失效，用原生流程重连后再检查状态。”

## 连接与权限

控制桥仅监听本机 `127.0.0.1:47892`。每次 FlClash 启动时生成随机授权令牌，令牌由 Windows DPAPI 加密保存，本机同用户下的命令行与 MCP 客户端会自动读取。

控制桥对请求大小与待执行队列长度做了限制，变更操作按顺序执行。涉及系统权限的操作（如 Windows UAC 提权弹窗）仍需用户在桌面端手动确认。

## 验证与开发文档

本项目已通过 Python 与 Dart 单元测试，并完成命令行/MCP 往返控制、界面退出重开持久化及网卡路由连通性实测。

- 构建步骤、完整命令与故障恢复：[docs/usage.md](docs/usage.md)
- 测试范围与实测记录：[docs/validation.md](docs/validation.md)

## 许可证与声明

本项目为独立的非官方扩展，与 FlClash 官方无隶属关系。代码按 **GPL-3.0-or-later** 许可发布；分发包含本项目的修改版时，请保留上游许可声明并提供对应源码。
