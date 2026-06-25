# RDB → HugeGraph 적재 파이프라인 — 구현 가이드

## 1. 설정 파일 구조

접속 정보와 매핑 정보를 두 파일로 분리합니다.

```
.env          → 접속 정보 + 파이프라인 설정
mapping.yaml  → 순수 매핑 정보 ```

### 1.1 .env

```bash
# PostgreSQL
PG_HOST=
PG_PORT=
PG_DATABASE=
PG_SCHEMA=
PG_USER=
PG_PASSWORD=

# HugeGraph
HG_HOST=
HG_PORT=
HG_GRAPHSPACE=DEFAULT
HG_GRAPH=
HG_USER=
HG_PASSWORD=

# 파이프라인
BATCH_SIZE=10
```

### 1.2 mapping.yaml

```yaml
vertex_tables:
  - class_edu_office
  - class_sch

edges:
  - edge_label:  hasOffice
    src_table:   class_sch
    src_col:     info_pblntf_sch_cd
    dst_table:   class_edu_office
    dst_col:     edufc_code
    via_table:   relation_edu_manage_sch
```


## 2. Edge 정의 통일

중간 테이블이 있는 경우와 FK 직접 연결인 경우를 `edges` 하나로 통일했습니다. `via_table` 필드 유무로 두 케이스를 구분합니다.

`via_table` 있음 → 중간 테이블에서 (src_col, dst_col) 조회
`via_table` 없음 → src_table 에서 FK 직접 조회


## 3. Bulk Loader 호환

`mapping.yaml`은 `generate_struct.py` 를 통해 HugeGraph Bulk Loader의 `struct.json`으로 변환할 수 있습니다. 대량 데이터 적재가 필요해지면 Bulk Loader로 전환합니다.

```
mapping.yaml + .env  →  generate_struct.py  →  struct.json
                                                    ↓
                                          bin/hugegraph-loader
```


## 4. 사용 방법

### 4.1 초기 설정

```bash
git clone <repo>
cd pg_to_hugegraph

pip install -r requirements.txt

cp .env.example .env
vi .env             # 본인 환경의 접속 정보 입력

vi mapping.yaml     # Vertex / Edge 매핑 정의
```

### 4.2 실행

```bash
python main.py                 # 전체 실행 (스키마 → Vertex → Edge → 통계)
python main.py --step schema   # 스키마만 생성
python main.py --step vertex   # Vertex만 적재
python main.py --step edge     # Edge만 적재 (Vertex 이미 적재된 상태에서)
python main.py --step stats    # 결과 확인만
```

### 4.3 Bulk Loader 전환 시

```bash
python generate_struct.py
bin/hugegraph-loader --graph hugegraph --file struct.json --host localhost --port 8080
```


## 5. 코드 구조

```
rdb_to_hugegraph/
  ├── .env                     Git 제외
  ├── .env.example             접속 정보 양식
  ├── mapping.yaml             테이블 매핑 정의 
  ├── requirements.txt
  ├── .gitignore
  │
  ├── main.py                  REST API 적재 진입점
  ├── generate_struct.py       Bulk Loader용 struct.json 생성
  │
  ├── pipeline/
  │   ├── models.py            데이터 클래스 (ColumnInfo, TableInfo, EdgeInfo 등)
  │   ├── extractor.py         PG 메타데이터 / 행 조회
  │   └── loader.py            HugeGraph 스키마 / 적재 / 조회
  │
  └── utils/
      ├── config.py            .env + mapping.yaml 로드
      └── serializer.py        타입 매핑 + 값 직렬화
```

수정해야하는 파일은 두 개입니다:

| 파일 | 수정 빈도 | 내용 |
|------|----------|------|
| `.env` | 환경마다 | 접속 정보 |
| `mapping.yaml` | 스키마 변경 시 | 매핑 정의 |

그 외 파일은 핵심 로직이므로 함부로 수정하지 않습니다.


## 6. mapping.yaml 작성 규칙

### 6.1 기본 구조

```yaml
vertex_tables:        # Vertex로 만들 테이블 목록
  - 테이블명1
  - 테이블명2

edges:                # Edge 정의 목록
  - edge_label:  엣지명
    src_table:   출발_테이블
    src_col:     출발을_가리키는_컬럼
    dst_table:   도착_테이블
    dst_col:     도착을_가리키는_컬럼
    via_table:   중간_테이블        # 선택
    props:                          # 선택
      - 프로퍼티_컬럼1
```

### 6.2 케이스별 작성 예시

**케이스 A. 중간 테이블이 있는 다대다 관계**

```
class_sch ──< relation_edu_manage_sch >── class_edu_office
```

```yaml
edges:
  - edge_label:  hasOffice
    src_table:   class_sch
    src_col:     info_pblntf_sch_cd
    dst_table:   class_edu_office
    dst_col:     edufc_code
    via_table:   relation_edu_manage_sch
```

**케이스 B. FK로 직접 연결 (중간 테이블 없음)**

```
class_store.edufc_code  →  class_edu_office.edufc_code
```

```yaml
edges:
  - edge_label:  belongsTo
    src_table:   class_store
    src_col:     edufc_code
    dst_table:   class_edu_office
    dst_col:     edufc_code
    # via_table 없음
```

**케이스 C. 양방향 관계**

같은 중간 테이블을 두 번 정의해서 양방향 Edge를 생성합니다.

```yaml
edges:
  - edge_label:  hasOffice
    src_table:   class_sch
    src_col:     info_pblntf_sch_cd
    dst_table:   class_edu_office
    dst_col:     edufc_code
    via_table:   relation_edu_manage_sch

  - edge_label:  hasSchool
    src_table:   class_edu_office
    src_col:     edufc_code
    dst_table:   class_sch
    dst_col:     info_pblntf_sch_cd
    via_table:   relation_edu_manage_sch
```

**케이스 D. Edge에 프로퍼티 부여**

```yaml
edges:
  - edge_label:  purchased
    src_table:   customers
    src_col:     customer_id
    dst_table:   products
    dst_col:     product_id
    via_table:   order_items
    props:
      - quantity
      - unit_price
```


## 7. 향후 과제

- 현재는 rdb의 스키마 정보를 기준으로 HugeGraph 스키마를 생성하게 됩니다. rdb의 컬럼명, 테이블명이 그대로 Vertex와 Property로 생성되고 있어 향후 명명규칙을 적용하는 로직이 필요합니다.
- NotNull 기준은 rdb의 메타정보와 동일하게 처리되어있지만, 인덱스는 처리할 수 없어 새로운 인덱스 추가 로직이 필요합니다.