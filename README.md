# FlClash Control

[![CI](https://github.com/TH0RGOODMAN/flclash-control/actions/workflows/tests.yml/badge.svg)](https://github.com/TH0RGOODMAN/flclash-control/actions/workflows/tests.yml)
[![Release](https://img.shields.io/github/v/release/TH0RGOODMAN/flclash-control?include_prereleases&label=release)](https://github.com/TH0RGOODMAN/flclash-control/releases)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![MCP SDK](https://img.shields.io/badge/MCP%20SDK-v2-6e56cf)](pyproject.toml)
[![License: GPL v3+](https://img.shields.io/badge/license-GPLv3%2B-blue)](LICENSE)

简体中文 · **[English Documentation](README.en.md)**

**通过命令行（CLI）与 MCP 直接控制运行中的 FlClash Windows 客户端——界面保持正常运行，开关状态实时写回并持久化，无需模拟鼠标或键盘。**

[功能对比](#为什么不直接用-mihomo-api) · [快速开始](#快速开始) · [工具与命令](#mcp-工具与-cli-命令) · [使用与构建文档](docs/usage.md) · [补丁集成说明](integration/flclash/README.md) · [实测记录](docs/validation.md) · [更新日志](CHANGELOG.md)

---

## 为什么不直接用 Mihomo API？

在日常桌面代理诊断与 AI 自动化排障中，直接请求 `127.0.0.1:9090` 的 Mihomo REST API 存在三项界面级断层：

| 能力维度 | Mihomo REST API (`:9090`) | 桌面键鼠模拟 (UI Automation) | **FlClash Control (`:47892`)** |
|---|---|---|---|
| 修改模式 / TUN 后同步回 FlClash 界面 | 否（仅改内核内存，界面重应用即被覆盖） | 是，但依赖窗口焦点与坐标 | **是（直接驱动 Riverpod 状态并落盘保存）** |
| 控制 Windows 系统代理开关 | 否（由 FlClash 原生插件管理） | 易受弹窗/最小化干扰 | **是（串行调用并等待原生代理插件完成）** |
| 原生 Helper / IPC 核心重连 | 否（`/restart` 不重建 Helper/IPC 通道） | 需点开界面菜单 | **是（复用客户端原生重连并校验配置与监听就绪）** |
| 后台静默运行、不抢占键鼠焦点 | 是 | 否 | **是（纯本地回环认证通信）** |

因此：**界面级持久开关、系统代理与原生核心重连使用 `FlClash Control`**；节点列表、延迟测速、DNS 查询与连接日志可继续配合通用 Mihomo API / MCP 工具使用。

### 架构设计

```text
AI Host / Terminal (flclash-control CLI & stdio MCP)
   │  Windows DPAPI 解密当前用户令牌 (%LOCALAPPDATA%\FlClash-Control\gui-bridge.json)
   │  POST http://127.0.0.1:47892/command (禁代理、禁重定向、拒绝浏览器 Origin/Fetch 头)
   ▼
FlClash GUI 内置 ControlBridge (Dart, 串行变更队列 + 无阻塞 status/health)
   ├── Riverpod Providers & Preferences ──► 界面开关实时同步并持久化保存
   ├── Native Proxy Plugin Queue        ──► Windows 系统代理可靠启停
   └── Strict Helper / IPC Controller   ──► 等待配置写入与端口监听双 Future 完成并传播错误
```

---

## MCP 工具与 CLI 命令

提供 **10 个带完整 `ToolAnnotations` 的 stdio MCP 工具**与对应的 `flclash-control` 子命令：

| MCP 工具 | CLI 命令 | 属性 | 功能说明 |
|---|---|---|---|
| `flclash_health` | `doctor` / `health` | 只读 | 检查本机 DPAPI 令牌可用性、控制桥连通性及状态文件 PID 与活动进程是否一致 |
| `flclash_status` | `status` | 只读 | 读取核心连接状态、监听运行态、模式、TUN/系统代理开关及待执行队列（权限等待期间不阻塞） |
| `flclash_start` | `start` | 幂等变更 | 启动代理监听并同步当前界面配置 |
| `flclash_stop` | `stop` | 幂等变更 | 停止代理监听，保留 FlClash 界面与控制桥继续运行 |
| `flclash_restart_core` | `restart` | 生命周期 | 走 FlClash 原生 Helper/IPC 重连流程并恢复原先的运行或停止状态 |
| `flclash_set_tun` | `tun on\|off` | 幂等变更 | 开启或关闭界面 TUN 开关（触发原生权限检查并持久化） |
| `flclash_set_system_proxy` | `system-proxy on\|off` | 幂等变更 | 开启或关闭 Windows 系统代理开关并持久化 |
| `flclash_set_mode` | `mode rule\|global\|direct` | 幂等变更 | 切换出站路由模式（Schema 严格枚举校验）并持久化 |
| `flclash_show_window` | `show` | 幂等窗口 | 唤起已有 FlClash 主窗口，不注入桌面输入 |
| `flclash_exit` | `exit [--wait]` | 退出进程 | 保存当前设置后正常退出客户端与内核；支持 `--wait` / `wait_for_exit` 等待进程完全关闭 |

---

## 快速开始

> [!IMPORTANT]
> 官方原版 FlClash 安装包不包含本地控制桥接口，单独安装本仓库 Python 包无法控制未打补丁的客户端。当前版本固定适配 **Windows x64 + `chen08209/FlClash` `v0.8.93`（Flutter `3.41.9`）**，构建与替换步骤见 [集成说明](integration/flclash/README.md) 与 [使用指南](docs/usage.md)。

### 1. 安装 Python 控制端（CLI & MCP）

启动带控制桥的兼容版 FlClash 后，在独立虚拟环境中安装控制端：

```powershell
git clone https://github.com/TH0RGOODMAN/flclash-control.git
cd flclash-control
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

常用终端命令：

```powershell
.\.venv\Scripts\flclash-control.exe doctor
.\.venv\Scripts\flclash-control.exe status
.\.venv\Scripts\flclash-control.exe tun on
.\.venv\Scripts\flclash-control.exe system-proxy off
.\.venv\Scripts\flclash-control.exe mode rule
.\.venv\Scripts\flclash-control.exe restart
```

### 2. 接入 MCP 客户端

在 Claude Desktop、Cursor、Antigravity 或 Codex 的 MCP 配置中添加（无需在配置中填写任何密钥或令牌）：

```json
{
  "mcpServers": {
    "flclash-control": {
      "command": "C:\\Tools\\flclash-control\\.venv\\Scripts\\flclash-control-mcp.exe",
      "args": []
    }
  }
}
```

可选环境变量：`FLCLASH_CONTROL_TIMEOUT`（自定义请求超时秒数，默认 `45`）、`FLCLASH_CONTROL_TOKEN_FILE`（自定义状态文件路径）。

---

## 安全边界与完成语义

- **本机同用户 DPAPI 鉴权**：控制桥仅绑定 `127.0.0.1:47892`；每次 GUI 启动生成全新 256 位随机 Bearer 令牌，经 Windows DPAPI 当前用户加密写入 `%LOCALAPPDATA%\FlClash-Control\gui-bridge.json`。服务端采用常量时间比对，并拒绝任何携带浏览器 `Origin` 或 `Sec-Fetch-Site` 头的跨站本地请求。
- **脱敏错误码白名单**：服务端与客户端均不回显订阅链接、节点名称或明文令牌；Python 客户端仅映射 25 个固定安全错误码（如 `tun_authorization_or_apply_failed`、`command_queue_full`），兼顾可诊断性与零敏感泄露。
- **原生权限与超时准则**：首次提权或修复服务触发的 Windows UAC 弹窗仍须用户在桌面确认。请求超时并不代表后台动作已取消，重试前应先调用 `status` / `flclash_status` 检查 `operation_pending` 与当前状态。

---

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build
```

- 完整命令、AOT 复现构建与备份恢复流程：[docs/usage.md](docs/usage.md)
- Python / Dart 自动化测试、GitHub Actions 补丁兼容性校验与实机网络验收记录：[docs/validation.md](docs/validation.md)

## 许可证与声明

本项目为独立的非官方扩展，与 FlClash 官方无隶属或背书关系。代码按 **[GPL-3.0-or-later](LICENSE)** 许可发布；分发包含本项目控制桥补丁的修改版二进制时，请保留上游版权与许可证声明并提供对应源码。
