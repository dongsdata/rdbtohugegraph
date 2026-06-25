"""
PG Extractor
- 메타데이터 추출 (테이블 / 컬럼 / PK)
- 행 배치 조회 (Vertex용 / Edge용)
"""
import logging
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from pipeline.models import ColumnInfo, DBMetadata, EdgeInfo, TableInfo
from utils.config import AppConfig, EdgeDef
from utils.serializer import map_pg_type

logger = logging.getLogger(__name__)


class PGExtractor:
    def __init__(self, cfg: AppConfig):
        self.cfg    = cfg
        self.engine = self._build_engine()

    def _build_engine(self) -> Engine:
        rdb = self.cfg.rdb
        url = (
            f"postgresql+psycopg2://{rdb.user}:{rdb.password}"
            f"@{rdb.host}:{rdb.port}/{rdb.database}"
            f"?options=-csearch_path%3D{rdb.schema}"
        )
        engine = create_engine(url, pool_pre_ping=True, echo=False)
        logger.info("PG 연결: %s/%s (schema=%s)", rdb.host, rdb.database, rdb.schema)
        return engine

    # ── 메타데이터 추출 ────────────────────────────────────────────────────────

    def extract_metadata(self) -> DBMetadata:
        insp       = inspect(self.engine)
        schema     = self.cfg.rdb.schema
        all_tables = set(insp.get_table_names(schema=schema))

        vertex_tables = self._extract_vertex_tables(insp, schema, all_tables)
        edges         = self._extract_edges(insp, schema, all_tables, vertex_tables)

        return DBMetadata(schema=schema, vertex_tables=vertex_tables, edges=edges)

    def _get_columns(self, insp, tname: str, schema: str, pk_names: list) -> list:
        return [
            ColumnInfo(
                name     = c["name"],
                sql_type = str(c["type"]),
                hg_type  = map_pg_type(str(c["type"])),
                is_pk    = c["name"] in pk_names,
                nullable = bool(c.get("nullable", True)),
            )
            for c in insp.get_columns(tname, schema=schema)
        ]

    def _extract_vertex_tables(self, insp, schema, all_tables) -> list:
        tables = []
        for tname in self.cfg.vertex_tables:
            if tname not in all_tables:
                logger.warning("없는 테이블: %s", tname)
                continue
            pk_names = insp.get_pk_constraint(tname, schema=schema).get("constrained_columns", [])
            columns  = self._get_columns(insp, tname, schema, pk_names)
            tables.append(TableInfo(name=tname, columns=columns, primary_keys=pk_names))
            logger.info("  Vertex: %-30s PK=%s", tname, pk_names)
        return tables

    def _extract_edges(
        self, insp, schema, all_tables, vertex_tables: list
    ) -> list:
        """
        mapping.yaml 의 edges 정의를 EdgeInfo 로 변환
        via_table 유무에 따라 처리 방식이 달라지는 건 extractor/loader 에서 투명하게 처리
        """
        vtable_map = {t.name: t for t in vertex_tables}
        edges      = []

        for e in self.cfg.edges:
            # 조회할 테이블 (via_table 있으면 via_table, 없으면 src_table)
            query_table = e.via_table if e.has_via_table else e.src_table
            if query_table not in all_tables:
                logger.warning("없는 테이블: %s", query_table)
                continue

            # Edge 프로퍼티 컬럼
            if e.props:
                pk_names  = insp.get_pk_constraint(query_table, schema=schema).get("constrained_columns", [])
                all_cols  = self._get_columns(insp, query_table, schema, pk_names)
                prop_cols = [c for c in all_cols if c.name in e.props]
            else:
                prop_cols = []

            # src Vertex PK 컬럼
            src_table_info = vtable_map.get(e.src_table)
            src_pk_cols    = src_table_info.primary_keys if src_table_info else [e.src_col]

            edge_info = EdgeInfo(
                edge_label  = e.edge_label,
                src_table   = e.src_table,
                src_col     = e.src_col,
                dst_table   = e.dst_table,
                dst_col     = e.dst_col,
                via_table   = e.via_table,
                prop_cols   = prop_cols,
                src_pk_cols = src_pk_cols,
            )
            edges.append(edge_info)

            if e.has_via_table:
                logger.info("  Edge  : %-20s via %-25s (%s → %s)",
                            e.edge_label, e.via_table, e.src_table, e.dst_table)
            else:
                logger.info("  Edge  : %-20s FK  %-25s (%s.%s → %s.%s)",
                            e.edge_label, e.src_table,
                            e.src_table, e.src_col, e.dst_table, e.dst_col)

        return edges

    # ── 행 배치 조회 ──────────────────────────────────────────────────────────

    def fetch_rows_batched(
        self, table_name: str, batch_size: int
    ) -> Iterator[list[dict]]:
        """Vertex용 전체 행 조회"""
        schema = self.cfg.rdb.schema
        full   = f'"{schema}"."{table_name}"'
        offset = 0
        with self.engine.connect() as conn:
            while True:
                rows = conn.execute(
                    text(f"SELECT * FROM {full} LIMIT :lim OFFSET :off"),
                    {"lim": batch_size, "off": offset},
                ).mappings().fetchall()
                if not rows:
                    break
                yield [dict(r) for r in rows]
                offset += batch_size
                if len(rows) < batch_size:
                    break

    def fetch_edge_pairs_batched(
        self, edge: EdgeInfo, batch_size: int
    ) -> Iterator[list[dict]]:
        """
        Edge용 (src_col, dst_col, props) 조회
        via_table 있음 → via_table 에서 조회
        via_table 없음 → src_table 에서 조회 (FK 직접 연결)
        """
        schema     = self.cfg.rdb.schema
        full       = f'"{schema}"."{edge.query_table}"'
        prop_sel   = (
            ", " + ", ".join(f'"{c.name}"' for c in edge.prop_cols)
            if edge.prop_cols else ""
        )
        offset = 0
        with self.engine.connect() as conn:
            while True:
                rows = conn.execute(
                    text(
                        f'SELECT "{edge.src_col}" AS src_fk,'
                        f' "{edge.dst_col}" AS dst_fk{prop_sel}'
                        f' FROM {full}'
                        f' WHERE "{edge.src_col}" IS NOT NULL'
                        f'   AND "{edge.dst_col}" IS NOT NULL'
                        f' LIMIT :lim OFFSET :off'
                    ),
                    {"lim": batch_size, "off": offset},
                ).mappings().fetchall()
                if not rows:
                    break
                yield [dict(r) for r in rows]
                offset += batch_size
                if len(rows) < batch_size:
                    break
