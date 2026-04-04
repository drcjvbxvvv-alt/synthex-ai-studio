"""project_brain/cli_serve.py — Server CLI commands (CLI-01)"""
import sys
import os
from pathlib import Path
from project_brain.cli_utils import (
    R, B, D, G, Y, RE, C, P, GR, W,
    _workdir, _ok, _err, _info,
)


def cmd_serve(args):
    """啟動 Project Brain API Server（L3 知識庫 + L1a Session Store）"""
    wd   = _workdir(args)
    port = args.port or 7891

    if getattr(args, 'mcp', False):
        print(f"\n{B}{C}🔌 Brain MCP Server 模式{R}")
        print(f"  {D}讓 Claude Code / Cursor / VS Code 直接連接 Project Brain{R}\n")
        print(f"  Claude Code 設定範例：")
        print(f"  {GR}{{")
        print(f'    "mcpServers": {{')
        print(f'      "project-brain": {{')
        print(f'        "command": "python",')
        print(f'        "args": ["-m", "project_brain.mcp_server"],')
        print(f'        "env": {{"BRAIN_WORKDIR": "{wd}"}}')
        print(f"      }}")
        print(f"    }}")
        print(f"  }}{R}\n")
        try:
            import sys as _sys
            _sys.argv = ['mcp_server', '--workdir', wd]
            from project_brain.mcp_server import main as _mcp_main
            _mcp_main()
        except ImportError as e:
            _err(f"MCP Server 需要安裝依賴：pip install mcp")
            _err(f"詳情：{e}")
            _info("或直接執行：python -m project_brain.mcp_server --workdir " + wd)
        return

    brain_dir = Path(wd) / '.brain'
    if not brain_dir.exists():
        _err(f"找不到 .brain 目錄，請先執行：brain init --workdir {wd}")
        return

    slack_wh = getattr(args, 'slack_webhook', None)
    if slack_wh:
        os.environ['BRAIN_SLACK_WEBHOOK_URL'] = slack_wh
        _info(f"Slack Webhook 已設定")

    from project_brain.api_server import run_server as _api_run

    _api_key  = os.environ.get('BRAIN_API_KEY', '') or os.environ.get('ANTHROPIC_API_KEY', '')
    bind_host = getattr(args, 'host', '0.0.0.0')
    production = getattr(args, 'production', False)
    workers    = getattr(args, 'workers', 4)

    if getattr(args, 'readonly', False):
        print(f"  {Y}唯讀模式 — 只允許查詢，寫入操作將被拒絕{R}")

    if production:
        print(f"\n  {G}⚡ Production 模式：Gunicorn {workers} workers{R}")
        try:
            import subprocess
            cmd = [
                "gunicorn",
                "--workers",      str(workers),
                "--worker-class", "gthread",
                "--threads",      "2",
                "--bind",         f"{bind_host}:{port}",
                "--timeout",      "30",
                "--access-logfile", "-",
                "--error-logfile",  "-",
                "brain:app",
            ]
            print(f"  {D}執行：{' '.join(cmd)}{R}\n")
            subprocess.execvp("gunicorn", cmd)
        except FileNotFoundError:
            _err("Gunicorn 未安裝：pip install gunicorn")
            _info("退回標準模式...")
            _api_run(workdir=wd, port=port, host=bind_host, api_key=_api_key,
                     readonly=getattr(args, 'readonly', False))
    else:
        _api_run(workdir=wd, port=port, host=bind_host, api_key=_api_key,
                 readonly=getattr(args, 'readonly', False))


def cmd_webui(args):
    """D3.js 知識圖譜視覺化（在瀏覽器驗證 add 的結果）"""
    wd   = _workdir(args)
    port = getattr(args, 'port', 7890)
    bd   = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，執行：brain setup"); return

    from project_brain.web_ui.server import run_server as _webui_run
    try:
        _webui_run(workdir=wd, port=port)
    except FileNotFoundError as e:
        _err(str(e))
    except Exception as e:
        _err(f"WebUI 啟動失敗：{e}")
