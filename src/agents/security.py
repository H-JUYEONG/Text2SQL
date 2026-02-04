"""
Query security validation module.
"""
import sys
sys.dont_write_bytecode = True

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def validate_query_security(query: str) -> Tuple[bool, str]:
    """Validate SQL query for security - enterprise requirement."""
    if not query or not query.strip():
        return False, "빈 쿼리는 실행할 수 없습니다."
    
    query_upper = query.upper().strip()
    
    # 위험한 SQL 키워드 차단
    dangerous_keywords = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 
        'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
        'MERGE', 'REPLACE', 'LOAD', 'COPY', 'IMPORT', 'EXPORT'
    ]
    
    for keyword in dangerous_keywords:
        if keyword in query_upper:
            logger.warning(f"Blocked dangerous SQL keyword: {keyword}")
            return False, f"보안상의 이유로 {keyword} 문은 실행할 수 없습니다. 읽기 전용 쿼리만 허용됩니다."
    
    # SELECT로 시작하는지 확인
    if not query_upper.startswith('SELECT'):
        return False, "SELECT 쿼리만 실행할 수 있습니다."
    
    # 시스템 테이블/메타데이터 접근 차단 (SQLite, PostgreSQL 공통)
    system_tables = [
        # SQLite
        'SQLITE_MASTER', 'SQLITE_TEMP_MASTER', 'SQLITE_SEQUENCE',
        # PostgreSQL
        'PG_CATALOG', 'INFORMATION_SCHEMA'
    ]
    for table in system_tables:
        if table in query_upper:
            logger.warning(f"Blocked system/metadata table access: {table}")
            return False, "시스템/메타데이터 테이블에 대한 직접 접근은 허용되지 않습니다."
    
    return True, ""

