# Logistics Text2SQL + RAG Agent

물류회사 도메인을 위한 Text2SQL + RAG 통합 에이전트입니다. LangGraph 1.0+를 사용하여 구현되었습니다.

## 기능

- **Text2SQL**: 자연어 질의를 SQL 쿼리로 변환하여 데이터베이스에서 정보를 조회
- **RAG (Retrieval-Augmented Generation)**: 물류 관련 문서에서 지식을 검색하여 답변 생성
- **하이브리드 라우팅**: 질문 유형에 따라 SQL 또는 RAG를 자동으로 선택

## 요구사항

- Python 3.8+
- LangGraph 1.0+
- LangChain 0.3+
- 데이터베이스 (SQLite, PostgreSQL, MySQL 등)
- LLM API 키 (OpenAI, Anthropic, Google 등)

## 설치

1. 저장소 클론 또는 파일 다운로드

2. 패키지 설치:
```bash
pip install -r requirements.txt
```

3. 환경 변수 설정:
```bash
# env_example.txt를 참고하여 .env 파일을 생성하세요
# .env 파일을 열어서 API 키를 설정하세요
```

4. (선택사항) 샘플 데이터베이스 생성:
```bash
python create_sample_db.py
```

## 사용법

### 1. 데이터베이스 준비

샘플 데이터베이스를 생성하거나 직접 데이터베이스를 준비하세요:

**옵션 1: 샘플 데이터베이스 사용**
```bash
python create_sample_db.py
```
이 스크립트는 `logistics.db` 파일을 생성하고 shipments, orders, warehouses 테이블에 샘플 데이터를 삽입합니다.

**옵션 2: 직접 데이터베이스 생성**
```python
import sqlite3

conn = sqlite3.connect('logistics.db')
cursor = conn.cursor()

# 예제 테이블 생성
cursor.execute('''
    CREATE TABLE IF NOT EXISTS shipments (
        id INTEGER PRIMARY KEY,
        tracking_number TEXT,
        origin TEXT,
        destination TEXT,
        status TEXT,
        created_at TIMESTAMP
    )
''')

conn.commit()
conn.close()
```

### 2. RAG 문서 인덱싱 (선택사항)

물류 관련 문서를 `data/` 디렉토리에 추가하고 인덱싱:

```bash
# 문서 구조
data/
  txt/
    logistics_guide.txt
    shipping_policy.txt
  pdf/
    warehouse_manual.pdf
  csv/
    product_catalog.csv
```

인덱싱 실행:
```python
python index_documents.py
```

### 3. 에이전트 실행

기본 사용 예제:
```python
from logistics_agent import LogisticsAgent

# 에이전트 초기화
agent = LogisticsAgent(
    db_uri="sqlite:///logistics.db",
    vector_store=vector_store,  # RAG를 사용하는 경우
)

# 질의 실행
query = "What tables are available in the database?"
response = agent.invoke(query)
print(response["messages"][-1].content)
```

스트리밍 모드:
```python
for chunk in agent.stream(query):
    for node, update in chunk.items():
        if "messages" in update:
            print(update["messages"][-1].content)
```

예제 스크립트 실행:
```bash
python example.py
```

## 질의 예제

### SQL 질의
- "What tables are available in the database?"
- "Show me all shipments from Seoul"
- "Count the number of pending orders"
- "What is the schema of the shipments table?"

### RAG 질의
- "What is cross-docking?"
- "How does inventory management work?"
- "Explain the shipping policy"

## 아키텍처

에이전트는 다음 노드들로 구성됩니다:

1. **route_query**: 질문을 분석하여 SQL 또는 RAG 라우팅 결정
2. **SQL 워크플로우**:
   - `list_tables`: 테이블 목록 조회
   - `get_schema`: 스키마 정보 조회
   - `generate_sql`: SQL 쿼리 생성
   - `check_query`: 쿼리 검증
   - `run_query`: 쿼리 실행
3. **RAG 워크플로우**:
   - `retrieve`: 문서 검색
   - `grade_documents`: 문서 관련성 평가
   - `rewrite_question`: 질문 재작성 (필요시)
   - `generate_answer`: 최종 답변 생성

## 설정

`config.py` 또는 환경 변수를 통해 설정할 수 있습니다:

- `LLM_MODEL`: 사용할 LLM 모델 (기본값: gpt-4o-mini)
- `DATABASE_URI`: 데이터베이스 연결 문자열
- `EMBEDDINGS_MODEL`: 임베딩 모델
- `CHUNK_SIZE`: 문서 청크 크기
- `CHUNK_OVERLAP`: 청크 오버랩 크기

## 문제 해결

### 데이터베이스 연결 오류
- `DATABASE_URI`가 올바른지 확인
- 데이터베이스 파일이 존재하는지 확인

### API 키 오류
- `.env` 파일에 API 키가 설정되어 있는지 확인
- 환경 변수가 올바르게 로드되는지 확인

### RAG가 작동하지 않음
- `data/` 디렉토리에 문서가 있는지 확인
- `index_documents.py`를 실행하여 문서를 인덱싱했는지 확인

## 라이선스

MIT License

## 참고 자료

- [LangGraph 문서](https://langchain-ai.github.io/langgraph/)
- [LangChain 문서](https://python.langchain.com/)
- [SQL Agent 튜토리얼](https://langchain-ai.github.io/langgraph/tutorials/sql-agent/)
- [RAG Agent 튜토리얼](https://langchain-ai.github.io/langgraph/tutorials/agentic-rag/)

