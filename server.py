#!/usr/bin/env python3
"""UU 远程终端 MCP 服务（stdio）。

把 `uuyc-cli term` 包成几个工具，让 Claude 直接在被控电脑（默认"穿墙"）的 PowerShell 里执行命令。
`term new` 要求交互式终端，所以这里用 pywinpty 提供的伪终端驱动。
MCP 协议（stdio、换行分隔的 JSON-RPC）直接手写，除 pywinpty 外没有第三方依赖。

平台支持：主控端 Windows → 被控端 Windows。
macOS 版 uuyc-cli（1.0.0）的 `term` 只能打开终端列表界面，没有远程执行命令的接口，
因此在 macOS 上只有 uu_device_list 可用，其余工具会返回说明性错误。

环境变量：
  UU_CLI              uuyc-cli 的完整路径（默认自动找）
  UU_DEFAULT_DEVICE   默认设备的 ID 或名称（默认设备名「穿墙」）
  UU_PYLIB            额外加入 sys.path 的目录（Windows 上 pywinpty 装在别处时用）

命令行自测：
  python server.py --devices
  python server.py --exec "hostname; whoami"
"""
import base64
import json
import os
import platform
import random
import re
import shutil
import string
import subprocess
import sys
import threading
import time

IS_WIN = platform.system() == "Windows"
if os.environ.get("UU_PYLIB"):
    sys.path.insert(0, os.environ["UU_PYLIB"])

DEFAULT_DEVICE = os.environ.get("UU_DEFAULT_DEVICE", "穿墙")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
PROMPT = re.compile(r"PS\s*[A-Za-z]:\\[^\n]*?>")
DEVICE_ID = re.compile(r"^[a-z0-9]{16}$")
MAX_COMMAND = 8000
MAX_OUTPUT = 30000


def find_cli():
    env = os.environ.get("UU_CLI")
    if env and os.path.exists(env):
        return env
    found = shutil.which("uuyc-cli")
    if found:
        return found
    if IS_WIN:
        candidates = [r"C:\Program Files\NetEase\GameViewer\bin\uuyc-cli.exe"]
    else:
        candidates = ["/usr/local/bin/uuyc-cli", "/opt/homebrew/bin/uuyc-cli"]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise RuntimeError("找不到 uuyc-cli：请设置环境变量 UU_CLI 为它的完整路径，并确认 UU 远程主程序已运行并登录")


def decode(raw):
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def run_cli(args, timeout=60):
    done = subprocess.run([find_cli(), *args], capture_output=True, timeout=timeout)
    return done.returncode, decode(done.stdout) + decode(done.stderr)


def list_devices():
    code, out = run_cli(["device", "list"], 30)
    devices = []
    try:
        data = json.loads(out)
        for d in data["data"]["devices"]:
            devices.append({"name": d["deviceName"], "id": d["deviceId"],
                            "status": "online" if d.get("isOnline") else "offline"})
        return code, out, devices
    except (ValueError, KeyError, TypeError):
        devices = []
    for line in out.splitlines():
        m = re.match(r"^(.*?) \(([a-z0-9]{16})\): (\w+)\s*$", line.strip())
        if m:
            devices.append({"name": m.group(1), "id": m.group(2), "status": m.group(3)})
    return code, out, devices


def resolve_device(device):
    device = (device or DEFAULT_DEVICE).strip()
    if DEVICE_ID.match(device):
        return device
    _code, _out, devices = list_devices()
    for d in devices:
        if d["name"] == device:
            return d["id"]
    raise RuntimeError("设备不存在：%s（用 uu_device_list 看一下名字或 ID）" % device)


def require_windows():
    if not IS_WIN:
        raise RuntimeError(
            "当前平台（%s）暂不支持远程执行：macOS 版 uuyc-cli 的 `term` 只能打开终端界面，"
            "没有创建会话/执行命令的接口。该功能目前仅支持 Windows 主控端。" % platform.system())


def kill_session(device_id, name):
    try:
        run_cli(["term", "-d", device_id, "kill", name], 30)
    except Exception:
        pass


class Pty:
    """跨平台伪终端：后台线程持续读输出，攒在 self.text 里。"""

    def __init__(self, argv):
        self.chunks = []
        self.lock = threading.Lock()
        self.dead = False
        if IS_WIN:
            from winpty import PtyProcess
            self.proc = PtyProcess.spawn(argv, dimensions=(40, 200))
        else:
            import fcntl
            import pty
            import struct
            import termios
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 200, 0, 0))
            self.proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, start_new_session=True, close_fds=True)
            os.close(slave)
            self.master = master
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while True:
            try:
                if IS_WIN:
                    s = self.proc.read(4096)
                else:
                    s = os.read(self.master, 4096).decode("utf-8", errors="replace")
            except Exception:
                break
            if s:
                with self.lock:
                    self.chunks.append(s)
            else:
                time.sleep(0.05)
        self.dead = True

    def text(self):
        with self.lock:
            raw = "".join(self.chunks)
        return ANSI.sub("", raw).replace("\r\n", "\n").replace("\r", "\n")

    def write(self, data):
        if IS_WIN:
            self.proc.write(data)
        else:
            os.write(self.master, data.encode("utf-8"))

    def wait_for(self, regex, timeout, start=0):
        end = time.time() + timeout
        while time.time() < end:
            m = regex.search(self.text(), start)
            if m:
                return m
            if self.dead:
                break
            time.sleep(0.1)
        return regex.search(self.text(), start)

    def close(self):
        try:
            if IS_WIN:
                self.proc.terminate(force=True)
            else:
                self.proc.kill()
                os.close(self.master)
        except Exception:
            pass


def exec_remote(command, device=None, timeout=60):
    require_windows()
    if len(command) > MAX_COMMAND:
        raise RuntimeError("命令太长（%d 字符，上限 %d）：请拆成多条，或让被控端用 git 拉脚本再执行" % (len(command), MAX_COMMAND))
    timeout = max(5, min(int(timeout), 600))
    device_id = resolve_device(device)
    cli = find_cli()
    name = "mcp" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    token = "".join(random.choices(string.ascii_lowercase, k=8))
    pty = Pty([cli, "term", "-d", device_id, "new", name, "--shell", "powershell"])
    try:
        if not pty.wait_for(PROMPT, 45):
            banner = pty.text().strip()[-600:]
            raise RuntimeError("没等到远端 PowerShell 提示符（设备离线、本机正被远程控制或 UU 没登录？）。已收到：%s" % banner)
        # 命令输出整体转成 UTF-8 的 Base64 再回传：远端终端是 VT 流，换行会被光标移动序列吃掉，中文编码也不可靠
        script = (
            "$__o = & {\n%(c)s\n"
            "$global:__ec = if ($?) { 0 } else { 1 }\n"
            "if ($LASTEXITCODE -ne $null -and $LASTEXITCODE -ne 0) { $global:__ec = $LASTEXITCODE }\n"
            "} 2>&1 | Out-String -Width 300\n"
            "$__b = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($__o))\n"
            "Write-Output ('__UU_'+'B_%(t)s:'+$global:__ec+':'+$__b+':'+'__UU_'+'E_%(t)s')\n" % {"t": token, "c": command}
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        before = len(pty.text())
        pty.write("powershell -NoProfile -EncodedCommand %s\r\n" % encoded)
        done_re = re.compile(r"__UU_B_%s:(\d+):([A-Za-z0-9+/=\s]*?):__UU_E_%s" % (token, token))
        m = pty.wait_for(done_re, timeout, before)
        timed_out = m is None
        if m:
            code = int(m.group(1))
            body = base64.b64decode(re.sub(r"\s+", "", m.group(2))).decode("utf-8", errors="replace").replace("\r\n", "\n")
        else:
            code = None
            body = "（超时，没有收到完整输出）"
        body = body.strip("\n")
        truncated = len(body) > MAX_OUTPUT
        if truncated:
            body = "…（前面被截断）\n" + body[-MAX_OUTPUT:]
        return {"exit_code": code, "timed_out": timed_out, "output": body}
    finally:
        try:
            pty.write("exit\r\n")
        except Exception:
            pass
        pty.close()
        kill_session(device_id, name)


TOOLS = [
    {
        "name": "uu_device_list",
        "description": "列出 UU 远程账号下的设备（名称、ID、在线状态）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "uu_exec",
        "description": (
            "在被控电脑（默认「穿墙」）的 PowerShell 里执行命令并返回输出和退出码。命令真的会在对方电脑上执行，"
            "破坏性操作（删除、改系统设置、装卸软件）要先问用户。注意：建立终端连接会挤掉用户正在用的该设备的远程桌面；"
            "本机正被别的设备远控时连不出去。输出里的中文可能乱码，必要时只看 ASCII 部分。目前仅支持 Windows 主控端。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell 命令或多行脚本（不超过 %d 字符）" % MAX_COMMAND},
                "device": {"type": "string", "description": "设备 ID 或名称，默认穿墙"},
                "timeout_s": {"type": "integer", "description": "等待命令完成的秒数，默认 60，最大 600"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "uu_sessions",
        "description": "列出被控电脑上已有的终端会话（JSON）。别人的会话不要动。",
        "inputSchema": {"type": "object", "properties": {"device": {"type": "string"}}},
    },
    {
        "name": "uu_kill_session",
        "description": "结束被控电脑上指定名字的终端会话。只用于清理自己建的以 mcp 开头的会话。",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "device": {"type": "string"}},
            "required": ["name"],
        },
    },
]


def call_tool(name, args):
    if name == "uu_device_list":
        code, out, devices = list_devices()
        return json.dumps({"exit_code": code, "devices": devices}, ensure_ascii=False, indent=2)
    if name == "uu_exec":
        result = exec_remote(args["command"], args.get("device"), args.get("timeout_s", 60))
        head = "exit_code=%s%s\n" % (result["exit_code"], "（超时，输出可能不完整）" if result["timed_out"] else "")
        return head + result["output"]
    if name == "uu_sessions":
        require_windows()
        code, out = run_cli(["term", "-d", resolve_device(args.get("device")), "ls", "--json"], 60)
        start = out.find("{")
        return out[start:] if start >= 0 else out
    if name == "uu_kill_session":
        require_windows()
        code, out = run_cli(["term", "-d", resolve_device(args.get("device")), "kill", args["name"]], 30)
        return out.strip().splitlines()[-1] if out.strip() else "exit=%s" % code
    raise RuntimeError("未知工具：%s" % name)


def serve():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            version = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": version, "capabilities": {"tools": {}},
                "serverInfo": {"name": "uu-term", "version": "0.1.0"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            try:
                text, error = call_tool(params.get("name"), params.get("arguments") or {}), False
            except Exception as exc:
                text, error = "错误：%s" % exc, True
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": error}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--devices":
        print(call_tool("uu_device_list", {}))
    elif len(sys.argv) > 2 and sys.argv[1] == "--exec":
        print(call_tool("uu_exec", {"command": sys.argv[2], "timeout_s": int(os.environ.get("UU_TIMEOUT", "60"))}))
    else:
        serve()
