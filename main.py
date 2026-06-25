"""
RDB → HugeGraph 적재 파이프라인
실행: python main.py [--step all|schema|vertex|edge|stats]
"""
import argparse
import logging
import sys

from pipeline.extractor import PGExtractor
from pipeline.loader import HugeGraphLoader
from utils.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("pyhugegraph").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def run(step: str):
    # ── 설정 로드 ──────────────────────────────────────────────────────────────
    cfg = load_config(env_file="env.env", mapping_file="mapping.yaml")
    logger.info("설정 로드 완료")
    logger.info("  RDB      : %s@%s:%s/%s (schema=%s)",
                cfg.rdb.user, cfg.rdb.host, cfg.rdb.port,
                cfg.rdb.database, cfg.rdb.schema)
    logger.info("  HugeGraph: %s:%s  graph=%s",
                cfg.hugegraph.host, cfg.hugegraph.port, cfg.hugegraph.graph)
    logger.info("  Vertex 테이블: %s", cfg.vertex_tables)
    logger.info("  Edge 정의    : %s",
                [(e.edge_label, "via" if e.has_via_table else "fk") for e in cfg.edges])
    logger.info("  Batch Size   : %d", cfg.batch_size)

    extractor = PGExtractor(cfg)
    loader    = HugeGraphLoader(cfg)

    # ── 메타데이터 추출 ────────────────────────────────────────────────────────
    logger.info("=== 메타데이터 추출 ===")
    metadata = extractor.extract_metadata()

    # ── STEP: schema ──────────────────────────────────────────────────────────
    if step in ("all", "schema"):
        logger.info("=== STEP: 스키마 생성 ===")
        loader.create_schema(metadata)

    # ── STEP: vertex ──────────────────────────────────────────────────────────
    if step in ("all", "vertex"):
        logger.info("=== STEP: Vertex 적재 ===")
        total = 0
        for table in metadata.vertex_tables:
            logger.info("📌 [%s] 적재 중...", table.name)
            batches = extractor.fetch_rows_batched(table.name, cfg.batch_size)
            total  += loader.load_vertices(table, batches)
        logger.info("✅ 전체 Vertex %d개 적재 완료", total)

    # ── STEP: edge ────────────────────────────────────────────────────────────
    if step in ("all", "edge"):
        logger.info("=== STEP: Edge 적재 ===")
        logger.info("Vertex ID 캐시 로드 중...")
        loader.load_vertex_id_cache(metadata)

        total = 0
        for edge in metadata.edges:
            via = f"via [{edge.via_table}]" if edge.has_via_table else "FK 직접 연결"
            logger.info("🔗 [%s] %s  (%s → %s)", edge.edge_label, via,
                        edge.src_table, edge.dst_table)
            batches = extractor.fetch_edge_pairs_batched(edge, cfg.batch_size)
            total  += loader.load_edges(edge, batches)
        logger.info("✅ 전체 Edge %d개 적재 완료", total)

    # ── STEP: stats ───────────────────────────────────────────────────────────
    if step in ("all", "stats"):
        logger.info("=== 결과 확인 ===")
        loader.print_stats(metadata)


def main():
    parser = argparse.ArgumentParser(description="RDB → HugeGraph 적재 파이프라인")
    parser.add_argument(
        "--step",
        choices=["all", "schema", "vertex", "edge", "stats"],
        default="all",
        help="실행할 단계 (기본값: all)",
    )
    args = parser.parse_args()
    run(args.step)


if __name__ == "__main__":
    main()
