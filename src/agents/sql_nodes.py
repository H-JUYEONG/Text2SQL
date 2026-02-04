"""
SQL Agent Nodes for LangGraph workflow.
"""
import sys
sys.dont_write_bytecode = True

import logging
from typing import Literal
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import MessagesState, END
from langgraph.prebuilt import ToolNode

from src.agents.prompts import get_generate_query_prompt, get_check_query_prompt, get_format_results_prompt, get_korean_prompt
from src.agents.security import validate_query_security, validate_query_schema, validate_question_schema
from src.config import LLM_MAX_TOKENS

logger = logging.getLogger(__name__)


class SQLNodes:
    """SQL workflow nodes for the logistics agent."""
    
    def __init__(self, agent):
        """Initialize with reference to the main agent."""
        self.agent = agent
        self.model = agent.model
        self.db = agent.db
        self.list_tables_tool = agent.list_tables_tool
        self.get_schema_tool = agent.get_schema_tool
        self.run_query_tool = agent.run_query_tool
        self.max_query_results = agent.max_query_results
        self.small_result_threshold = agent.small_result_threshold
        self.limit_for_large_results = agent.limit_for_large_results
        self.enable_logging = agent.enable_logging
    
    def list_tables(self, state: MessagesState):
        """List all available tables - predetermined tool call pattern."""
        # 사용자 질문에서 테이블명 추출 및 스키마 검증
        messages = state["messages"]
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        if user_question:
            # 질문에서 언급한 테이블명이 실제 DB에 있는지 확인
            is_valid, error_msg = validate_question_schema(user_question, self.db)
            if not is_valid:
                logger.warning(f"❌ [QUESTION SCHEMA VALIDATION] Question schema validation failed: {error_msg}")
                error_response = AIMessage(
                    content=f"죄송합니다. {error_msg} 현재 데이터베이스에 존재하는 테이블과 컬럼만 조회할 수 있습니다.",
                    id=messages[-1].id if messages else None
                )
                return {"messages": [error_response]}
        
        tool_call = {
            "name": "sql_db_list_tables",
            "args": {},
            "id": "list_tables_001",
            "type": "tool_call",
        }
        tool_call_message = AIMessage(content="", tool_calls=[tool_call])
        
        tool_message = self.list_tables_tool.invoke(tool_call)
        response = AIMessage(f"Available tables: {tool_message.content}")
        
        return {"messages": [tool_call_message, tool_message, response]}
    
    def call_get_schema(self, state: MessagesState):
        """Call the get schema tool - force tool call pattern."""
        llm_with_tools = self.model.bind_tools([self.get_schema_tool], tool_choice="any")
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}
    
    def generate_query(self, state: MessagesState):
        """Generate SQL query - following Custom SQL Agent pattern."""
        # 이전에는 하드코딩된 5행으로 제한되어 있어 결과가 불필요하게 잘리는 문제가 있었음.
        # 이제는 설정된 MAX_QUERY_RESULTS 값을 그대로 사용하여,
        # 기본적으로 충분한 개수를 허용하되, 실제 LIMIT 사용 여부는 프롬프트 규칙에 맡긴다.
        max_results = self.max_query_results
        generate_query_system_prompt = get_generate_query_prompt(self.db.dialect, max_results)
        
        system_message = {
            "role": "system",
            "content": generate_query_system_prompt,
        }
        # 사용자 질문 로깅 (마지막 HumanMessage 사용)
        if self.enable_logging:
            messages = state["messages"]
            last_human_message = None
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    last_human_message = msg
                    break
            user_question = last_human_message.content if last_human_message else (messages[0].content if messages else "Unknown")
            logger.info("=" * 80)
            logger.info("📝 [USER QUESTION] 사용자 질문:")
            logger.info(f"질문: {user_question}")
            logger.info("=" * 80)
        
        # Check if we have query results AND if there's a new question after the results
        messages = state["messages"]
        last_human_idx = -1
        last_query_result_idx = -1
        
        # Find the last HumanMessage
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break
        
        # Find the last query result (tool message or content with query results)
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                last_query_result_idx = i
                break
            elif hasattr(msg, 'content') and msg.content:
                content = str(msg.content)
                if (content.strip().startswith('[') and '),' in content) or \
                   (content.strip().startswith('(') and '),' in content):
                    if 'table_info' not in content.lower() and 'pragma' not in content.lower() and \
                       ('),' in content and len(content) > 50):
                        last_query_result_idx = i
                        break
        
        # Determine if we should use previous results or generate new query
        has_query_results = last_query_result_idx >= 0
        has_new_question_after_results = last_human_idx > last_query_result_idx if has_query_results else False
        
        # If we have query results AND the last question came BEFORE the results, format the answer
        if has_query_results and not has_new_question_after_results:
            format_instruction = {
                "role": "system",
                "content": "You have received SQL query results. Convert them into a natural, conversational Korean answer. Format the raw data (tuples, lists) as readable text with proper formatting. Include all information from the results."
            }
            response = self.model.invoke([format_instruction] + state["messages"])
            if self.enable_logging:
                logger.info("📝 [ANSWER FORMATTING] 쿼리 결과를 자연어로 포맷팅 중...")
        else:
            # New question or no previous results - generate new query
            if self.enable_logging and has_new_question_after_results:
                logger.info("🆕 [NEW QUESTION DETECTED] 새로운 질문이 감지되었습니다. 새 쿼리를 생성합니다.")
            if self.enable_logging:
                logger.info("🤖 [LLM PROCESSING] LLM이 쿼리를 생성하는 중...")
            llm_with_tools = self.model.bind_tools([self.run_query_tool])
            response = llm_with_tools.invoke([system_message] + state["messages"])
        
        # 쿼리 생성 로깅 (기업 환경)
        if self.enable_logging:
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tool_call in response.tool_calls:
                    if tool_call.get('name') == 'sql_db_query':
                        generated_query = tool_call.get('args', {}).get('query', '')
                        if generated_query:
                            logger.info("=" * 80)
                            logger.info("🔍 [QUERY GENERATION] 에이전트가 생성한 SQL 쿼리:")
                            logger.info(f"SQL: {generated_query}")
                            logger.info("=" * 80)
            elif hasattr(response, 'content') and response.content:
                logger.info("💬 [DIRECT RESPONSE] LLM이 직접 답변을 생성했습니다.")
                logger.info(f"답변: {response.content[:200]}...")
        
        # LLM이 직접 답변을 생성한 경우, 보안 검증 메시지인지 확인
        # 보안 검증 메시지가 아닌 경우에만 스키마 검증을 수행할 수 있도록 함
        if hasattr(response, 'content') and response.content and not hasattr(response, 'tool_calls'):
            content = str(response.content)
            security_rejection_msg = "죄송합니다. 데이터 수정, 삭제, 생성 등의 작업은 보안상의 이유로 허용되지 않습니다. 읽기 전용 조회만 가능합니다."
            # 보안 검증 메시지가 아닌 경우, 스키마 검증을 위해 쿼리를 추출해볼 수 있음
            # 하지만 이 경우는 LLM이 보안 검증을 수행한 것이므로 그대로 반환
            if security_rejection_msg in content:
                # 보안 검증 메시지인 경우 그대로 반환
                return {"messages": [response]}
        
        return {"messages": [response]}
    
    def check_query(self, state: MessagesState):
        """Check SQL query for common mistakes and security - following Custom SQL Agent pattern."""
        check_query_system_prompt = get_check_query_prompt(self.db.dialect)
        
        system_message = {
            "role": "system",
            "content": check_query_system_prompt,
        }
        
        # 먼저 보안 검증 수행
        tool_call = state["messages"][-1].tool_calls[0]
        query = tool_call["args"]["query"]
        
        # 쿼리 검증 전 로깅
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("🔒 [QUERY VALIDATION] 쿼리 검증 시작")
            logger.info(f"Original Query: {query}")
            logger.info("=" * 80)
        
        # 한국어 상태 값 사용 검증 및 수정
        korean_status_values = ['배송 완료', '배송완료', '배송중', '대기중', '지연', '배송 지연']
        has_korean_status = any(kv in query for kv in korean_status_values)
        
        if has_korean_status:
            logger.warning("⚠️  [STATUS VALUE ERROR] 한국어 상태 값이 쿼리에 사용되었습니다!")
            logger.warning(f"문제가 있는 쿼리: {query}")
            # 한국어를 영어로 매핑
            query_fixed = query
            query_fixed = query_fixed.replace("'배송 완료'", "'delivered'")
            query_fixed = query_fixed.replace("'배송완료'", "'delivered'")
            query_fixed = query_fixed.replace("'배송중'", "'shipped'")
            query_fixed = query_fixed.replace("'대기중'", "'pending'")
            query_fixed = query_fixed.replace("'지연'", "'delayed'")
            query_fixed = query_fixed.replace("'배송 지연'", "'delayed'")
            
            if query_fixed != query:
                logger.warning("🔧 [AUTO FIX] 한국어 상태 값을 영어로 자동 수정합니다.")
                logger.warning(f"수정된 쿼리: {query_fixed}")
                tool_call["args"]["query"] = query_fixed
                query = query_fixed
        
        # 보안 검증
        is_valid, error_msg = validate_query_security(query)
        if not is_valid:
            logger.warning(f"❌ [SECURITY BLOCK] Query security validation failed: {error_msg}")
            logger.warning(f"Blocked Query: {query}")
            error_response = AIMessage(
                content=f"쿼리 검증 실패: {error_msg}",
                id=state["messages"][-1].id
            )
            return {"messages": [error_response]}
        
        logger.info("✅ [SECURITY PASS] 쿼리 보안 검증 통과")
        
        # 스키마 검증
        is_schema_valid, schema_error_msg = validate_query_schema(query, self.db)
        if not is_schema_valid:
            logger.warning(f"❌ [SCHEMA VALIDATION BLOCK] Query schema validation failed: {schema_error_msg}")
            logger.warning(f"Blocked Query: {query}")
            # 스키마 검증 실패 시 더 친절하고 구체적인 메시지 제공 (보안 검증 메시지와 명확히 구분)
            error_response = AIMessage(
                content=f"죄송합니다. {schema_error_msg} 현재 데이터베이스에 존재하는 테이블과 컬럼만 조회할 수 있습니다. 질문을 다시 정리해서 물어봐 주시겠어요?",
                id=state["messages"][-1].id
            )
            return {"messages": [error_response]}
        
        logger.info("✅ [SCHEMA VALIDATION PASS] 쿼리 스키마 검증 통과")
        
        # Generate an artificial user message to check
        user_message = {"role": "user", "content": query}
        llm_with_tools = self.model.bind_tools([self.run_query_tool], tool_choice="any")
        response = llm_with_tools.invoke([system_message, user_message])
        response.id = state["messages"][-1].id
        
        # 검증 후 최종 쿼리 로깅
        if self.enable_logging and hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.get('name') == 'sql_db_query':
                    validated_query = tool_call.get('args', {}).get('query', '')
                    if validated_query:
                        logger.info("=" * 80)
                        logger.info("✅ [QUERY VALIDATED] 검증 완료된 최종 SQL 쿼리:")
                        logger.info(f"SQL: {validated_query}")
                        if validated_query != query:
                            logger.info("⚠️  [QUERY MODIFIED] 원본 쿼리가 수정되었습니다.")
                            logger.info(f"Original: {query}")
                        logger.info("=" * 80)
        
        return {"messages": [response]}
    
    def request_query_approval(self, state: MessagesState):
        """기업용 HITL: 생성된 SQL 쿼리를 사용자에게 보여주고 승인 요청"""
        messages = state["messages"]
        
        # check_query에서 반환한 메시지에서 쿼리 추출
        query = None
        tool_call_to_save = None
        
        # 가장 최근의 tool_calls가 있는 메시지 찾기 (check_query에서 반환한 것)
        for msg in reversed(messages):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if tool_call.get('name') == 'sql_db_query':
                        query = tool_call.get('args', {}).get('query', '')
                        tool_call_to_save = tool_call  # 나중에 사용하기 위해 저장
                        break
                if query:
                    break
        
        if not query:
            # 쿼리를 찾을 수 없는 경우 에러
            if self.enable_logging:
                logger.error("❌ [QUERY APPROVAL] 쿼리를 찾을 수 없습니다.")
            error_response = AIMessage(
                content="쿼리를 찾을 수 없습니다. 다시 시도해주세요.",
                id=messages[-1].id if messages else None
            )
            return {"messages": [error_response]}
        
        # 사용자에게 쿼리 승인 요청
        # tool_call 정보도 metadata에 저장하여 나중에 쉽게 찾을 수 있도록
        
        # 쿼리를 읽기 쉽게 포맷팅 (들여쓰기 및 줄바꿈)
        formatted_query = self._format_sql_query(query)
        
        approval_message = AIMessage(
            content=f"""🔍 **SQL 쿼리 실행 승인 요청**

다음 쿼리를 실행하려고 합니다. 검토 후 승인해주세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**생성된 SQL 쿼리:**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{formatted_query}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**승인 방법**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ **승인**: "승인", "실행", "예", "ok", "yes" 등
❌ **거부**: "거부", "취소", "아니오", "no", "수정" 등

승인하시면 쿼리가 실행되고 결과를 반환합니다.""",
            metadata={
                "needs_user_response": True,
                "workflow_paused": True,
                "query_approval_pending": True,
                "pending_query": query,
                "pending_tool_call": tool_call_to_save  # tool_call도 저장
            },
            id=messages[-1].id if messages else None
        )
        
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("🔍 [QUERY APPROVAL REQUEST] 사용자에게 쿼리 승인 요청")
            logger.info(f"SQL: {query}")
            logger.info("=" * 80)
        
        return {"messages": [approval_message]}
    
    def _format_sql_query(self, query: str) -> str:
        """SQL 쿼리를 읽기 쉽게 포맷팅"""
        import re
        
        # 기본 포맷팅: 키워드 대문자화 및 줄바꿈
        query = query.strip()
        
        # 주요 SQL 키워드를 대문자로 변환
        keywords = [
            'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 
            'FULL JOIN', 'ON', 'GROUP BY', 'ORDER BY', 'HAVING', 'UNION', 'INSERT', 
            'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'AND', 'OR', 'NOT', 
            'IN', 'EXISTS', 'LIKE', 'BETWEEN', 'AS', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN',
            'DISTINCT', 'LIMIT', 'OFFSET', 'ASC', 'DESC'
        ]
        
        # 키워드 대문자화 (대소문자 구분 없이, 긴 키워드부터)
        for keyword in sorted(keywords, key=len, reverse=True):
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            query = pattern.sub(keyword, query)
        
        # 한 줄 쿼리인 경우 줄바꿈으로 분리
        if '\n' not in query or len(query.split('\n')) == 1:
            # SELECT, FROM, WHERE 등을 줄바꿈으로 분리
            query = re.sub(r'\s+(FROM)\s+', r'\n\1 ', query, flags=re.IGNORECASE)
            query = re.sub(r'\s+(WHERE)\s+', r'\n\1 ', query, flags=re.IGNORECASE)
            query = re.sub(r'\s+(JOIN|INNER JOIN|LEFT JOIN|RIGHT JOIN|FULL JOIN)\s+', r'\n  \1 ', query, flags=re.IGNORECASE)
            query = re.sub(r'\s+(ON)\s+', r'\n    \1 ', query, flags=re.IGNORECASE)
            query = re.sub(r'\s+(GROUP BY|ORDER BY|HAVING)\s+', r'\n\1 ', query, flags=re.IGNORECASE)
            query = re.sub(r'\s+(AND|OR)\s+', r'\n  \1 ', query, flags=re.IGNORECASE)
        
        # 들여쓰기 정리
        lines = query.split('\n')
        formatted_lines = []
        indent_level = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # FROM, WHERE, GROUP BY, ORDER BY는 들여쓰기 없음
            if re.match(r'^(FROM|WHERE|GROUP BY|ORDER BY|HAVING)', line, re.IGNORECASE):
                indent_level = 0
            # JOIN은 2칸 들여쓰기
            elif re.match(r'^(JOIN|INNER JOIN|LEFT JOIN|RIGHT JOIN|FULL JOIN)', line, re.IGNORECASE):
                indent_level = 1
            # ON은 3칸 들여쓰기
            elif re.match(r'^(ON)', line, re.IGNORECASE):
                indent_level = 2
            # AND, OR는 1칸 들여쓰기
            elif re.match(r'^(AND|OR)', line, re.IGNORECASE):
                indent_level = 1
            
            formatted_lines.append('  ' * indent_level + line)
        
        return '\n'.join(formatted_lines)
    
    def process_query_approval(self, state: MessagesState):
        """사용자의 쿼리 승인/거부 응답 처리"""
        messages = state["messages"]
        
        # 마지막 사용자 메시지 찾기
        user_response = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_response = msg.content.lower().strip()
                break
        
        if not user_response:
            # 사용자 응답이 없는 경우 다시 승인 요청
            return self.request_query_approval(state)
        
        # 승인 키워드
        approval_keywords = ["승인", "실행", "예", "ok", "yes", "y", "확인", "좋아", "좋아요"]
        # 거부 키워드
        rejection_keywords = ["거부", "취소", "아니오", "no", "n", "수정", "다시", "재생성"]
        
        is_approved = any(keyword in user_response for keyword in approval_keywords)
        is_rejected = any(keyword in user_response for keyword in rejection_keywords)
        
        # 승인된 경우: 쿼리 실행을 위해 run_query로 진행
        if is_approved:
            if self.enable_logging:
                logger.info("✅ [QUERY APPROVED] 사용자가 쿼리 승인")
            
            # tool_call 찾기: 우선순위
            # 1. metadata에 저장된 pending_tool_call
            # 2. 이전 메시지의 tool_calls
            # 3. metadata의 pending_query로 새로 생성
            tool_call_to_execute = None
            pending_query = None
            
            # 1. metadata에서 pending_tool_call 확인 (가장 확실한 방법)
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                    tool_call_to_execute = msg.metadata.get("pending_tool_call")
                    if tool_call_to_execute:
                        if self.enable_logging:
                            logger.info("✅ [QUERY APPROVAL] metadata에서 tool_call 찾음")
                        break
                    pending_query = msg.metadata.get("pending_query")
                    if pending_query and not tool_call_to_execute:
                        break
            
            # 2. tool_call이 없으면 이전 메시지에서 찾기
            if not tool_call_to_execute:
                for msg in reversed(messages):
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            if tool_call.get('name') == 'sql_db_query':
                                tool_call_to_execute = tool_call
                                if self.enable_logging:
                                    logger.info("✅ [QUERY APPROVAL] 이전 메시지에서 tool_call 찾음")
                                break
                        if tool_call_to_execute:
                            break
            
            # 3. tool_call이 없고 pending_query가 있으면 새로 생성
            if not tool_call_to_execute and pending_query:
                tool_call_to_execute = {
                    "name": "sql_db_query",
                    "args": {"query": pending_query},
                    "id": f"query_approval_{id(pending_query)}"
                }
                if self.enable_logging:
                    logger.info("✅ [QUERY APPROVAL] pending_query로 tool_call 생성")
            
            if tool_call_to_execute:
                # tool_call을 포함한 메시지 생성 (run_query에서 실행됨)
                execution_message = AIMessage(
                    content="",
                    tool_calls=[tool_call_to_execute],
                    metadata={"query_approved": True},
                    id=messages[-1].id if messages else None
                )
                if self.enable_logging:
                    logger.info(f"✅ [QUERY APPROVAL] 실행 메시지 생성: {tool_call_to_execute.get('args', {}).get('query', '')[:50]}...")
                return {"messages": [execution_message]}
            else:
                # tool_call을 찾을 수 없는 경우 에러
                if self.enable_logging:
                    logger.error("❌ [QUERY APPROVAL] tool_call을 찾을 수 없습니다.")
                error_response = AIMessage(
                    content="쿼리를 찾을 수 없습니다. 다시 시도해주세요.",
                    id=messages[-1].id if messages else None
                )
                return {"messages": [error_response]}
        
        # 거부된 경우: 수정 요청 또는 종료
        elif is_rejected:
            if self.enable_logging:
                logger.info("❌ [QUERY REJECTED] 사용자가 쿼리 거부")
            
            rejection_response = AIMessage(
                content="쿼리가 거부되었습니다. 다른 방식으로 질문해주시거나, 수정이 필요한 부분을 알려주시면 다시 쿼리를 생성하겠습니다.",
                metadata={"query_rejected": True},
                id=messages[-1].id if messages else None
            )
            return {"messages": [rejection_response]}
        
        # 명확하지 않은 응답: 다시 확인 요청
        else:
            if self.enable_logging:
                logger.warning("⚠️  [UNCLEAR RESPONSE] 사용자 응답이 명확하지 않음")
            
            clarification_response = AIMessage(
                content="응답을 명확히 이해하지 못했습니다. '승인' 또는 '거부'로 답변해주세요.",
                metadata={"needs_user_response": True, "workflow_paused": True},
                id=messages[-1].id if messages else None
            )
            return {"messages": [clarification_response]}
    
    def format_query_results(self, state: MessagesState):
        """Format SQL query results into natural Korean language."""
        # 쿼리 결과 찾기
        query_results = None
        user_question = None
        
        for msg in reversed(state["messages"]):
            if not user_question and isinstance(msg, HumanMessage):
                user_question = msg.content
            if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                query_results = msg.content
                break
            elif hasattr(msg, 'content') and msg.content:
                content = str(msg.content)
                if (content.strip().startswith('[') and '),' in content) or \
                   (content.strip().startswith('(') and '),' in content):
                    if 'table_info' not in content.lower() and 'pragma' not in content.lower():
                        query_results = content
                        break
        
        if not query_results:
            korean_prompt = get_korean_prompt()
            response = self.model.invoke([korean_prompt] + state["messages"])
            return {"messages": [response]}
        
        # 원본 SQL 쿼리 찾기
        original_sql_query = None
        for msg in reversed(state["messages"]):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and tc.get('name') == 'sql_db_query':
                        original_sql_query = tc.get('args', {}).get('query', '')
                        break
                    elif hasattr(tc, 'name') and tc.name == 'sql_db_query':
                        if hasattr(tc, 'args') and isinstance(tc.args, dict):
                            original_sql_query = tc.args.get('query', '')
                            break
            if original_sql_query:
                break
        
        # 쿼리 결과 개수 및 복잡도 분석하여 동적으로 토큰 수 계산
        result_count = 1
        result_complexity = 1.0  # 복잡도 계수 (1.0 = 기본, 2.0 = 매우 복잡)
        
        if query_results:
            # 튜플 형태의 결과 개수 추정
            if isinstance(query_results, str):
                # '),' 패턴으로 행 개수 추정
                result_count = max(1, query_results.count('),') + (1 if query_results.strip().endswith(')') else 0))
                # 결과 데이터의 실제 길이로 복잡도 추정
                avg_row_length = len(query_results) / max(result_count, 1)
                # 평균 행 길이가 200자 이상이면 복잡한 항목 (주문 목록 등)
                if avg_row_length > 200:
                    result_complexity = 2.0  # 복잡한 항목 (상품명, 단가, 수량 등 많은 정보)
                elif avg_row_length > 100:
                    result_complexity = 1.5  # 중간 복잡도
            elif isinstance(query_results, (list, tuple)):
                result_count = len(query_results)
                # 리스트의 경우 첫 번째 항목 길이로 복잡도 추정
                if result_count > 0:
                    first_item_str = str(query_results[0])
                    if len(first_item_str) > 200:
                        result_complexity = 2.0
                    elif len(first_item_str) > 100:
                        result_complexity = 1.5
        
        # SQL 쿼리 분석으로 복잡도 추가 판단
        if original_sql_query:
            query_upper = original_sql_query.upper()
            # JOIN이 많거나 컬럼이 많으면 복잡한 항목
            join_count = query_upper.count('JOIN')
            select_columns = query_upper.count('SELECT') - query_upper.count('SELECT COUNT')
            if join_count >= 2 or select_columns > 5:
                result_complexity = max(result_complexity, 1.8)  # 복잡한 쿼리
        
        # 결과 개수와 복잡도를 고려한 토큰 수 계산
        # 기본 항목당 토큰: 100토큰
        # 복잡한 항목: 100 * 복잡도 계수 = 200토큰 (주문 목록 등)
        tokens_per_item = 100 * result_complexity
        base_tokens = result_count * tokens_per_item
        overhead_tokens = 1000  # 시스템 메시지, 요약 등 오버헤드
        
        # 최소 2000 토큰, 최대 LLM_MAX_TOKENS
        estimated_tokens = min(
            int(base_tokens + overhead_tokens),
            self.agent.max_query_results * 200  # 최대 결과 수 * 최대 항목당 토큰
        )
        # 최소값과 최대값 사이로 제한
        estimated_tokens = max(2000, min(estimated_tokens, LLM_MAX_TOKENS))
        
        dynamic_max_tokens = estimated_tokens
        
        # 동적 토큰 수로 모델 설정 (임시로 max_tokens 조정)
        original_max_tokens = None
        if hasattr(self.model, 'max_tokens'):
            original_max_tokens = self.model.max_tokens
            self.model.max_tokens = dynamic_max_tokens
        
        # 쿼리 결과를 자연어로 포맷팅
        format_instruction = {
            "role": "system",
            "content": get_format_results_prompt()
        }
        
        messages_to_send = [format_instruction]
        if user_question:
            messages_to_send.append({"role": "user", "content": user_question})
        
        context_parts = []
        if original_sql_query:
            context_parts.append(f"실행된 SQL 쿼리:\n{original_sql_query}\n")
        context_parts.append(f"쿼리 결과:\n{query_results}")
        
        messages_to_send.append({"role": "assistant", "content": "\n".join(context_parts)})
        
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("📝 [RESULT FORMATTING] 쿼리 결과를 자연어로 포맷팅 중...")
            logger.info(f"추정된 결과 개수: {result_count}건")
            logger.info(f"복잡도 계수: {result_complexity:.1f}x")
            logger.info(f"항목당 예상 토큰: {tokens_per_item:.0f} 토큰")
            logger.info(f"동적 토큰 수: {dynamic_max_tokens} 토큰 (최대: {LLM_MAX_TOKENS})")
            logger.info(f"원본 결과: {str(query_results)[:200]}...")
            logger.info("=" * 80)
        
        try:
            response = self.model.invoke(messages_to_send)
        finally:
            # 원래 max_tokens 복원
            if original_max_tokens is not None:
                self.model.max_tokens = original_max_tokens
        
        if self.enable_logging:
            logger.info(f"✅ [FORMATTED RESPONSE] 포맷팅 완료: {str(response.content)[:200]}...")
        
        return {"messages": [response]}
    
    def _run_query_with_logging(self, state: MessagesState):
        """Run query with detailed logging for enterprise monitoring."""
        tool_node = ToolNode([self.run_query_tool])
        
        # 실행 전 쿼리 추출 및 로깅
        if self.enable_logging:
            messages = state["messages"]
            for msg in reversed(messages):
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        if tool_call.get('name') == 'sql_db_query':
                            query_to_execute = tool_call.get('args', {}).get('query', '')
                            if query_to_execute:
                                logger.info("=" * 80)
                                logger.info("🚀 [QUERY EXECUTION] SQL 쿼리 실행 시작")
                                logger.info(f"SQL: {query_to_execute}")
                                logger.info("=" * 80)
                            break
                    break
        
        # 쿼리 실행
        result = tool_node.invoke(state)
        
        # 실행 후 결과 로깅
        if self.enable_logging:
            if result and 'messages' in result:
                last_msg = result['messages'][-1]
                if hasattr(last_msg, 'content'):
                    result_preview = str(last_msg.content)[:500]
                    logger.info("=" * 80)
                    logger.info("✅ [QUERY RESULT] 쿼리 실행 완료")
                    logger.info(f"Result Preview: {result_preview}...")
                    logger.info("=" * 80)
        
        return result
    
    def should_continue_sql(self, state: MessagesState) -> Literal[END, "check_query"]:
        """Determine next step in SQL workflow - following Custom SQL Agent pattern."""
        messages = state["messages"]
        last_message = messages[-1]
        
        # 무한 루프 방지: 최근 메시지만 확인
        recent_messages = messages[-20:]
        sql_queries_in_recent = []
        for msg in recent_messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and tc.get('name') == 'sql_db_query':
                        sql_queries_in_recent.append(tc.get('args', {}).get('query', ''))
        
        # 같은 쿼리가 3번 이상 반복되면 무한 루프로 판단
        if len(sql_queries_in_recent) >= 3:
            unique_queries = set(sql_queries_in_recent[-3:])
            if len(unique_queries) == 1:
                logger.warning("Same query repeated multiple times, stopping to prevent infinite loop")
                return END
        
        # 에러 메시지가 있으면 중단
        for msg in reversed(messages[-5:]):
            if hasattr(msg, 'content') and msg.content:
                content = str(msg.content).lower()
                if 'error' in content or 'syntax error' in content or 'operationalerror' in content:
                    logger.warning("Error detected in messages, stopping SQL workflow")
                    return END
        
        if not last_message.tool_calls:
            return END
        else:
            return "check_query"

