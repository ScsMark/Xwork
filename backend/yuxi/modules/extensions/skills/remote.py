from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from yuxi.infrastructure.observability.logging import logger
from yuxi.infrastructure.filesystem import await_io
from yuxi.modules.extensions.options import remote_skill_source_policy
from yuxi.modules.extensions.skills.package import is_valid_skill_slug

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
CONTROL_SEQUENCE_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)|\x1B[\(\)][A-Za-z0-9]")
CLI_TIMEOUT_SECONDS = 300
GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/(?!\.{1,2}$)[A-Za-z0-9_.-]+$")
GITHUB_HOST = "github.com"
INVALID_SOURCE_MESSAGE = "source 仅支持远程 Skill 来源白名单中的 HTTPS 地址"


@dataclass(frozen=True, slots=True)
class DownloadedSkill:
    """已下载的目录；包格式由草稿或安装边界校验。"""

    slug: str
    source_dir: Path


@dataclass(frozen=True, slots=True)
class SkillDownloadFailure:
    """一个请求条目的获取失败原因。"""

    slug: str
    error: str


@dataclass(slots=True)
class RemoteSkillDownloads:
    """一次远程批量获取的临时目录与逐项结果。"""

    temp_home: str | None
    results: list[DownloadedSkill | SkillDownloadFailure]

    async def cleanup(self) -> None:
        """释放本批获取持有的宿主临时目录。"""
        if self.temp_home:
            await await_io(asyncio.to_thread(shutil.rmtree, self.temp_home, ignore_errors=True))


async def list_remote_skills(source: str, *, uid: str) -> list[dict[str, str]]:
    """列出允许来源中的可安装 Skill。"""
    policy = await remote_skill_source_policy.get()
    normalized_source = _normalize_source(source, policy["allowed_hosts"])

    sandbox = _RemoteSkillRequest.create(uid)
    try:
        output = await sandbox.run(["npx", "-y", "skills", "add", normalized_source, "--list"])
    finally:
        await sandbox.cleanup()

    skills = _parse_available_skills(output)
    if not skills:
        raise ValueError("未发现可安装的 skills")
    return skills


async def download_remote_skills(
    *,
    source: str,
    skills: list[str],
    uid: str,
) -> RemoteSkillDownloads:
    """批量从远程仓库拉取 skill 目录，但不写数据库。"""
    policy = await remote_skill_source_policy.get()
    normalized_source = _normalize_source(source, policy["allowed_hosts"])
    if not skills:
        raise ValueError("skills 列表不能为空")

    results: dict[int, DownloadedSkill | SkillDownloadFailure] = {}
    requests: list[tuple[int, str]] = []
    for index, skill in enumerate(skills):
        try:
            requests.append((index, _normalize_skill_name(skill)))
        except ValueError as exc:
            results[index] = SkillDownloadFailure(slug=skill, error=str(exc))

    if not requests:
        return RemoteSkillDownloads(temp_home=None, results=list(results.values()))

    sandbox = _RemoteSkillRequest.create(uid)
    temp_home: str | None = None
    try:
        try:
            temp_home = tempfile.mkdtemp(prefix=".remote-skills-")
            skill_args: list[str] = []
            for _index, name in requests:
                skill_args.extend(["--skill", name])

            cli_failed = False
            cli_error = ""
            try:
                await sandbox.run(
                    [
                        "npx",
                        "-y",
                        "skills",
                        "add",
                        normalized_source,
                        *skill_args,
                        "-g",
                        "-y",
                        "--copy",
                    ]
                )
            except ValueError as exc:
                # CLI 对不匹配的 skill 会退出码非零，但已安装的目录仍在；保留真实原因。
                cli_failed = True
                cli_error = str(exc)

            downloaded_dirs: dict[str, Path | None] = {}
            for original_index, name in requests:
                installed_dir = Path(temp_home) / name
                if name not in downloaded_dirs:
                    try:
                        await sandbox.download_skill(name, installed_dir)
                        downloaded_dirs[name] = installed_dir
                    except ValueError:
                        downloaded_dirs[name] = None
                installed_dir = downloaded_dirs[name]
                if installed_dir is None:
                    error_msg = cli_error if cli_failed and cli_error else "skills CLI 未生成预期的技能目录"
                    results[original_index] = SkillDownloadFailure(slug=name, error=error_msg)
                    continue
                results[original_index] = DownloadedSkill(slug=name, source_dir=installed_dir)

        finally:
            await sandbox.cleanup()
    except BaseException:
        if temp_home:
            await await_io(asyncio.to_thread(shutil.rmtree, temp_home, ignore_errors=True))
        raise

    return RemoteSkillDownloads(temp_home=temp_home, results=[results[index] for index in range(len(skills))])


async def search_remote_skills(query: str, *, uid: str) -> list[dict[str, str]]:
    """使用 npx skills find <query> 搜索远程 skills。"""
    query_val = str(query or "").strip()
    if not query_val:
        return []
    if any(ch in query_val for ch in ("\n", "\r", "\x00")):
        raise ValueError("搜索关键字包含非法字符")

    sandbox = _RemoteSkillRequest.create(uid)
    try:
        output = await sandbox.run(["npx", "-y", "skills", "find", query_val])
    finally:
        await sandbox.cleanup()

    return _parse_search_skills(output)


@dataclass(slots=True)
class _RemoteSkillRequest:
    """在业务进程内执行远程 Skill CLI，临时 HOME 按请求隔离。

    CLI 必须在有外网与 Node 的进程里运行；沙箱执行环境按 Run 创建，
    设置页发起的安装请求没有 Run 上下文，因此这里改用宿主进程执行。
    """

    home: Path

    @classmethod
    def create(cls, uid: str) -> _RemoteSkillRequest:
        """每个请求只创建自己的宿主临时 HOME，执行结束后整体删除。"""
        del uid  # 目录与用户隔离，CLI 不需要用户身份
        home = Path(tempfile.mkdtemp(prefix=".remote-skills-"))
        (home / "workspace").mkdir(parents=True, exist_ok=True)
        return cls(home=home)

    async def run(self, args: list[str]) -> str:
        """执行 Skills CLI，并返回合并后的标准输出与标准错误。"""
        env = {
            "HOME": str(self.home),
            "TMPDIR": str(self.home / "tmp"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
            "NPM_CONFIG_FUND": "false",
        }
        (self.home / "tmp").mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self.home / "workspace"),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output_bytes, _ = await asyncio.wait_for(process.communicate(), timeout=CLI_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ValueError(f"skills CLI 执行超时（{CLI_TIMEOUT_SECONDS} 秒）") from exc
        output = ANSI_ESCAPE_RE.sub("", output_bytes.decode("utf-8", errors="replace"))
        if process.returncode != 0:
            tail = " ".join(output.strip().splitlines()[-6:])[-600:]
            logger.error("skills CLI exit={} args={} output={}", process.returncode, args[:4], tail)
            raise ValueError(f"skills CLI 执行失败（退出码 {process.returncode}）：{tail or '无输出'}")
        return output

    async def download_skill(self, name: str, target_dir: Path) -> None:
        """将本次 CLI 生成的技能目录复制到宿主临时目录。"""
        source_dir = self.home / ".agents" / "skills" / name
        if not source_dir.is_dir():
            raise ValueError("skills CLI 未生成预期的技能目录")
        await await_io(asyncio.to_thread(self._copy_dir, source_dir, target_dir))

    @staticmethod
    def _copy_dir(source_dir: Path, target_dir: Path) -> None:
        """覆盖式复制技能目录，保留文件内容与权限。"""
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir, symlinks=False)

    async def cleanup(self) -> None:
        """只移除本请求的临时目录。"""
        await await_io(asyncio.to_thread(shutil.rmtree, self.home, ignore_errors=True))


def _normalize_source(source: str, allowed_hosts: list[str]) -> str:
    value = str(source or "").strip()
    if not value:
        raise ValueError("source 不能为空")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise ValueError("source 包含非法字符")

    allowed_hosts = {host.strip().lower().rstrip(".") for host in allowed_hosts}
    if GITHUB_REPO_PATTERN.fullmatch(value):
        if GITHUB_HOST not in allowed_hosts:
            raise ValueError(INVALID_SOURCE_MESSAGE)
        return f"https://{GITHUB_HOST}/{value}"

    parsed = urlparse(value)
    try:
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError:
        raise ValueError(INVALID_SOURCE_MESSAGE) from None

    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or hostname not in allowed_hosts
    ):
        raise ValueError(INVALID_SOURCE_MESSAGE)

    path = parsed.path.rstrip("/") or "/"
    if hostname == GITHUB_HOST:
        repo_path = path.strip("/")
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        if not GITHUB_REPO_PATTERN.fullmatch(repo_path):
            raise ValueError(INVALID_SOURCE_MESSAGE)
        return f"https://{GITHUB_HOST}/{repo_path}"

    return parsed._replace(scheme="https", netloc=hostname, path=path).geturl().rstrip("/")


def _normalize_skill_name(skill: str) -> str:
    value = str(skill or "").strip()
    if not is_valid_skill_slug(value):
        raise ValueError("skill 名称不合法")
    return value


def _clean_cli_output(output: str) -> list[str]:
    cleaned = ANSI_ESCAPE_RE.sub("", output or "")
    cleaned = CONTROL_SEQUENCE_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r", "\n")
    normalized_lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        stripped = re.sub(r"^[│┌└◇◒◐◓◑■●]+\s*", "", stripped)
        normalized_lines.append(stripped.strip())
    return normalized_lines


def _parse_available_skills(output: str) -> list[dict[str, str]]:
    lines = _clean_cli_output(output)
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    collecting = False

    for idx, line in enumerate(lines):
        if not collecting:
            if "Available Skills" in line:
                collecting = True
            continue

        if not line:
            continue
        if "Use --skill " in line:
            break
        if not is_valid_skill_slug(line):
            continue
        if line in seen:
            continue

        description = ""
        next_index = idx + 1
        while next_index < len(lines):
            next_line = lines[next_index]
            next_index += 1
            if not next_line:
                continue
            if "Use --skill " in next_line:
                break
            if is_valid_skill_slug(next_line):
                break
            if next_line and next_line[0].isalpha():
                description = next_line
            else:
                continue
            break

        seen.add(line)
        items.append({"name": line, "description": description})

    return items


def _parse_search_skills(output: str) -> list[dict[str, str]]:
    """解析 npx skills find 命令的输出。"""
    lines = _clean_cli_output(output)
    results: list[dict[str, str]] = []
    # 匹配形如 "owner/repo@skill-name [installs]"
    # 例如：vercel-labs/agent-skills@web-design-guidelines 339.3K installs
    pattern = re.compile(r"^([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+)\@([a-zA-Z0-9_\-\.]+)(?:\s+(.*))?$")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            source, name, extra = match.groups()
            installs = extra.strip() if extra else ""
            results.append(
                {
                    "source": source,
                    "name": name,
                    "installs": installs,
                }
            )
    return results
