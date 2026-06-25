"""
공유 데이터 클래스
"""
from dataclasses import dataclass, field


@dataclass
class ColumnInfo:
    name: str
    sql_type: str
    hg_type: str
    is_pk: bool
    nullable: bool


@dataclass
class TableInfo:
    name: str
    columns: list       # List[ColumnInfo]
    primary_keys: list


@dataclass
class EdgeInfo:
    """
    추출된 Edge 정보 (config.EdgeDef + 실제 컬럼 정보 포함)
    via_table 있음 → 중간 테이블에서 (src_col, dst_col) 조회
    via_table 없음 → src_table 에서 (src_col) 직접 조회
    """
    edge_label: str
    src_table: str
    src_col: str
    dst_table: str
    dst_col: str
    via_table: str               # 빈 문자열이면 FK 직접 연결
    prop_cols: list              # List[ColumnInfo] - Edge 프로퍼티 컬럼
    src_pk_cols: list            # src Vertex의 PK 컬럼명 목록

    @property
    def has_via_table(self) -> bool:
        return bool(self.via_table)

    @property
    def query_table(self) -> str:
        """실제로 조회할 테이블명"""
        return self.via_table if self.has_via_table else self.src_table


@dataclass
class DBMetadata:
    schema: str
    vertex_tables: list    # List[TableInfo]
    edges: list            # List[EdgeInfo]
