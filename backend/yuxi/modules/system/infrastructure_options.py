"""基础设施连接地址的管理员配置定义。

取值优先级为「数据库值 → 部署环境变量 → 默认值」，与
yuxi.infrastructure.connections 的注册表保持一致。

只收录运行期可改的地址：PostgreSQL 与 Redis 在进程启动时建立连接，
数据库无法反向改变自身连接目标，因此不属于本配置项。

MinerU OCR 地址由文档域的 mineru_ocr_host_opts 单独管理，此处不重复定义。
"""

from yuxi.modules.system.services.options import Option

RUNTIME_CONNECTION_FIELDS = [
    {
        "key": "minio_uri",
        "label": "MinIO 地址",
        "type": "string",
        "environment": "MINIO_URI",
        "placeholder": "http://minio:9000",
        "help": "对象存储所在机器与端口；留空时读取 MINIO_URI。",
    },
    {
        "key": "milvus_uri",
        "label": "Milvus 地址",
        "type": "string",
        "environment": "MILVUS_URI",
        "placeholder": "http://milvus:19530",
        "help": "向量库所在机器与端口；使用 PG + pgvector 时可留空。",
    },
    {
        "key": "neo4j_uri",
        "label": "Neo4j 地址",
        "type": "string",
        "environment": "NEO4J_URI",
        "placeholder": "bolt://neo4j:7687",
        "help": "知识图谱所在机器与端口；留空时读取 NEO4J_URI。",
    },
    {
        "key": "sandbox_runner_url",
        "label": "沙箱执行器地址",
        "type": "string",
        "environment": "SANDBOX_RUNNER_URL",
        "placeholder": "http://sandbox-runner:8090",
        "help": "代码沙箱运行器所在机器与端口；留空时读取 SANDBOX_RUNNER_URL。",
    },
]

infrastructure_connections_opts = Option(
    key="infrastructure_connections",
    name="基础设施连接地址",
    description="配置各基础组件的连接地址；数据库值优先于部署环境变量。",
    params={
        "fields": RUNTIME_CONNECTION_FIELDS,
    },
)

__all__ = ["RUNTIME_CONNECTION_FIELDS", "infrastructure_connections_opts"]
