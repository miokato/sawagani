"""launchd/systemd による Sawagani 常駐監視を扱う内部モジュール。"""

import hashlib
import os
import plistlib
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from . import settings


class CommandResult(Protocol):
    """subprocess.run の戻り値として必要な最小属性。"""

    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """外部コマンド実行を差し替えるための protocol。"""

    def __call__(self, argv: list[str]) -> CommandResult:
        """argv を実行し、returncode/stdout/stderr を返す。"""


@dataclass
class InstallResult:
    """install() の実行結果。"""

    installed: bool
    message: str
    backend: str
    label: str
    service_path: Path
    log_path: Path


@dataclass
class UninstallResult:
    """uninstall() の実行結果。"""

    stopped: bool
    message: str
    backend: str
    label: str
    service_path: Path


@dataclass
class SchedulerStatus:
    """OS 監視付き常駐ジョブの状態。"""

    registered: bool
    running: bool
    paused: bool
    message: str
    backend: str
    label: str
    service_path: Path
    log_path: Path


def run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """外部コマンドを実行する既定 runner。"""
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def select_backend() -> str:
    """実行OSに応じて監視バックエンドを選ぶ。"""
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "systemd"
    raise RuntimeError(f"unsupported platform for Sawagani scheduler: {sys.platform}")


def service_slug(data_dir: Path) -> str:
    """data_dir ごとに安定した短い識別子を返す。"""
    digest = hashlib.sha1(str(data_dir.resolve()).encode("utf-8")).hexdigest()
    return digest[:8]


def agent_label(data_dir: Path, backend: str | None = None) -> str:
    """OS ジョブの label/unit 名を返す。"""
    selected = backend or select_backend()
    slug = service_slug(data_dir)
    if selected == "launchd":
        return f"com.sawagani.{slug}"
    if selected == "systemd":
        return f"sawagani-{slug}.service"
    raise ValueError(f"unknown scheduler backend: {selected}")


def launchd_dir() -> Path:
    """LaunchAgent の配置ディレクトリを返す。"""
    return Path.home() / "Library" / "LaunchAgents"


def systemd_user_dir() -> Path:
    """systemd user unit の配置ディレクトリを返す。"""
    return Path.home() / ".config" / "systemd" / "user"


def launchd_service_path(data_dir: Path) -> Path:
    """LaunchAgent plist の配置パスを返す。"""
    return launchd_dir() / f"{agent_label(data_dir, 'launchd')}.plist"


def systemd_service_path(data_dir: Path) -> Path:
    """systemd user unit の配置パスを返す。"""
    return systemd_user_dir() / agent_label(data_dir, "systemd")


def build_launchd_plist(
    interval: int,
    python: str,
    path_env: str,
    data_dir: Path,
    log: Path,
    label: str,
) -> bytes:
    """LaunchAgent plist を plistlib で生成する。"""
    payload = {
        "Label": label,
        "ProgramArguments": [
            python,
            "-m",
            "sawagani",
            "serve",
            "--interval",
            str(interval),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 20,
        "WorkingDirectory": str(data_dir),
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "EnvironmentVariables": {
            settings.HOME_ENV: str(data_dir),
            "PATH": path_env,
        },
    }
    return plistlib.dumps(payload, sort_keys=False)


def systemd_quote(value: Path | str) -> str:
    """systemd unit の値として扱いやすいよう二重引用符で囲む。"""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def build_systemd_unit(interval: int, python: str, data_dir: Path) -> str:
    """systemd user service unit を生成する。"""
    return "\n".join(
        [
            "[Unit]",
            "Description=Sawagani heartbeat agent",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={shlex.quote(python)} -m sawagani serve --interval {interval}",
            "Restart=always",
            f"Environment={systemd_quote(f'{settings.HOME_ENV}={data_dir}')}",
            f"WorkingDirectory={systemd_quote(data_dir)}",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def backend_service_path(backend: str, data_dir: Path) -> Path:
    """backend に対応する service ファイルパスを返す。"""
    if backend == "launchd":
        return launchd_service_path(data_dir)
    if backend == "systemd":
        return systemd_service_path(data_dir)
    raise ValueError(f"unknown scheduler backend: {backend}")


def install(interval: int, runner: Runner = run_command) -> InstallResult:
    """OS 監視付き常駐ジョブを登録し、起動する。"""
    backend = select_backend()
    data_dir = settings.data_dir()
    log_path = settings.log_path()
    label = agent_label(data_dir, backend)
    service_path = backend_service_path(backend, data_dir)
    service_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if backend == "launchd":
        service_path.write_bytes(
            build_launchd_plist(
                interval=interval,
                python=sys.executable,
                path_env=os.environ.get("PATH", ""),
                data_dir=data_dir,
                log=log_path,
                label=label,
            )
        )
        service_path.chmod(0o600)
        domain = f"gui/{os.getuid()}"
        runner(["launchctl", "bootout", f"{domain}/{label}"])
        result = runner(["launchctl", "bootstrap", domain, str(service_path)])
        if result.returncode != 0:
            result = runner(["launchctl", "load", "-w", str(service_path)])
        return InstallResult(result.returncode == 0, "installed", backend, label, service_path, log_path)

    service_path.write_text(
        build_systemd_unit(interval=interval, python=sys.executable, data_dir=data_dir),
        encoding="utf-8",
    )
    runner(["systemctl", "--user", "daemon-reload"])
    result = runner(["systemctl", "--user", "enable", "--now", label])
    return InstallResult(result.returncode == 0, "installed", backend, label, service_path, log_path)


def uninstall(runner: Runner = run_command) -> UninstallResult:
    """OS 監視付き常駐ジョブを解除する。未登録でも冪等に返す。"""
    backend = select_backend()
    data_dir = settings.data_dir()
    label = agent_label(data_dir, backend)
    service_path = backend_service_path(backend, data_dir)

    if backend == "launchd":
        domain = f"gui/{os.getuid()}"
        result = runner(["launchctl", "bootout", f"{domain}/{label}"])
        if result.returncode != 0 and service_path.exists():
            result = runner(["launchctl", "unload", "-w", str(service_path)])
        if result.returncode == 0:
            service_path.unlink(missing_ok=True)
        return UninstallResult(result.returncode == 0, "stopped", backend, label, service_path)

    result = runner(["systemctl", "--user", "disable", "--now", label])
    runner(["systemctl", "--user", "daemon-reload"])
    if result.returncode == 0:
        service_path.unlink(missing_ok=True)
    return UninstallResult(result.returncode == 0, "stopped", backend, label, service_path)


def status(runner: Runner = run_command) -> SchedulerStatus:
    """OS 監視付き常駐ジョブの状態を返す。"""
    backend = select_backend()
    data_dir = settings.data_dir()
    label = agent_label(data_dir, backend)
    service_path = backend_service_path(backend, data_dir)
    paused = settings.stop_path().exists()

    if backend == "launchd":
        result = runner(["launchctl", "print", f"gui/{os.getuid()}/{label}"])
        registered = service_path.exists()
        running = result.returncode == 0
    else:
        result = runner(["systemctl", "--user", "is-active", label])
        registered = service_path.exists()
        running = result.returncode == 0

    if running and paused:
        message = "paused"
    elif running:
        message = "running"
    elif registered:
        message = "registered"
    else:
        message = "stopped"

    return SchedulerStatus(
        registered=registered,
        running=running,
        paused=paused,
        message=message,
        backend=backend,
        label=label,
        service_path=service_path,
        log_path=settings.log_path(),
    )
