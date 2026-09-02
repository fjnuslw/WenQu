"""Repository source acquisition for local paths, zip uploads and public HTTPS Git URLs."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import os
import shutil
import socket
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from getoffer.errors import UpstreamError, ValidationFailed

ARCHIVE_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "out", "target", ".next", ".turbo", "coverage",
    "miniprogram_npm", "uni_modules", "unpackage", "vendor", "Pods",
}
MAX_GIT_HISTORY_COMMITS = 200


@dataclass(frozen=True)
class AcquiredRepository:
    root: Path
    kind: str
    owned_directory: bool
    skipped_dirs: tuple[str, ...]
    metadata: dict[str, object]


async def acquire_repository(
    *,
    zip_bytes: bytes | None,
    local_path: str | None,
    git_url: str | None,
    name: str,
    projects_dir: Path,
    git_proxy: str = "",
) -> AcquiredRepository:
    supplied = sum(value is not None for value in (zip_bytes, local_path, git_url))
    if supplied != 1:
        raise ValidationFailed("file、local_path、git_url 必须且只能提供一个")

    if local_path is not None:
        candidate = Path(local_path)
        if not candidate.is_absolute():
            raise ValidationFailed("local_path 必须是绝对路径（本地部署形态，用户显式指定）")
        if not candidate.is_dir():
            raise ValidationFailed(f"目录不存在或不是目录: {local_path}")
        return AcquiredRepository(
            root=candidate.resolve(),
            kind="local",
            owned_directory=False,
            skipped_dirs=(),
            metadata={"kind": "local"},
        )

    target = _owned_target(projects_dir, name)
    if target.exists():
        raise ValidationFailed(f"项目目录已存在: {name}（请换名或先删除）")
    if zip_bytes is not None:
        written, skipped = extract_zip_safely(zip_bytes, target)
        if written == 0:
            remove_owned_repository(target, projects_dir)
            raise ValidationFailed("zip 内没有有效文件（全部被噪声过滤或为空包）")
        return AcquiredRepository(
            root=target,
            kind="zip",
            owned_directory=True,
            skipped_dirs=tuple(skipped),
            metadata={"kind": "zip", "written_files": written},
        )

    assert git_url is not None
    safe_url = validate_public_git_url(git_url)
    await asyncio.to_thread(_clone_git_repository, safe_url, target, projects_dir, git_proxy)
    return AcquiredRepository(
        root=target,
        kind="git",
        owned_directory=True,
        skipped_dirs=(),
        metadata={"kind": "git", "url": safe_url, "history_limit": MAX_GIT_HISTORY_COMMITS},
    )


def derive_repository_name(git_url: str) -> str:
    parsed = urlsplit(git_url.strip())
    leaf = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
    if leaf.endswith(".git"):
        leaf = leaf[:-4]
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in leaf)
    return cleaned.strip("-_")[:128]


def enumerate_repository_files(
    root: Path,
    *,
    excluded_dirs: set[str] | None = None,
) -> list[Path]:
    """Return source-visible files, honoring .gitignore when history is available.

    Git repositories can contain large ignored caches or locally generated datasets; walking
    them first defeats the collector budget and can hit unreadable runtime directories. Zip
    and plain-directory sources use a permission-tolerant filesystem walk instead.
    """
    resolved_root = root.resolve()
    if (root / ".git").exists():
        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={root.resolve()}",
                    "-C",
                    str(root),
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                ],
                capture_output=True,
                timeout=30,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            files: list[Path] = []
            for raw_path in completed.stdout.split(b"\0"):
                if not raw_path:
                    continue
                relative = raw_path.decode("utf-8", errors="replace").replace("\\", "/")
                pure = PurePosixPath(relative)
                if pure.is_absolute() or ".." in pure.parts:
                    continue
                candidate = root.joinpath(*pure.parts)
                if _is_safe_repository_file(resolved_root, candidate):
                    files.append(candidate)
            return sorted(files, key=lambda item: item.relative_to(root).as_posix())

    files = []
    blocked_directories = ARCHIVE_EXCLUDE_DIRS | (excluded_dirs or set())

    def ignore_walk_error(_error: OSError) -> None:
        return None

    for current, directories, names in os.walk(root, onerror=ignore_walk_error):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if name not in blocked_directories
            and not _is_link_like(current_path / name)
        ]
        for name in names:
            candidate = current_path / name
            if _is_safe_repository_file(resolved_root, candidate):
                files.append(candidate)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _is_safe_repository_file(resolved_root: Path, candidate: Path) -> bool:
    """Reject links and races that could make a repository file resolve outside its root."""
    try:
        if _is_link_like(candidate):
            return False
        resolved = candidate.resolve(strict=True)
        return resolved.is_relative_to(resolved_root) and resolved.is_file()
    except OSError:
        return False


def _is_link_like(path: Path) -> bool:
    """Treat Windows junctions like symlinks; both are unsafe repository boundaries."""
    try:
        is_junction = getattr(path, "is_junction", None)
        return path.is_symlink() or bool(is_junction and is_junction())
    except OSError:
        return True


def validate_public_git_url(value: str) -> str:
    url = value.strip()
    if not url or any(char.isspace() for char in url):
        raise ValidationFailed("git_url 不能为空或包含空白字符")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ValidationFailed("Git URL 仅支持公共 HTTPS；不接受 SSH/file/local 协议")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationFailed("Git URL 不能内嵌用户名、密码或 token")
    if parsed.query or parsed.fragment:
        raise ValidationFailed("Git URL 不能包含 query/fragment（避免凭据泄漏）")
    hostname = parsed.hostname
    if not hostname or hostname.casefold() == "localhost":
        raise ValidationFailed("Git URL 缺少有效公共主机名")
    if not parsed.path or parsed.path == "/":
        raise ValidationFailed("Git URL 缺少仓库路径")
    _assert_public_host(hostname, parsed.port or 443)
    return url


def extract_zip_safely(data: bytes, target: Path) -> tuple[int, list[str]]:
    """Extract an archive under one owned target with Zip Slip and noise guards."""
    target.mkdir(parents=True, exist_ok=False)
    skipped: set[str] = set()
    written = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        remove_owned_repository(target, target.parent)
        raise ValidationFailed(f"zip 包损坏: {exc}") from exc
    try:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename
            pure = PurePosixPath(name.replace("\\", "/"))
            invalid = (
                pure.is_absolute()
                or ".." in pure.parts
                or name.startswith(("/", "\\"))
                or ":" in name.split("/")[0]
            )
            if invalid:
                raise ValidationFailed(f"zip 内含非法路径（疑似 Zip Slip）: {name}")
            parts = pure.parts
            excluded = next((part for part in parts[:-1] if part in ARCHIVE_EXCLUDE_DIRS), None)
            if excluded is not None:
                skipped.add(excluded)
                continue
            destination = target.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(info))
            written += 1
    except Exception:
        remove_owned_repository(target, target.parent)
        raise
    return written, sorted(skipped)


def _assert_public_host(hostname: str, port: int) -> None:
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValidationFailed(f"Git 主机无法解析: {hostname}") from exc
        addresses = []
        for record in records:
            try:
                addresses.append(ipaddress.ip_address(record[4][0]))
            except ValueError:
                continue
    if not addresses:
        raise ValidationFailed(f"Git 主机没有可用地址: {hostname}")
    blocked = [address for address in addresses if not address.is_global]
    if blocked:
        raise ValidationFailed("Git URL 解析到本机、私网或保留地址，已拒绝")


def _clone_git_repository(
    url: str,
    target: Path,
    projects_dir: Path,
    git_proxy: str,
) -> None:
    command = ["git"]
    if git_proxy.strip():
        command.extend(["-c", f"http.proxy={git_proxy.strip()}"])
    command.extend(
        [
            "-c", "protocol.file.allow=never",
            "-c", "protocol.ext.allow=never",
            "-c", "http.followRedirects=false",
            # Ownership immediately computes numstat over this bounded history. A blobless
            # clone would lazily refetch historical blobs during that step and can appear
            # hung, so keep the shallow bound but clone the required objects up front.
            "clone", "--no-tags",
            f"--depth={MAX_GIT_HISTORY_COMMITS}", "--", url, str(target),
        ]
    )
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        remove_owned_repository(target, projects_dir)
        raise UpstreamError(f"Git clone 启动失败或超时: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        remove_owned_repository(target, projects_dir)
        message = (completed.stderr or completed.stdout).strip().splitlines()
        detail = message[-1][:300] if message else "unknown git error"
        raise UpstreamError("Git clone 失败", details={"git": detail})


def _owned_target(projects_dir: Path, name: str) -> Path:
    root = projects_dir.resolve()
    target = (root / name).resolve()
    if target.parent != root:
        raise ValidationFailed("项目目标目录越界")
    return target


def remove_owned_repository(target: Path, projects_dir: Path) -> None:
    """Delete exactly one source-owned child directory, including read-only Git objects."""
    root = projects_dir.resolve()
    resolved = target.resolve()
    if resolved.parent != root:
        raise RuntimeError("拒绝清理非项目专用目录")
    if resolved.exists():
        # Windows 上 Git pack/index 常带只读位；clone 中断和项目删除仍必须可回收。
        shutil.rmtree(resolved, onexc=_remove_readonly)


def _remove_readonly(function, path: str, _error) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)
