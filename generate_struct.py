"""
mapping.yaml + .env → HugeGraph Bulk Loader용 struct.json 생성

실행: python generate_struct.py
      python generate_struct.py --output my_struct.json
"""
import argparse
import json
import logging
import sys

from utils.config import load_config

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def generate_struct(cfg, output_file: str):
    rdb = cfg.rdb
    hg  = cfg.hugegraph

    # JDBC URL
    jdbc_url = (
        f"jdbc:postgresql://{rdb.host}:{rdb.port}/{rdb.database}"
    )

    structs = []

    # ── Vertex 테이블 ─────────────────────────────────────────────────────────
    for tname in cfg.vertex_tables:
        structs.append({
            "id": f"vertex_{tname}",
            "input": {
                "type": "JDBC",
                "vendor": "POSTGRESQL",
                "driver": "org.postgresql.Driver",
                "url": jdbc_url,
                "database": rdb.database,
                "schema": rdb.schema,
                "table": tname,
                "username": rdb.user,
                "password": rdb.password,
                "batch_size": cfg.batch_size,
            },
            "vertices": [{"label": tname}],
            "edges": [],
        })
        logger.info("  Vertex struct: %s", tname)

    # ── Edge 정의 ─────────────────────────────────────────────────────────────
    for e in cfg.edges:
        # 조회할 테이블: via_table 있으면 via_table, 없으면 src_table
        query_table = e.via_table if e.has_via_table else e.src_table

        struct = {
            "id": f"edge_{e.edge_label}",
            "input": {
                "type": "JDBC",
                "vendor": "POSTGRESQL",
                "driver": "org.postgresql.Driver",
                "url": jdbc_url,
                "database": rdb.database,
                "schema": rdb.schema,
                "table": query_table,
                "username": rdb.user,
                "password": rdb.password,
                "batch_size": cfg.batch_size,
            },
            "vertices": [],
            "edges": [
                {
                    "label": e.edge_label,
                    "source": [e.src_col],
                    "target": [e.dst_col],
                }
            ],
        }

        # Edge 프로퍼티가 있으면 field_mapping 추가
        if e.props:
            struct["edges"][0]["field_mapping"] = {p: p for p in e.props}

        structs.append(struct)
        via_info = f"via [{e.via_table}]" if e.has_via_table else "FK 직접 연결"
        logger.info("  Edge struct  : %s  %s  (%s → %s)",
                    e.edge_label, via_info, e.src_table, e.dst_table)

    # ── struct.json 작성 ──────────────────────────────────────────────────────
    result = {
        "version": "2.0",
        "structs": structs,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    logger.info("\n✅ struct.json 생성 완료: %s", output_file)
    logger.info("   structs 수: %d (Vertex %d + Edge %d)",
                len(structs), len(cfg.vertex_tables), len(cfg.edges))


def main():
    parser = argparse.ArgumentParser(description="mapping.yaml → struct.json 변환")
    parser.add_argument("--output", default="struct.json", help="출력 파일 경로")
    args = parser.parse_args()

    logger.info("=== struct.json 생성 ===")
    cfg = load_config(env_file=".env", mapping_file="mapping.yaml")
    generate_struct(cfg, args.output)
    logger.info("\n사용 방법:")
    logger.info("  bin/hugegraph-loader --graph %s --file %s --host %s --port %s",
                cfg.hugegraph.graph, args.output,
                cfg.hugegraph.host, cfg.hugegraph.port)


if __name__ == "__main__":
    main()
