# uu-term-mcp

把 UU 远程的 `uuyc-cli term` 包成 MCP 工具，让 Claude 直接在被控电脑（默认"穿墙"）的 PowerShell 里执行命令。
单文件 `server.py`，stdio 协议，除 Windows 上的 `pywinpty` 外没有第三方依赖。

## 工具

| 工具 | 作用 |
|---|---|
| `uu_device_list` | 列出账号下设备（名称、ID、在线状态） |
| `uu_exec` | 在被控端 PowerShell 里执行命令/脚本，返回退出码和输出；`command` 必填，`device`（ID 或名称，默认穿墙）、`timeout_s`（默认 60，最大 600）可选 |
| `uu_sessions` | 列出被控端已有终端会话（JSON） |
| `uu_kill_session` | 结束指定名字的终端会话（只清理自己建的 `mcp*`） |

每次 `uu_exec` 都会新建一个随机名字的会话（`mcpxxxxxx`），跑完自动 `exit` 并 kill，不留残会话。命令内容会整体转成 Base64 的 `-EncodedCommand` 发送，所以引号、多行脚本、`$` 都不会被吃掉。命令上限 8000 字符。

## 前提

1. 本机 UU 远程主程序在运行并已登录（否则 `uuyc-cli` 退出码 2）。
2. 本机能找到 `uuyc-cli`：Windows 默认找 `C:\Program Files\NetEase\GameViewer\bin\uuyc-cli.exe`；装在别处就设环境变量 `UU_CLI`。
3. 被控端必须是 Windows（`term` 的限制），主控端 Windows / macOS 都行。
4. **本机正被别的设备远程控制时，连不出去**（报 "currently being remotely controlled"，工具会返回错误）。要先在 UU 里"断开所有远控"。
5. 建立终端连接会挤掉用户正在用的该设备的远程桌面。

## 安装（Windows）

依赖装在项目内的 `.pylib`，不动系统 Python（`.pylib` 已在 `.gitignore`，换机器要重装）：

```powershell
py -m pip install pywinpty --target <仓库目录>\.pylib
claude mcp add uu-term --scope user -e UU_CLI="<uuyc-cli.exe 的完整路径>" -e UU_PYLIB="<仓库目录>\.pylib" -- py -I <仓库目录>\server.py
```

## 安装（macOS，同步到 Mac）

1. 把整个 `uu-term-mcp` 文件夹放到 Mac 上（见下面"同步方式"）。
2. Mac 上装好 UU 远程并登录**同一个账号**（这样设备列表里才有"穿墙"），确认终端里能执行 `uuyc-cli device list`；找不到的话用 `which uuyc-cli` 或在 UU 安装目录里找，把完整路径填进 `UU_CLI`。
3. 注册（macOS 自带 `python3`，无需装依赖）：
   ```bash
   claude mcp add uu-term --scope user -e UU_CLI=/path/to/uuyc-cli -- python3 /path/to/uu-term-mcp/server.py
   ```
4. 自测：`python3 server.py --devices`，再 `python3 server.py --exec "hostname; whoami"`。

## 同步方式

- **推荐：放进 git 仓库**，两台机器 `git pull` 即可保持一致。这个目录目前不是 git 仓库，要建的话在目录里 `git init`，推到你自己的 GitHub 私有仓库。
- 或者用 UU 的"文件传输"、AirDrop、网盘直接拷贝（只有 `server.py` 和本文件）。
- 两台机器各自要执行一次 `claude mcp add`，MCP 配置不会随文件夹同步。

## 命令行自测

```
python server.py --devices
python server.py --exec "hostname; whoami"        # UU_TIMEOUT=120 可调超时
```

## 已验证 / 未验证

- 已验证：stdio 协议（initialize、tools/list、tools/call、错误返回）；用本地 PowerShell 代替远端验证了退出码、引号和多行命令、超时返回；**在真实"穿墙"上**用命令行 `--exec` 验证了：连接、换行保留、中文输出（含中文报错信息）、会话自动清理（跑完 `term ls` 显示无残留会话）。
- 输出靠 Base64 回传：远端终端是 VT 流，换行会被光标序列吃掉，直接读文本会丢行。
- 未验证：通过 Claude 实际调用 `uu_exec` 这一层（需要新会话加载 MCP）；macOS（pty 部分用的是标准库，与 Windows 分支不同）。
- 命令行里用 PowerShell 传带双引号的参数会被吃掉（5.1 的传参问题），自测时请用单引号包整条命令，或直接走 MCP。

## 已知限制

- 没有文件传输：`uuyc-cli` 没有这个命令。传文件用 UU 界面的"文件传输"，或让被控端 `git pull`。
- 不支持交互式命令（要输入密码、按 y 之类）；请加参数避开。
- 每次调用都重新建立会话，约需几秒到十几秒。
