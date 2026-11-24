"""基础设施连接地址与受管服务状态。

设计约束：
- 连接地址存入数据库（config_options），读取顺序为「数据库 → 环境变量 → 默认值」，
  因此管理员在设置页保存后立即生效，无需重启 api/worker。
- 部署期地址（PostgreSQL / Redis）由进程启动时的环境变量决定，数据库无法反向改变
  自身连接目标，故只读展示并说明重启要求。
- 服务状态通过 TCP 探活判定，不依赖 docker CLI：api 容器不持有 docker socket，
  也没有 compose 客户端，容器编排由服务器上的运维命令完成。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from yuxi.api.dependencies.auth import get_db, get_superadmin_user
from yuxi.infrastructure.connections import (
    EDITABLE_FIELDS,
    OPTION_KEY,
    SPEC_BY_KEY,
    ensure_definition,
    load_connections,
    probe_all,
    refresh_connections,
)
from yuxi.modules.identity.models import User
from yuxi.modules.system.repositories.options import get_option
from yuxi.modules.system.services.options import save_configuration

router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])


@router.get("/connections")
async def get_connections(
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回各连接地址的生效值、来源与可达性。"""
    await ensure_definition(db)
    connections = await load_connections(db)
    await probe_all(connections)
    return {"ok": True, "connections": connections}


class ConnectionsUpdate(BaseModel):
    """管理员提交的连接地址；键为 option 字段名。"""

    values: dict[str, str]


@router.put("/connections")
async def update_connections(
    payload: ConnectionsUpdate,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """保存可编辑的连接地址并立即生效。"""
    unknown = sorted(set(payload.values) - set(EDITABLE_FIELDS))
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支持的配置项：{', '.join(unknown)}")

    await ensure_definition(db)
    record = await save_configuration(db, OPTION_KEY, payload.values, current_user.username)
    if record is None:
        raise HTTPException(status_code=404, detail="连接地址配置项不存在")

    # 数据库提交后立即刷新进程快照，使本进程的新连接立刻使用新地址。
    await refresh_connections()
    connections = await load_connections(db)
    await probe_all(connections)
    return {"ok": True, "connections": connections}


@router.get("/services")
async def list_services(
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回受管服务清单与其当前可用状态。"""
    await ensure_definition(db)
    record = await get_option(db, OPTION_KEY)
    stored = dict(record.value or {}) if record is not None else {}
    connections = await load_connections(db)

    services = []
    for item in connections:
        spec = SPEC_BY_KEY.get(item["key"])
        option_field = spec.option_field if spec is not None else None
        services.append(
            {
                "name": item["key"],
                "label": item["label"],
                "service": item["service"],
                "endpoint": item["value"],
                "source": item["source"],
                "editable": item["editable"],
                "reason": item["reason"],
                "status": item.get("status", "unknown"),
                "detail": item.get("detail", ""),
                "configured": bool(stored.get(option_field, "")) if option_field else bool(item["value"]),
            }
        )
    return {"ok": True, "services": services}


@router.post("/connections/refresh")
async def refresh(
    current_user: User = Depends(get_superadmin_user),
) -> dict:
    """重新拉取连接地址（用于其他进程改动后的显式刷新）。"""
    changed = await refresh_connections()
    return {"ok": True, "changed": changed}


__all__ = ["router"]
