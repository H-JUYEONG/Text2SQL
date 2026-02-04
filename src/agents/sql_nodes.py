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
from src.agents.security import validate_query_security

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
        self.enable_logging = agent.enable_logging
    
    def list_tables(self, state: MessagesState):
        """List all available tables - predetermined tool call pattern."""
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
            logger.info(f"원본 결과: {str(query_results)[:200]}...")
            logger.info("=" * 80)
        
        response = self.model.invoke(messages_to_send)
        
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

