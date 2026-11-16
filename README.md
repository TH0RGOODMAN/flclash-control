# FlClash Control

FlClash Control 是面向运行中 FlClash Windows 界面的独立扩展，通过命令行（CLI）与 stdio MCP 启停代理、切换 TUN 和系统代理、保存出站模式，以及原生重连内核。它直接对接 GUI 状态管理与动作层，无需注入鼠标或键盘事件。

本项目面向 **Windows x64 / FlClash 0.8.93**。普通上游安装包不包含控制桥；须先构建并安装兼容的 GUI 集成补丁，单独安装 Python 包不能接管原版客户端。

> **0.1.0 已完成本机验收（2026-11-16）。** CLI/MCP 启停、TUN 与系统代理往返、模式切换、原生重连、设置保存及退出重开均已验证。当前是面向固定版本的实验扩展。

## 为什么需要这个项目

FlClash 可以开启 Mihomo 外部控制器，已有 MCP 工具能查询节点、测速、检查 DNS，并修改内核运行状态。但运行时修改不会自动写回 FlClash 界面设置；Mihomo 的 `/restart` 也不同于 FlClash 原生的 Helper/IPC 重连。

本项目在 GUI 进程内加入认证控制桥，调用同一套 Riverpod 状态、系统代理插件和内核动作。界面继续运行，设置由 FlClash 自己保存，原生权限检查仍会执行。

## 功能

- 读取界面、内核、TUN、系统代理、出站模式与待完成操作状态。
- 使用原生动作启停代理监听，保持窗口可用。
- 原生重启内核，重新连接 Helper/IPC 并恢复运行状态。
- 设置并保存 TUN、系统代理和 `rule / global / direct` 模式。
- 显示已有窗口，或保存设置后正常退出应用。
- 提供九个 stdio MCP 工具，可与现有 Mihomo MCP 诊断工具配合使用。

节点选择、延迟、DNS、连接和日志可继续使用 [clash-verge-mcp-pro](https://github.com/cdxiaodong/clash-verge-mcp-pro) 的适用运行时工具；目标客户端已验证其 16 个工具的接入。Clash Verge 的文件管理工具不适用于 FlClash 数据目录。

## 快速使用

先安装桥接版 FlClash，启动并完成原生初始化，再安装客户端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\flclash-control.exe status
.\.venv\Scripts\flclash-control.exe tun on
.\.venv\Scripts\flclash-control.exe system-proxy off
.\.venv\Scripts\flclash-control.exe mode rule
.\.venv\Scripts\flclash-control.exe restart
```

完整命令、MCP 配置、构建及恢复方法见 [使用说明](docs/usage.md)。

## 控制桥

桥只监听 `127.0.0.1:47892`。每次 GUI 启动生成随机授权令牌，使用 Windows 当前用户 DPAPI 加密后保存；客户端在本地解密并发送认证请求。令牌不出现在命令行参数或文档中。

服务器拒绝跨来源浏览器请求，检查 Host 和 loopback 来源，限制请求大小，并串行执行控制动作。它只提供明确的控制命令，不提供任意文件、完整配置或通用 RPC 接口。应用退出时桥一并结束，重新启动会更换令牌。

原生重连等待配置与监听启动完成，失败会向客户端传递。权限提示仍由用户处理；等待期间 `status` 可读取中间状态。客户端超时表示结果尚未确定，应先检查待完成操作和原生提示再重试。

## 构建与兼容性

当前集成基线为 [FlClash v0.8.93](https://github.com/chen08209/FlClash/tree/v0.8.93)，提交 `45015f856b44cb52cca755c04c885d73c45ae6b9`，Flutter **3.41.9**。`integration/flclash/` 包含 Dart 控制桥及原生动作补丁。

[build_aot.ps1](scripts/build_aot.ps1) 编译 Dart AOT，检查源码版本、Flutter 引擎匹配及桥标记，输出成品和构建清单。脚本不停止应用、不安装成品，也不修改现有 FlClash。只有引擎匹配时才可复用现有 Windows runner、内核和原生 DLL；其他版本不能套用该安装方式。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest
```

客户端测试使用临时 DPAPI 数据与模拟 HTTP 传输，覆盖本机认证、环境代理隔离、重定向拒绝、异常脱敏和命令映射。运行验收还需核对 GUI、保存设置、实际网卡与路由，以及关闭系统代理后的 HTTPS 连通性；仅返回开关值不代表外网已可用。

本机验收包括 28 项客户端测试、34 项 Dart 测试及静态分析。运行/停止状态下的重连都保持原状态；停止后代理监听关闭，启动后恢复。正常退出重开后偏好保留；系统代理关闭、TUN 开启时，Google 返回 204，YouTube 和百度返回 200，HTTPS 证书校验开启。详细边界见 [验收说明](docs/validation.md)。

早期独立内核托管实验保留在 `experiments/headless/`，未部署、未完成验证，不属于支持的运行方式。

## 许可证

[GPL-3.0-or-later](LICENSE)。GUI 补丁基于 [chen08209/FlClash](https://github.com/chen08209/FlClash)，分发修改版时须保留上游许可证、声明及对应源码。本项目是独立扩展，不是 FlClash 官方发行版。
