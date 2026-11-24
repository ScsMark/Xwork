"""运行期连接地址注册表。

平台允许管理员在设置页调整各基础组件的连接地址。取值优先级为
「数据库中的管理员配置 → 部署环境变量 → 内置默认地址」。

地址变化后重置持有旧地址的客户端（MinIO / Neo4j / 沙箱执行器），
使后续调用立即使用新地址；Milvus 按知识库实例创建，新实例自然生效。
"""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.infrastructure.observability.logging import logger

OPTION_KEY = "infrastructure_connections"
REFRESH_INTERVAL_SECONDS = 60.0
PROBE_TIMEOUT_SECONDS = 2.0

# 各协议的默认端口；显式端口优先于默认值。
_DEFAULT_PORTS = {
    "postgresql": 5432,
    "postgresql+asyncpg": 5432,
    "postgres": 5432,
    "redis": 6379,
    "rediss": 6379,
    "http": 80,
    "https": 443,
    "bolt": 7687,
    "neo4j": 7687,
    "grpc": 19530,
}


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    """一个受管连接地址的元数据。"""

    key: str
    env: str
    label: str
    service: str
    option_field: str | None = None
    editable: bool = False
    reason: str = ""
    placeholder: str = ""
    default: str = ""


# 顺序决定设置页的展示顺序。
CONNECTION_SPECS: tuple[ConnectionSpec, ...] = (
    ConnectionSpec(
        key="POSTGRES_URL",
        env="POSTGRES_URL",
        label="PostgreSQL 地址",
        service="主数据库",
        reason="部署期配置；数据库无法反向改变自身连接目标，修改需改服务器环境并重启 api/worker。",
        placeholder="postgresql+asyncpg://user:pass@10.0.0.1:5432/yuxi",
    ),
    ConnectionSpec(
        key="REDIS_URL",
        env="REDIS_URL",
        label="Redis 地址",
        service="缓存与任务队列",
        reason="部署期配置；连接在进程启动时建立，修改需重启 api/worker。",
        placeholder="redis://10.0.0.1:6379/0",
    ),
    ConnectionSpec(
        key="MINIO_URI",
        env="MINIO_URI",
        label="MinIO 地址",
        service="对象存储",
        option_field="minio_uri",
        editable=True,
        placeholder="http://minio:9000",
        default="http://minio:9000",
    ),
    ConnectionSpec(
        key="MILVUS_URI",
        env="MILVUS_URI",
        label="Milvus 地址",
        service="向量库",
        option_field="milvus_uri",
        editable=True,
        placeholder="http://milvus:19530",
        default="http://milvus:19530",
    ),
    ConnectionSpec(
        key="NEO4J_URI",
        env="NEO4J_URI",
        label="Neo4j 地址",
        service="知识图谱",
        option_field="neo4j_uri",
        editable=True,
        placeholder="bolt://neo4j:7687",
        default="bolt://localhost:7687",
    ),
    ConnectionSpec(
        key="SANDBOX_RUNNER_URL",
        env="SANDBOX_RUNNER_URL",
        label="沙箱执行器地址",
        service="代码沙箱",
        option_field="sandbox_runner_url",
        editable=True,
        placeholder="http://sandbox-runner:8090",
        default="http://sandbox-runner:8090",
    ),
)

SPEC_BY_KEY = {spec.key: spec for spec in CONNECTION_SPECS}
EDITABLE_FIELDS = {spec.option_field: spec for spec in CONNECTION_SPECS if spec.option_field}

_lock = threading.Lock()
_snapshot: dict[str, str] = {}


def get_connection(key: str, default: str = "") -> str:
    """读取当前生效的连接地址；未刷新过时回落到部署环境变量。"""
    with _lock:
        value = _snapshot.get(key, "")
    if value:
        return value
    spec = SPEC_BY_KEY.get(key)
    if spec is not None:
        return os.getenv(spec.env, "") or spec.default
    return os.getenv(key, default) or default


def snapshot() -> dict[str, str]:
    """返回当前生效地址的副本。"""
    with _lock:
        return dict(_snapshot)


async def ensure_definition(db: AsyncSession) -> None:
    """确保配置定义已落库；app-init 尚未执行时也能自愈。

    定义已存在时直接返回，避免每次读取都获取 advisory lock。
    """
    from yuxi.modules.system.infrastructure_options import infrastructure_connections_opts
    from yuxi.modules.system.repositories.options import get_option, sync_option_definitions

    if await get_option(db, OPTION_KEY) is not None:
        return
    await sync_option_definitions(db, {OPTION_KEY: infrastructure_connections_opts})


async def load_connections(db: AsyncSession) -> list[dict]:
    """读取各连接地址的生效值、来源与健康状态。"""
    from yuxi.modules.system.repositories.options import get_option

    record = await get_option(db, OPTION_KEY)
    stored = dict(record.value or {}) if record is not None else {}

    results: list[dict] = []
    for spec in CONNECTION_SPECS:
        stored_value = ""
        if spec.option_field:
            stored_value = str(stored.get(spec.option_field, "") or "").strip()
        env_value = (os.getenv(spec.env, "") or "").strip()
        effective = stored_value or env_value or spec.default
        if stored_value:
            source = "database"
        elif env_value:
            source = "environment"
        else:
            source = "default"
        results.append(
            {
                "key": spec.key,
                "label": spec.label,
                "service": spec.service,
                "value": effective,
                "stored": stored_value,
                "source": source,
                "editable": spec.editable,
                "reason": spec.reason,
                "placeholder": spec.placeholder,
            }
        )
    return results


def apply_connections(values: dict[str, str]) -> list[str]:
    """把新地址写入进程快照，并重置地址已变化的客户端。"""
    changed: list[str] = []
    with _lock:
        for key, value in values.items():
            if key not in SPEC_BY_KEY:
                continue
            if _snapshot.get(key, "") != value:
                _snapshot[key] = value
                changed.append(key)
    if changed:
        _reset_clients(changed)
    return changed


def _reset_clients(changed: list[str]) -> None:
    """丢弃持有旧地址的进程级客户端；失败不阻断其余重置。"""
    if "MINIO_URI" in changed:
        try:
            from yuxi.infrastructure.minio.client import reset_minio_client

            reset_minio_client()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to reset MinIO client: error_type={type(exc).__name__}")
    if "NEO4J_URI" in changed:
        try:
            from yuxi.infrastructure.neo4j.manager import close_shared_neo4j_connection

            close_shared_neo4j_connection()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to close Neo4j connection: error_type={type(exc).__name__}")
    if "SANDBOX_RUNNER_URL" in changed:
        try:
            from yuxi.modules.agents.runtime.sandbox.provider import reset_sandbox_provider

            reset_sandbox_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to reset sandbox provider: error_type={type(exc).__name__}")


async def refresh_connections() -> list[str]:
    """从数据库重新加载地址并应用到进程；返回发生变化的键。

    数据库不可用时保留既有快照并返回空变更，不阻断调用方。
    """
    from yuxi.infrastructure.postgres.manager import pg_manager

    try:
        async with pg_manager.get_async_session_context() as session:
            await ensure_definition(session)
            record = await _get_raw_record(session)
            stored = dict(record.value or {}) if record is not None else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read connection addresses: error_type={type(exc).__name__}")
        return []

    values: dict[str, str] = {}
    for spec in CONNECTION_SPECS:
        stored_value = ""
        if spec.option_field:
            stored_value = str(stored.get(spec.option_field, "") or "").strip()
        values[spec.key] = stored_value or (os.getenv(spec.env, "") or "").strip() or spec.default
    return apply_connections(values)


async def _get_raw_record(session: AsyncSession):
    from yuxi.modules.system.repositories.options import get_option

    return await get_option(session, OPTION_KEY)


async def refresh_loop() -> None:
    """周期刷新连接地址，使其他进程写入的配置及时生效。"""
    while True:
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
        try:
            await refresh_connections()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to refresh connection addresses: error_type={type(exc).__name__}")


async def probe_uri(uri: str) -> tuple[str, str]:
    """探测地址可达性；返回状态与可展示说明，不暴露凭据。"""
    if not uri:
        return "unconfigured", "未配置地址"
    try:
        parsed = urlparse(uri)
    except ValueError:
        return "unknown", "地址格式无法解析"
    host = parsed.hostname
    if not host:
        return "unknown", "地址缺少主机名"
    port = parsed.port or _DEFAULT_PORTS.get(parsed.scheme.lower(), 0)
    if not port:
        return "unknown", "地址缺少端口"
    try:
        _, _ = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=PROBE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return "unreachable", f"{host}:{port} 连接超时"
    except OSError:
        return "unreachable", f"{host}:{port} 无法连接"
    return "healthy", f"{host}:{port} 可达"


async def probe_all(values: list[dict]) -> list[dict]:
    """并发探测全部连接地址。"""
    statuses = await asyncio.gather(*(probe_uri(str(item.get("value") or "")) for item in values))
    for item, (status, detail) in zip(values, statuses):
        item["status"] = status
        item["detail"] = detail
    return values


__all__ = [
    "CONNECTION_SPECS",
    "EDITABLE_FIELDS",
    "OPTION_KEY",
    "SPEC_BY_KEY",
    "apply_connections",
    "ensure_definition",
    "get_connection",
    "load_connections",
    "probe_all",
    "probe_uri",
    "refresh_connections",
    "refresh_loop",
    "snapshot",
]
