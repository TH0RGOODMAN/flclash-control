# FlClash Control v0.1.0

用命令行和 MCP 控制正在运行的 FlClash Windows 客户端，界面照常运行，无需模拟键鼠。

### 主要能力

- **状态与生命周期**：读取运行状态、连接状态与开关项；支持启停代理监听、调用 FlClash 原生 Helper/IPC 重连、唤起窗口及保存设置后正常退出。
- **界面设置同步**：修改 TUN、系统代理及 `rule` / `global` / `direct` 模式，直接同步至界面并持久化保存。
- **MCP 支持**：提供 9 个 stdio MCP 工具，通过本机 `127.0.0.1:47892` 通信，自动使用本机授权，MCP 配置不需填写令牌。

### 开始使用与版本范围

当前实验性版本面向 **Windows x64**，固定适配 **FlClash 0.8.93**（Flutter `3.41.9`）。官方安装包不包含控制桥接口，使用前须先构建并安装兼容版 FlClash，再安装本仓库 Python 包。

- 构建、安装与完整命令：https://github.com/TH0RGOODMAN/flclash-control/blob/main/docs/usage.md
- 补丁集成说明：https://github.com/TH0RGOODMAN/flclash-control/blob/main/integration/flclash/README.md
- 实测记录与边界：https://github.com/TH0RGOODMAN/flclash-control/blob/main/docs/validation.md
