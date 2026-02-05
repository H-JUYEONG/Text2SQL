"""
Configuration file for the logistics Text2SQL + RAG agent.
"""
import sys
# 바이트코드(.pyc) 파일 생성 방지 - 모든 모듈에 적용
sys.dont_write_bytecode = True

import os
from dotenv import load_dotenv

# 환경 변수가 없을 때만 .env 파일 로드 (Docker 환경 변수가 우선)
# override=False: 환경 변수가 이미 설정되어 있으면 .env 파일 값으로 덮어쓰지 않음
load_dotenv(override=False)

# LLM Configuration
LLM_MODEL = "gpt-4o-mini"  # or "claude-sonnet-4-5-20250929", "gpt-4o", "claude-opus"
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
# LLM 응답 최대 토큰 수 설정
# 기업 환경 고려: 100개 결과도 처리 가능하도록 충분한 토큰 수 필요
# 항목당 토큰 수: 간단한 항목 80-100토큰, 복잡한 항목(주문 목록 등) 150-250토큰
# 기본값: 8000 토큰 (100개 * 80토큰 = 8000, 복잡한 항목 고려 시 더 필요)
# 환경변수로 조정 가능: LLM_MAX_TOKENS=10000 (더 긴 응답 필요 시)
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))  # LLM 응답 최대 토큰 수

# Embeddings Configuration
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-large")

# Database Configuration
DATABASE_URI = os.getenv("DATABASE_URI", "postgresql://user:password@localhost:5432/dbname")

# RAG Configuration
VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "in_memory")  # in_memory, chroma, etc.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Admin / Security (no-login authorization signals)
# 관리자 권한 판별용 키 (요청 헤더 X-ADMIN-KEY 와 비교)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
# 관리자 허용 IP allowlist (쉼표로 구분)
# 예: "127.0.0.1,112.145.77.209"
ADMIN_IP_ALLOWLIST = [
    ip.strip() for ip in os.getenv("ADMIN_IP_ALLOWLIST", "").split(",") if ip.strip()
]

# Enterprise Configuration
MAX_QUERY_RESULTS = int(os.getenv("MAX_QUERY_RESULTS", "100"))  # 최대 결과 수 제한
SMALL_RESULT_THRESHOLD = int(os.getenv("SMALL_RESULT_THRESHOLD", "50"))  # 이 개수 이하면 LIMIT 없이 전체 조회
LIMIT_FOR_LARGE_RESULTS = int(os.getenv("LIMIT_FOR_LARGE_RESULTS", "100"))  # 건수가 많을 때 적용할 LIMIT (기업 환경: 100개)
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))  # 쿼리 타임아웃
ENABLE_QUERY_LOGGING = os.getenv("ENABLE_QUERY_LOGGING", "true").lower() == "true"  # 쿼리 로깅 활성화
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # 로깅 레벨

# Checkpoint Configuration (for HITL)
# 체크포인트 저장용 DB URI (기본값: 메인 DB와 동일 - 별도 DB 불필요)
# 같은 DB를 사용해도 되고, 필요시 별도 DB URI를 설정할 수 있습니다.
# LangGraph의 PostgresSaver가 자동으로 체크포인트 테이블을 생성합니다.
CHECKPOINT_DB_URI = os.getenv("CHECKPOINT_DB_URI", DATABASE_URI)
USE_DB_CHECKPOINTER = os.getenv("USE_DB_CHECKPOINTER", "false").lower() == "true"  # DB 기반 체크포인터 사용 여부

