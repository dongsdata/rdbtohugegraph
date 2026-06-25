"""
설정 로드
- .env         : 접속 정보 + 파이프라인 설정
- mapping.yaml : 순수 매핑 정보 (vertex_tables, edges)
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class RDBConfig:
    host: str
    port: int
    database: str
    schema: str
    user: str
    password: str


@dataclass
class HugeGraphConfig:
    host: str
    port: int
    graphspace: str
    graph: str
    user: str
    password: str


@dataclass
class EdgeDef:
    """Edge 정의 - via_table 유무로 중간 테이블 / FK 직접 연결 구분"""
    edge_label: str
    src_table: str
    src_col: str
    dst_table: str
    dst_col: str
    via_table: str = ""          # 중간 테이블 (없으면 빈 문자열)
    props: list = field(default_factory=list)

    @property
    def has_via_table(self) -> bool:
        return bool(self.via_table)


@dataclass
class AppConfig:
    rdb: RDBConfig
    hugegraph: HugeGraphConfig
    batch_size: int
    vertex_tables: list    # List[str]
    edges: list            # List[EdgeDef]


def load_config(
    env_file: str = ".env",
    mapping_file: str = "mapping.yaml",
) -> AppConfig:
    # .env 로드
    env_path = Path(env_file)
    if not env_path.exists():
        raise FileNotFoundError(
            f".env 파일이 없습니다.\n  cp .env.example .env"
        )
    load_dotenv(env_path)

    # mapping.yaml 로드
    with open(mapping_file, encoding="utf-8") as f:
        mapping = yaml.safe_load(f)

    # 접속 정보: .env 에서만
    rdb = RDBConfig(
        host     = _require("PG_HOST"),
        port     = int(_require("PG_PORT")),
        database = _require("PG_DATABASE"),
        schema   = _require("PG_SCHEMA"),
        user     = _require("PG_USER"),
        password = _require("PG_PASSWORD"),
    )
    hugegraph = HugeGraphConfig(
        host       = _require("HG_HOST"),
        port       = int(_require("HG_PORT")),
        graphspace = _require("HG_GRAPHSPACE"),
        graph      = _require("HG_GRAPH"),
        user       = _require("HG_USER"),
        password   = _require("HG_PASSWORD"),
    )

    # 매핑 정보: mapping.yaml 에서만
    edges = [
        EdgeDef(
            edge_label = e["edge_label"],
            src_table  = e["src_table"],
            src_col    = e["src_col"],
            dst_table  = e["dst_table"],
            dst_col    = e["dst_col"],
            via_table  = e.get("via_table", ""),
            props      = e.get("props", []),
        )
        for e in mapping.get("edges", [])
    ]

    return AppConfig(
        rdb           = rdb,
        hugegraph     = hugegraph,
        batch_size    = int(_require("BATCH_SIZE")),
        vertex_tables = mapping.get("vertex_tables", []),
        edges         = edges,
    )


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"환경변수 '{key}' 가 설정되지 않았습니다. .env 파일을 확인하세요."
        )
    return val
