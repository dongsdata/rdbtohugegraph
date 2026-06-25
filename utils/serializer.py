"""
PG 타입 → HugeGraph 타입 매핑
PG 값 → HugeGraph 호환 타입 직렬화
"""
import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


# PG 타입 → HugeGraph PropertyKey 타입
PG_TYPE_MAP: dict[str, str] = {
    "INTEGER": "int",    "INT": "int",       "INT4": "int",    "SMALLINT": "int",
    "INT2": "int",       "SERIAL": "int",
    "BIGINT": "long",    "INT8": "long",     "BIGSERIAL": "long",
    "REAL": "float",     "FLOAT4": "float",
    "DOUBLE PRECISION": "double", "FLOAT8": "double", "FLOAT": "double",
    "NUMERIC": "double", "DECIMAL": "double","MONEY": "double",
    "VARCHAR": "text",   "CHARACTER VARYING": "text",
    "CHAR": "text",      "CHARACTER": "text","TEXT": "text",   "BPCHAR": "text",
    "BOOLEAN": "int",    "BOOL": "int",       # HugeGraph boolean 미지원 → 0/1
    "DATE": "text",      "TIME": "text",     "TIMETZ": "text",
    "TIMESTAMP": "text", "TIMESTAMPTZ": "text", "INTERVAL": "text",
    "UUID": "text",      "JSON": "text",     "JSONB": "text",
    "BYTEA": "text",     "INET": "text",     "CIDR": "text",   "MACADDR": "text",
    "OID": "long",
}

# HugeGraph 타입 → pyhugegraph schema 메서드명
HG_TYPE_METHOD: dict[str, str] = {
    "text": "asText",
    "int": "asInt",
    "long": "asLong",
    "float": "asFloat",
    "double": "asDouble",
}


def map_pg_type(sql_type_str: str) -> str:
    """PG 타입 문자열 → HugeGraph 타입"""
    base = re.sub(r"\(.*\)", "", sql_type_str).strip().upper()
    if base.endswith("[]") or base.startswith("ARRAY"):
        return "text"
    return PG_TYPE_MAP.get(base, "text")


def pg_serialize(v: Any) -> Any:
    """Python/PG 값 → HugeGraph 호환 타입으로 변환"""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    return str(v)
