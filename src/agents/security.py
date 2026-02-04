"""
Query security validation module.
"""
import sys
sys.dont_write_bytecode = True

import logging
import re
from typing import Tuple, Set, Dict, Optional

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
    
    # 시스템 테이블/메타데이터 접근 차단 (PostgreSQL)
    system_tables = [
        # PostgreSQL
        'PG_CATALOG', 'INFORMATION_SCHEMA'
    ]
    for table in system_tables:
        if table in query_upper:
            logger.warning(f"Blocked system/metadata table access: {table}")
            return False, "시스템/메타데이터 테이블에 대한 직접 접근은 허용되지 않습니다."
    
    return True, ""


def extract_tables_from_query(query: str) -> Set[str]:
    """Extract table names from SQL query, preserving original case."""
    tables = set()
    
    # FROM 절에서 테이블 추출 (원본 대소문자 유지)
    # FROM table_name alias 또는 FROM table_name 형태
    from_pattern = r'\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)'
    from_matches = re.findall(from_pattern, query, re.IGNORECASE)
    tables.update(from_matches)
    
    # JOIN 절에서 테이블 추출 (원본 대소문자 유지)
    # JOIN table_name alias 또는 JOIN table_name 형태
    join_pattern = r'\b(?:INNER\s+|LEFT\s+|RIGHT\s+|FULL\s+)?JOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)'
    join_matches = re.findall(join_pattern, query, re.IGNORECASE)
    tables.update(join_matches)
    
    # 서브쿼리 내부의 테이블도 추출 (간단한 패턴, 원본 대소문자 유지)
    # FROM (SELECT ... FROM table_name) 형태
    subquery_pattern = r'FROM\s*\([^)]*FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)'
    subquery_matches = re.findall(subquery_pattern, query, re.IGNORECASE)
    tables.update(subquery_matches)
    
    return tables


def extract_columns_from_query(query: str) -> Dict[str, Set[str]]:
    """Extract column references from SQL query, mapping to their tables."""
    # table.column 형태 추출
    column_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)'
    matches = re.findall(column_pattern, query, re.IGNORECASE)
    
    table_columns: Dict[str, Set[str]] = {}
    for table, column in matches:
        table_lower = table.lower()
        if table_lower not in table_columns:
            table_columns[table_lower] = set()
        table_columns[table_lower].add(column.lower())
    
    return table_columns


def get_database_schema(db) -> Dict[str, Set[str]]:
    """Get actual database schema: table names and their columns."""
    schema = {}
    
    try:
        # 방법 1: get_usable_table_names()와 get_table_info() 사용
        if hasattr(db, 'get_usable_table_names'):
            table_names = db.get_usable_table_names()
            
            for table_name in table_names:
                table_name_lower = table_name.lower()
                schema[table_name_lower] = set()
                
                # 각 테이블의 스키마 정보 가져오기
                try:
                    if hasattr(db, 'get_table_info'):
                        table_info = db.get_table_info([table_name])
                    elif hasattr(db, 'get_table_info_no_throw'):
                        table_info = db.get_table_info_no_throw([table_name])
                    else:
                        continue
                    
                    # CREATE TABLE 문에서 컬럼 추출
                    # 형식: CREATE TABLE table_name (col1 type, col2 type, ...)
                    column_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s+[A-Za-z]+'
                    
                    # 괄호 안의 컬럼 정의 부분 추출
                    paren_match = re.search(r'\(([^)]+)\)', table_info, re.IGNORECASE | re.DOTALL)
                    if paren_match:
                        column_defs = paren_match.group(1)
                        # 각 컬럼 정의에서 컬럼명 추출
                        for col_def in column_defs.split(','):
                            col_def = col_def.strip()
                            # 컬럼명은 첫 번째 단어 (타입 앞)
                            col_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)', col_def)
                            if col_match:
                                schema[table_name_lower].add(col_match.group(1).lower())
                except Exception as e:
                    logger.debug(f"Failed to get schema for table {table_name}: {e}")
        
        # 방법 2: get_table_info_no_throw()로 전체 스키마 가져오기
        if not schema and hasattr(db, 'get_table_info_no_throw'):
            try:
                tables_info = db.get_table_info_no_throw()
                
                # 테이블별로 파싱하여 스키마 구성
                # table_info 형식: "CREATE TABLE table_name (col1 type, col2 type, ...)"
                table_pattern = r'CREATE TABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\('
                
                # 각 CREATE TABLE 블록 찾기
                for match in re.finditer(table_pattern, tables_info, re.IGNORECASE):
                    table_name = match.group(1).lower()
                    schema[table_name] = set()
                    
                    # 해당 테이블의 괄호 내용 찾기
                    start_pos = match.end()
                    # 다음 CREATE TABLE 또는 문자열 끝까지
                    end_match = re.search(r'CREATE TABLE|$', tables_info[start_pos:], re.IGNORECASE)
                    if end_match:
                        table_block = tables_info[start_pos:start_pos + end_match.start()]
                    else:
                        table_block = tables_info[start_pos:]
                    
                    # 괄호 안의 컬럼 정의 추출
                    paren_match = re.search(r'\(([^)]+)\)', table_block, re.IGNORECASE | re.DOTALL)
                    if paren_match:
                        column_defs = paren_match.group(1)
                        # 각 컬럼 정의에서 컬럼명 추출
                        for col_def in column_defs.split(','):
                            col_def = col_def.strip()
                            # 컬럼명은 첫 번째 단어 (타입 앞)
                            col_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)', col_def)
                            if col_match:
                                schema[table_name].add(col_match.group(1).lower())
            except Exception as e:
                logger.debug(f"Failed to get schema via get_table_info_no_throw: {e}")
    
    except Exception as e:
        logger.warning(f"Failed to get database schema: {e}")
    
    return schema


def extract_table_names_from_question(question: str) -> Set[str]:
    """Extract table names mentioned in user question."""
    tables = set()
    question_lower = question.lower()
    
    # "테이블" 앞의 단어 추출 (예: "customer 테이블", "orders 테이블")
    table_pattern = r'([a-zA-Z_][a-zA-Z0-9_]*)\s+테이블'
    matches = re.findall(table_pattern, question, re.IGNORECASE)
    tables.update([m.lower() for m in matches])
    
    # 영어 테이블명 패턴 (예: "customer table", "orders table")
    table_pattern_en = r'([a-zA-Z_][a-zA-Z0-9_]*)\s+table'
    matches_en = re.findall(table_pattern_en, question, re.IGNORECASE)
    tables.update([m.lower() for m in matches_en])
    
    return tables


def validate_question_schema(question: str, db) -> Tuple[bool, str]:
    """Validate that table/column names mentioned in the question exist in the database schema."""
    if not question or not question.strip():
        return True, ""  # 빈 질문은 검증 스킵
    
    try:
        # 데이터베이스 스키마 가져오기
        schema = get_database_schema(db)
        
        if not schema:
            logger.warning("Could not retrieve database schema, skipping question schema validation")
            return True, ""  # 스키마를 가져올 수 없으면 검증 스킵
        
        # 질문에서 테이블명 추출
        question_tables = extract_table_names_from_question(question)
        
        logger.debug(f"Extracted tables from question: {question_tables}")
        logger.debug(f"Available schema tables: {list(schema.keys())}")
        
        if not question_tables:
            # 질문에서 테이블명이 추출되지 않으면 검증 스킵
            return True, ""
        
        # 테이블 존재 여부 확인
        schema_tables = set(schema.keys())
        invalid_tables = []
        
        for table in question_tables:
            if table not in schema_tables:
                logger.warning(f"Table '{table}' mentioned in question not found in schema")
                invalid_tables.append(table)
        
        if invalid_tables:
            logger.warning(f"Question schema validation failed: Tables not found: {invalid_tables}")
            table_list = ', '.join([f"'{t}'" for t in invalid_tables])
            return False, f"요청하신 '{table_list}' 테이블은 데이터베이스에 존재하지 않습니다"
        
        logger.info("Question schema validation passed")
        return True, ""
    
    except Exception as e:
        logger.error(f"Error during question schema validation: {e}")
        return True, ""  # 에러 발생 시 검증 스킵


def validate_query_schema(query: str, db) -> Tuple[bool, str]:
    """Validate that all tables and columns in the query exist in the database schema."""
    if not query or not query.strip():
        return False, "빈 쿼리는 실행할 수 없습니다."
    
    try:
        # 데이터베이스 스키마 가져오기
        schema = get_database_schema(db)
        
        if not schema:
            logger.warning("Could not retrieve database schema, skipping schema validation")
            return True, ""  # 스키마를 가져올 수 없으면 검증 스킵
        
        # 쿼리에서 테이블 추출
        query_tables = extract_tables_from_query(query)
        
        logger.debug(f"Extracted tables from query: {query_tables}")
        logger.debug(f"Available schema tables: {list(schema.keys())}")
        
        if not query_tables:
            # 테이블이 추출되지 않으면 검증 스킵 (복잡한 쿼리일 수 있음)
            logger.debug("No tables extracted from query, skipping table validation")
            return True, ""
        
        # 테이블 존재 여부 확인
        schema_tables = set(schema.keys())
        invalid_tables = []
        
        for table in query_tables:
            table_lower = table.lower()
            logger.debug(f"Checking table '{table}' (lowercase: '{table_lower}') against schema")
            if table_lower not in schema_tables:
                logger.warning(f"Table '{table}' (lowercase: '{table_lower}') not found in schema")
                invalid_tables.append(table)
        
        if invalid_tables:
            logger.warning(f"Schema validation failed: Tables not found: {invalid_tables}")
            table_list = ', '.join([f"'{t}'" for t in invalid_tables])
            return False, f"요청하신 쿼리에서 {table_list} 테이블을 참조하고 있는데, 이 테이블은 데이터베이스에 존재하지 않습니다"
        
        # 컬럼 존재 여부 확인 (table.column 형태만)
        table_columns = extract_columns_from_query(query)
        
        for table_name, columns in table_columns.items():
            if table_name not in schema:
                # 이미 테이블 검증에서 걸렸을 수 있음
                continue
            
            valid_columns = schema[table_name]
            invalid_columns = []
            
            for column in columns:
                if column not in valid_columns:
                    invalid_columns.append(f"{table_name}.{column}")
            
            if invalid_columns:
                logger.warning(f"Schema validation failed: Columns not found: {invalid_columns}")
                column_list = ', '.join([f"'{c}'" for c in invalid_columns])
                return False, f"요청하신 쿼리에서 {column_list} 컬럼을 참조하고 있는데, 이 컬럼은 해당 테이블에 존재하지 않습니다"
        
        logger.info("Schema validation passed")
        return True, ""
    
    except Exception as e:
        logger.error(f"Error during schema validation: {e}")
        # 에러 발생 시 검증 실패로 처리하지 않고 통과 (안전한 방향)
        return True, ""

