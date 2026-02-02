# Text2SQL + RAG Agent

물류 도메인을 위한 하이브리드 질의응답 시스템. 자연어 질문을 분석하여 SQL(데이터베이스 조회) 또는 RAG(문서 검색)로 자동 라우팅합니다.

## 🎯 핵심 기능

- **Text2SQL**: 자연어 → SQL 변환하여 데이터베이스 조회
- **RAG**: 벡터 검색으로 물류 문서에서 지식 추출
- **하이브리드 라우팅**: 질문 유형에 따라 SQL/RAG 자동 선택

## 🔄 작동 방식

```
사용자 질문
    ↓
[라우팅 결정] → LLM이 질문 분석
    ↓
    ├─ SQL 워크플로우 (데이터 조회 질문)
    │   └─ 스키마 확인 → SQL 생성 → 실행 → 결과 포맷팅
    │
    ├─ RAG 워크플로우 (개념/프로세스 질문)
    │   └─ 문서 검색 → 관련성 평가 → 답변 생성
    │
    └─ DIRECT (인사말 등)
```

### 라우팅 규칙

- **SQL**: "배송 완료된 주문 수는?", "기사별 평균 배송 시간은?"
- **RAG**: "배송 프로세스는 어떻게 되나요?", "물류 최적화 방법은?"

## 📁 프로젝트 구조

```
Text2SQL/
├── src/
│   ├── app.py                 # FastAPI 웹 애플리케이션
│   ├── logistics_agent.py     # 메인 에이전트 클래스
│   ├── config.py              # 설정 관리
│   └── agents/
│       ├── routing.py          # SQL/RAG 라우팅 로직
│       ├── sql_nodes.py        # SQL 워크플로우 노드
│       ├── rag_nodes.py        # RAG 워크플로우 노드
│       ├── graph_builder.py    # LangGraph 워크플로우 구성
│       ├── prompts.py          # 프롬프트 템플릿
│       └── security.py         # SQL 쿼리 보안 검증
├── scripts/
│   ├── index_documents.py     # PDF 문서 인덱싱
│   ├── create_sample_db.py    # 샘플 데이터베이스 생성
│   └── run_app.bat            # 앱 실행 스크립트
├── data/
│   ├── logistics.db           # SQLite 데이터베이스
│   └── pdf/                   # RAG용 PDF 문서
├── templates/                  # HTML 템플릿
└── static/                    # CSS/JS 정적 파일
```

## 🔧 사용 기술 스택

### LangChain 컴포넌트

- **LangGraph**: 워크플로우 오케스트레이션
  - `StateGraph`, `MessagesState`, `ToolNode`
- **LangChain Community**: 
  - `SQLDatabase`, `SQLDatabaseToolkit` (SQL 에이전트)
  - `PyPDFDirectoryLoader` (PDF 문서 로드)
  - `InMemoryVectorStore` (벡터 스토어)
- **LangChain OpenAI**: 
  - `OpenAIEmbeddings` (문서 임베딩)
  - `init_chat_model` (LLM 초기화)
- **LangChain Core**: 
  - `MessagesState`, `HumanMessage`, `AIMessage`
  - `MemorySaver` (대화 히스토리 관리)

### 기타

- **FastAPI**: 웹 API 서버
- **SQLite**: 데이터베이스
- **pypdf**: PDF 파싱

## 📊 워크플로우 상세

### SQL 워크플로우
```
list_tables → call_get_schema → get_schema → generate_query 
→ check_query → run_query → format_results → END
```

### RAG 워크플로우  
```
generate_query_or_respond → retrieve → grade_documents 
→ (generate_answer | rewrite_question) → END
```

## 🔍 주요 특징

- **문서 구조 보존**: RAG 응답 시 PDF의 단계/구조 유지
- **보안 검증**: SQL 쿼리 보안 검사 (SELECT만 허용)
- **로깅**: 라우팅 결정 및 쿼리 실행 로그
- **대화 히스토리**: LangGraph MemorySaver로 세션별 히스토리 관리

## 📚 참고 자료

- [LangChain RAG agent](https://docs.langchain.com/oss/python/langchain/rag/)
- [LangChain SQL agent](https://docs.langchain.com/oss/python/langchain/sql-agent/)
- [LangGraph Custom RAG agent](https://docs.langchain.com/oss/python/langgraph/agentic-rag/)
- [LangGraph Custom SQL agent](https://docs.langchain.com/oss/python/langgraph/sql-agent/)
- [Document loaders](https://docs.langchain.com/oss/python/integrations/document_loaders/)
- [Vector stores](https://docs.langchain.com/oss/python/integrations/vectorstores#in-memory/)
