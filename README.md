# Text2SQL + RAG Agent

물류 도메인을 위한 하이브리드 질의응답 시스템. 자연어 질문을 분석하여 SQL(데이터베이스 조회) 또는 RAG(문서 검색)로 자동 라우팅합니다.

> 특정 도메인에 집중하여 Text2SQL 기술을 검증하기 위해 물류 도메인을 선택했습니다.

## 🎯 핵심 기능

- **Text2SQL**: 자연어 → SQL 변환하여 PostgreSQL 데이터베이스 조회
- **RAG**: PDF 문서 폴더 로드 및 임베딩 기반 검색
- **하이브리드 라우팅**: LLM 기반 의도 분석으로 SQL/RAG 자동 선택
- **Question Agent**: 모호한 질문 분석 및 사용자에게 재질문 (HITL)
- **Human-in-the-Loop (HITL)**: 
  - 쿼리 승인/거부 (버튼 UI) 및 피드백 기반 재생성
  - 라우팅 불확실 시 사용자 확인
- **보안**: 스키마 검증, 읽기 전용 SQL만 허용

## 🔄 작동 방식

```
사용자 질문
    ↓
[Question Agent] → 모호성 분석
    ├─ 모호함 → 사용자 재질문 (HITL)
    └─ 명확함 → [라우팅] → LLM 의도 분석
        ├─ SQL: 스키마 검증 → SQL 생성 → 보안 검증 → 승인 요청 (HITL)
        │   ├─ 승인 → 실행 → 결과 반환
        │   └─ 거부 → 피드백 → 재생성
        ├─ RAG: PDF 문서 검색 → 답변 생성
        └─ UNCERTAIN → 사용자 확인 (HITL)
```

## 📁 프로젝트 구조

```
Text2SQL/
├── src/
│   ├── app.py                      # FastAPI 웹 애플리케이션
│   ├── logistics_agent.py          # 메인 에이전트
│   ├── config.py                   # 설정
│   └── agents/
│       ├── routing.py              # SQL/RAG 라우팅
│       ├── question_agent.py       # 모호성 분석, 질문 분할
│       ├── sql_nodes.py            # SQL 워크플로우 (승인/거부)
│       ├── rag_nodes.py            # RAG 워크플로우
│       ├── graph_builder.py        # LangGraph 구성
│       ├── prompts.py              # 프롬프트 템플릿
│       └── security.py             # 보안/스키마 검증
├── scripts/                        # 유틸리티 스크립트
├── data/                           # DB 및 PDF 문서
├── templates/                      # HTML 템플릿
└── static/                         # CSS/JS (버튼 UI)
```

## 🔧 기술 스택

### Frontend
- **HTML/CSS/JavaScript** - 웹 인터페이스
- **Vanilla JS** - 프레임워크 없는 순수 JavaScript

### Backend
- **Python 3.11+** - 프로그래밍 언어
- **FastAPI** - 비동기 웹 프레임워크
- **LangGraph 1.0+** - AI 에이전트 워크플로우 오케스트레이션
- **LangChain 1.2+** - LLM 통합 및 SQL/RAG 에이전트
- **PostgreSQL** - 대상 데이터베이스
- **psycopg[binary]** - PostgreSQL 드라이버
- **langgraph-checkpoint-postgres** - HITL 상태 저장 (사용자 응답 대기 중 워크플로우 상태 유지)

### Infrastructure
- **Docker** - 컨테이너화 (이미지 빌드 및 실행)
- **docker-compose** - 멀티 컨테이너 오케스트레이션 (앱 + PostgreSQL 함께 실행)
  - 현재 배포 방식: `docker-compose` 사용 (내부적으로 Docker 사용)
  - `Dockerfile`로 앱 이미지 빌드 → `docker-compose.yml`로 서비스 실행
- **GitHub Actions** - CI/CD 파이프라인 (자동 빌드 및 배포)

## 🔄 CI/CD

### GitHub Actions

자동 빌드 및 배포를 위한 GitHub Actions 워크플로우가 설정되어 있습니다:

- **트리거**: `main` 또는 `master` 브랜치에 push 시 자동 실행
- **작업**:
  1. 코드 체크아웃
  2. Secrets 검증 (EC2 접속 정보)
  3. EC2 서버에 SSH 연결
  4. 코드 pull 및 Docker 이미지 빌드
  5. docker-compose로 서비스 재시작
  6. 헬스 체크

### 워크플로우 파일

`.github/workflows/deploy-ec2.yml` 파일에서 CI/CD 설정을 관리합니다.

### 필요한 GitHub Secrets

EC2 배포를 위해 다음 Secrets를 설정해야 합니다:

- `EC2_HOST`: EC2 인스턴스 IP 주소 또는 도메인
- `EC2_USERNAME`: EC2 사용자명 (예: `ubuntu`, `ec2-user`)
- `EC2_SSH_KEY`: EC2 SSH 개인 키 (전체 내용)

**설정 방법**: GitHub 저장소 → Settings → Secrets and variables → Actions → New repository secret

## 📝 사용 예시

### SQL 질문 (거부 후 재생성)
```
사용자: "배송이 완료되지 않은 주문 목록을 보여줘"
에이전트: [SQL 생성] → [승인 요청 버튼]
사용자: [거부] → "고객 이름과 구매 물품까지 알고싶어"
에이전트: [피드백 반영하여 재생성] → [승인 요청]
```

### 모호한 질문 (HITL)
```
사용자: "성과가 좋은 기사 조회해줘"
에이전트: "성과 기준이 무엇인가요? (매출, 배송 건수 등)"
사용자: "배송 완료 건수 기준으로"
에이전트: [SQL 생성 및 실행] → [결과 반환]
```

### RAG 질문 (PDF 문서 검색)
```
사용자: "배송 프로세스는 어떻게 되나요?"
에이전트: [PDF 문서 검색] → [답변 생성]
```

## 🔒 보안

- **읽기 전용**: SELECT 쿼리만 허용
- **스키마 검증**: 존재하지 않는 테이블/컬럼 참조 차단
- **쿼리 승인**: 기업 환경에서 DB 손상 방지
- **타임아웃**: 쿼리 실행 시간 제한

## 📚 참고 자료

- [LangChain RAG agent](https://docs.langchain.com/oss/python/langchain/rag/)
- [LangChain SQL agent](https://docs.langchain.com/oss/python/langchain/sql-agent/)
- [LangGraph Custom RAG agent](https://docs.langchain.com/oss/python/langgraph/agentic-rag/)
- [LangGraph Custom SQL agent](https://docs.langchain.com/oss/python/langgraph/sql-agent/)
- [Document loaders](https://docs.langchain.com/oss/python/integrations/document_loaders/)
- [Vector stores](https://docs.langchain.com/oss/python/integrations/vectorstores#in-memory/)  