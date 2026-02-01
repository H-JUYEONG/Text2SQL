"""
Configuration file for the logistics Text2SQL + RAG agent.
"""
import sys
# 바이트코드(.pyc) 파일 생성 방지 - 모든 모듈에 적용
sys.dont_write_bytecode = True

import os
from dotenv import load_dotenv

load_dotenv()

# LLM Configuration
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")  # or "claude-sonnet-4-5-20250929", "gpt-4o"
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

# Embeddings Configuration
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-large")

# Database Configuration
DATABASE_URI = os.getenv("DATABASE_URI", "sqlite:///logistics.db")

# RAG Configuration
VECTOR_STORE_TYPE = os.getenv("VECTOR_STORE_TYPE", "in_memory")  # in_memory, chroma, etc.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Enterprise Configuration
MAX_QUERY_RESULTS = int(os.getenv("MAX_QUERY_RESULTS", "100"))  # 최대 결과 수 제한
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))  # 쿼리 타임아웃
ENABLE_QUERY_LOGGING = os.getenv("ENABLE_QUERY_LOGGING", "true").lower() == "true"  # 쿼리 로깅 활성화
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # 로깅 레벨

