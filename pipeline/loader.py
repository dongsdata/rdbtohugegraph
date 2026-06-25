"""
HugeGraph Loader
- 스키마 생성 (PropertyKey / VertexLabel / EdgeLabel)
- Vertex 적재
- Edge 적재
- 결과 조회 (Cypher)
"""
import base64
import logging

import requests
from pyhugegraph.client import PyHugeClient

from pipeline.models import DBMetadata, EdgeInfo, TableInfo
from utils.config import AppConfig
from utils.serializer import HG_TYPE_METHOD, pg_serialize

logger = logging.getLogger(__name__)


class HugeGraphLoader:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        hg       = cfg.hugegraph

        self.client = PyHugeClient(
            hg.host, str(hg.port),
            graph=hg.graph, user=hg.user, pwd=hg.password,
            graphspace=hg.graphspace,
        )
        self.schema = self.client.schema()
        self.g      = self.client.graph()

        token         = base64.b64encode(f"{hg.user}:{hg.password}".encode()).decode()
        self._url     = (
            f"http://{hg.host}:{hg.port}"
            f"/graphspaces/{hg.graphspace}/graphs/{hg.graph}/cypher"
        )
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        }

        # PK값 → Vertex ID 캐시  {"label": {"pk_val": "hg_id"}}
        self._vertex_id_cache: dict[str, dict] = {}
        logger.info("HugeGraph 연결: %s:%s  graph=%s", hg.host, hg.port, hg.graph)

    # ── Cypher 조회 ────────────────────────────────────────────────────────────

    def cypher(self, query: str) -> list:
        resp = requests.post(
            self._url, data=query,
            headers=self._headers, timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("status", {}).get("code", 200) != 200:
            raise RuntimeError(result["status"]["message"])
        return result.get("result", {}).get("data", [])

    # ── 스키마 생성 ────────────────────────────────────────────────────────────

    def create_schema(self, metadata: DBMetadata):
        self._create_property_keys(metadata)
        self._create_vertex_labels(metadata)
        self._create_edge_labels(metadata)
        logger.info("스키마 생성 완료")

    def _create_property_keys(self, metadata: DBMetadata):
        logger.info("[1] PropertyKey 생성")
        seen = set()
        for table in metadata.vertex_tables:
            for col in table.columns:
                if col.name in seen:
                    continue
                seen.add(col.name)
                method = HG_TYPE_METHOD.get(col.hg_type, "asText")
                getattr(self.schema.propertyKey(col.name), method)().ifNotExist().create()
                logger.info("  ✔ %-30s %s  (%s)", col.name, col.hg_type, col.sql_type)

        for edge in metadata.edges:
            for col in edge.prop_cols:
                if col.name in seen:
                    continue
                seen.add(col.name)
                method = HG_TYPE_METHOD.get(col.hg_type, "asText")
                getattr(self.schema.propertyKey(col.name), method)().ifNotExist().create()
                logger.info("  ✔ %-30s %s  (%s) [Edge prop]", col.name, col.hg_type, col.sql_type)

    def _create_vertex_labels(self, metadata: DBMetadata):
        logger.info("[2] VertexLabel 생성")
        for table in metadata.vertex_tables:
            prop_names    = [c.name for c in table.columns]
            nullable_cols = [c.name for c in table.columns if c.nullable and not c.is_pk]
            
            vl = self.schema.vertexLabel(table.name).properties(*prop_names)
            if table.primary_keys:
                vl = vl.usePrimaryKeyId().primaryKeys(*table.primary_keys)
            if nullable_cols:
                vl = vl.nullableKeys(*nullable_cols)
            vl.ifNotExist().create()
            logger.info("  ✔ %-25s PK=%s", table.name, table.primary_keys)

    def _create_edge_labels(self, metadata: DBMetadata):
        logger.info("[3] EdgeLabel 생성")
        seen = set()
        for edge in metadata.edges:
            if edge.edge_label in seen:
                continue
            seen.add(edge.edge_label)
            prop_names = [c.name for c in edge.prop_cols]
            el = (
                self.schema.edgeLabel(edge.edge_label)
                    .sourceLabel(edge.src_table)
                    .targetLabel(edge.dst_table)
            )
            if prop_names:
                el = el.properties(*prop_names)
            el.ifNotExist().create()
            logger.info("  ✔ %-25s (%s → %s)", edge.edge_label, edge.src_table, edge.dst_table)

    # ── Vertex 적재 ────────────────────────────────────────────────────────────

    def load_vertices(self, table: TableInfo, batches) -> int:
        total = 0
        self._vertex_id_cache.setdefault(table.name, {})
        for batch in batches:
            for row in batch:
                props  = {
                    c.name: pg_serialize(row[c.name])
                    for c in table.columns
                    if row.get(c.name) is not None
                }
                result = self.g.addVertex(table.name, props)
                if result and table.primary_keys:
                    pk_val = str(row.get(table.primary_keys[0], ""))
                    self._vertex_id_cache[table.name][pk_val] = result.id
            total += len(batch)
            logger.info("   배치 %d행 완료 (누적 %d)", len(batch), total)
        logger.info("   ✅ [%s] %d개 Vertex 적재 완료", table.name, total)
        return total

    # ── Vertex ID 캐시 로드 ────────────────────────────────────────────────────

    def load_vertex_id_cache(self, metadata: DBMetadata):
        """Edge 적재 전 호출 - 이미 적재된 Vertex ID를 캐시에 로드"""
        for table in metadata.vertex_tables:
            if not table.primary_keys:
                continue
            pk_col = table.primary_keys[0]
            result = self.cypher(
                f"MATCH (n:`{table.name}`) "
                f"RETURN id(n) AS vid, n.`{pk_col}` AS pk"
            )
            cache = {str(r["pk"]): r["vid"] for r in result}
            self._vertex_id_cache[table.name] = cache
            logger.info("  %s: %d개 캐시 로드", table.name, len(cache))

    # ── Edge 적재 ──────────────────────────────────────────────────────────────

    def load_edges(self, edge: EdgeInfo, batches) -> int:
        """
        via_table 있음 / 없음 모두 동일한 인터페이스로 처리
        extractor 가 이미 올바른 테이블에서 (src_fk, dst_fk) 를 조회해서 넘겨줌
        """
        total = skip = 0
        for batch in batches:
            for row in batch:
                src_id = self._vertex_id_cache.get(edge.src_table, {}).get(str(row["src_fk"]))
                dst_id = self._vertex_id_cache.get(edge.dst_table, {}).get(str(row["dst_fk"]))
                if not src_id or not dst_id:
                    skip += 1
                    continue
                props = {
                    c.name: pg_serialize(row[c.name])
                    for c in edge.prop_cols
                    if row.get(c.name) is not None
                }
                self.g.addEdge(edge.edge_label, src_id, dst_id, props)
                total += 1
            logger.info("   배치 %d쌍 완료 (누적 %d)", len(batch), total)

        logger.info("   ✅ [%s] %d개 Edge 적재 완료", edge.edge_label, total)
        if skip:
            logger.warning("   ⚠️  캐시 미스 %d건 건너뜀", skip)
        return total

    # ── 결과 통계 ──────────────────────────────────────────────────────────────

    def print_stats(self, metadata: DBMetadata):
        print("\n📦 Vertex 수:")
        for table in metadata.vertex_tables:
            cnt = self.cypher(
                f"MATCH (n:`{table.name}`) RETURN count(n) AS cnt"
            )[0]["cnt"]
            print(f"  {table.name}: {cnt}")

        if metadata.edges:
            print("\n🔗 Edge 수:")
            seen = set()
            for edge in metadata.edges:
                if edge.edge_label in seen:
                    continue
                seen.add(edge.edge_label)
                cnt = self.cypher(
                    f"MATCH ()-[r:`{edge.edge_label}`]->() RETURN count(r) AS cnt"
                )[0]["cnt"]
                print(f"  {edge.edge_label} ({edge.src_table} → {edge.dst_table}): {cnt}")
