# uu-term-mcp

基于 UU 远程命令行工具 `uuyc-cli` 的 MCP（Model Context Protocol）服务，使 Claude 等 AI 客户端可以在远端 Windows 电脑的 PowerShell 中执行命令并获取输出与退出码。

单文件实现（`server.py`），stdio 传输，MCP 协议部分自行实现，唯一第三方依赖是 Windows 上的 [`pywinpty`](https://github.com/andfoy/pywinpty)。

## 平台支持

| 主控端（运行本服务） | 被控端 | 状态 |
|---|---|---|
| Windows | Windows | ✅ 支持，已在真实设备上验证 |
| macOS | Windows | ⚠️ 仅支持设备列表（`uu_device_list`），暂不支持远程执行 |
| 任意 | macOS / Linux | ❌ UU 远程终端功能本身要求被控端为 Windows |

**macOS 主控端的限制原因：** macOS 版 `uuyc-cli`（1.0.0，UU 远程 4.44.0）的 `term` 子命令仅提供 `open` / `exit`，作用是在 UU 主程序中打开某设备的终端列表界面，不提供创建会话、发送命令、读取输出的接口；`lterm` 管理的是本机终端会话。因此无法通过 CLI 在 macOS 上驱动远程终端。待 UU 官方补充相应接口后再行适配。

## 工具

| 工具 | 说明 | macOS |
|---|---|---|
| `uu_device_list` | 列出账号下设备（名称、ID、在线状态） | ✅ |
| `uu_exec` | 在被控端 PowerShell 中执行命令或脚本，返回退出码与输出。参数：`command`（必填）、`device`（ID 或名称，默认「穿墙」）、`timeout_s`（默认 60，最大 600） | ❌ |
| `uu_sessions` | 列出被控端已有终端会话（JSON） | ❌ |
| `uu_kill_session` | 结束指定名称的终端会话（仅用于清理本服务创建的 `mcp*` 会话） | ❌ |

每次 `uu_exec` 调用都会新建一个随机名称的会话（`mcpxxxxxx`），执行完毕后自动 `exit` 并 kill，不遗留会话。命令内容整体转为 Base64 的 `-EncodedCommand` 发送，引号、多行脚本、`$` 均不会被转义破坏；命令长度上限 8000 字符。

## 前提条件

1. 本机已安装 UU 远程主程序并登录，且主程序处于运行状态（否则 `uuyc-cli` 退出码为 2）。
2. 能找到 `uuyc-cli`：Windows 默认路径为 `C:\Program Files\NetEase\GameViewer\bin\uuyc-cli.exe`，安装在其他位置时设置环境变量 `UU_CLI`。
3. 被控端为 Windows 系统。
4. 本机正被其他设备远程控制时无法发起终端连接（报 "currently being remotely controlled"），需先在 UU 中断开所有远控。
5. 建立终端连接会挤掉被控端当前正在使用的远程桌面连接。

## 安装（Windows）

依赖安装在项目内的 `.pylib` 目录，不影响系统 Python（该目录已列入 `.gitignore`，更换机器后需重新安装）：

```powershell
py -m pip install pywinpty --target <仓库目录>\.pylib
claude mcp add uu-term --scope user -e UU_CLI="<uuyc-cli.exe 的完整路径>" -e UU_PYLIB="<仓库目录>\.pylib" -- py -I <仓库目录>\server.py
```

注册后新开一个 Claude 会话，即可让它调用 `uu_exec`，例如："在穿墙上执行 `hostname`"。

## 安装（macOS，仅设备列表）

```bash
./install-mac.sh
```

脚本会检测 `uuyc-cli` 并注册 MCP。macOS 上仅 `uu_device_list` 可用，其余工具会返回说明性错误，见上文"平台支持"。

## 命令行自测

```
python server.py --devices
python server.py --exec "hostname; whoami"        # UU_TIMEOUT=120 可调超时（仅 Windows）
```

PowerShell 5.1 传参会吞掉双引号，自测时请用单引号包住整条命令，或直接通过 MCP 调用。

## 环境变量

| 变量 | 说明 |
|---|---|
| `UU_CLI` | `uuyc-cli` 的完整路径（默认自动查找） |
| `UU_DEFAULT_DEVICE` | 默认设备的 ID 或名称（默认「穿墙」） |
| `UU_PYLIB` | 额外加入 `sys.path` 的目录（`pywinpty` 安装在别处时使用） |

## 验证情况

- 已验证（Windows → Windows）：stdio 协议（`initialize`、`tools/list`、`tools/call`、错误返回）；在真实被控端上验证了连接、换行保留、中文输出（含中文报错信息）、退出码、超时返回、会话自动清理。
- 已验证（macOS）：`uu_device_list`；执行类工具的平台提示。
- 实现说明：输出通过 Base64 回传，因为远端终端是 VT 流，换行会被光标移动序列吞掉，直接读取文本会丢行。

## 已知限制

- 不支持文件传输（`uuyc-cli` 没有该命令）。传文件请使用 UU 界面的"文件传输"，或让被控端 `git pull`。
- 不支持交互式命令（输入密码、确认 y/n 等），请使用非交互参数。
- 每次调用都会重新建立会话，耗时数秒到十几秒。
- 输出中的中文在部分情况下可能出现乱码。

## 声明

本项目为个人项目，与网易及 UU 远程无隶属关系。UU 远程、`uuyc-cli` 的权利归其各自所有者。
