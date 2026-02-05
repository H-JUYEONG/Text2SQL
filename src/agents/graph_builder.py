"""
Graph builder for LangGraph workflow.
"""
import sys
sys.dont_write_bytecode = True

import logging
from typing import Literal
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage

from src.agents.prompts import get_korean_prompt

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Graph builder for the logistics agent."""
    
    def __init__(self, agent):
        """Initialize with reference to the main agent."""
        self.agent = agent
        self.sql_nodes = agent.sql_nodes
        self.rag_nodes = agent.rag_nodes
        self.routing = agent.routing
        self.question_agent = agent.question_agent
        self.get_schema_tool = agent.get_schema_tool
        self.retriever_tool = agent.retriever_tool
        self.model = agent.model
        self.enable_logging = agent.enable_logging
    
    def build_graph(self):
        """Build the LangGraph workflow following reference patterns."""
        workflow = StateGraph(MessagesState)
        
        # SQL Workflow Nodes
        workflow.add_node("list_tables", self.sql_nodes.list_tables)
        workflow.add_node("call_get_schema", self.sql_nodes.call_get_schema)
        workflow.add_node("get_schema", ToolNode([self.get_schema_tool]))
        workflow.add_node("generate_query", self.sql_nodes.generate_query)
        workflow.add_node("check_query", self.sql_nodes.check_query)
        workflow.add_node("request_query_approval", self.sql_nodes.request_query_approval)  # HITL: 쿼리 승인 요청
        workflow.add_node("process_query_approval", self.sql_nodes.process_query_approval)  # HITL: 승인/거부 처리
        workflow.add_node("run_query", self.sql_nodes._run_query_with_logging)
        workflow.add_node("format_results", self.sql_nodes.format_query_results)
        
        # RAG Workflow Nodes
        workflow.add_node("generate_query_or_respond", self.rag_nodes.generate_query_or_respond)
        if self.retriever_tool:
            workflow.add_node("retrieve", ToolNode([self.retriever_tool]))
        workflow.add_node("rewrite_question", self.rag_nodes.rewrite_question)
        workflow.add_node("generate_answer", self.rag_nodes.generate_answer)
        
        # Question Agent Nodes
        workflow.add_node("analyze_question", self.question_agent.analyze_question)
        workflow.add_node("clarify_question", self.question_agent.clarify_question)
        workflow.add_node("split_question", self.question_agent.split_question)
        
        # Routing Node
        workflow.add_node("route_initial_query", self.routing.route_initial_query_node)
        workflow.add_node("request_routing_clarification", self.routing.request_routing_clarification)
        
        # Direct Response
        def direct_response(state: MessagesState):
            """Direct response without tools."""
            korean_prompt = get_korean_prompt()
            messages_with_prompt = [korean_prompt] + state["messages"]
            response = self.model.invoke(messages_with_prompt)
            return {"messages": [response]}
        
        workflow.add_node("direct_response", direct_response)
        
        # Out-of-scope Response (domain mismatch)
        def out_of_scope_response(state: MessagesState):
            """Reply with a fixed message when the question is outside the agent scope."""
            from langchain_core.messages import AIMessage
            msg = AIMessage(
                content=(
                    "죄송합니다. 해당 질문은 현재 물류 데이터/물류 운영 문서/물류 DB 조회 범위를 벗어나 "
                    "정보를 제공할 수 없습니다.\n\n"
                    "물류 관련 질문으로 다시 질문해 주세요."
                )
            )
            return {"messages": [msg]}

        workflow.add_node("out_of_scope_response", out_of_scope_response)

        # Reject Response (for security violations)
        def reject_response(state: MessagesState):
            """Reject data modification requests."""
            from langchain_core.messages import AIMessage
            rejection_message = AIMessage(
                content="죄송합니다. 데이터 수정, 삭제, 생성 등의 작업은 보안상의 이유로 허용되지 않습니다. 읽기 전용 조회만 가능합니다."
            )
            return {"messages": [rejection_message]}
        
        workflow.add_node("reject_response", reject_response)
        
        # Edges
        workflow.add_edge(START, "analyze_question")
        
        # Question Agent workflow
        workflow.add_conditional_edges(
            "analyze_question",
            self.question_agent.should_clarify,
            {
                "clarify_question": "clarify_question",
                "split_question": "split_question",
                END: END,
            },
        )
        
        workflow.add_conditional_edges(
            "clarify_question",
            self.question_agent.should_continue_after_clarification,
            {
                "split_question": "split_question",
                END: END,
            },
        )
        
        workflow.add_edge("split_question", "route_initial_query")
        
        # Route to SQL or RAG workflow
        workflow.add_conditional_edges(
            "route_initial_query",
            self.routing.route_initial_query_condition,
            {
                "sql_workflow": "list_tables",
                "rag_workflow": "generate_query_or_respond",
                "direct_response": "direct_response",
                "out_of_scope_workflow": "out_of_scope_response",
                "reject_workflow": "reject_response",
                "process_query_approval": "process_query_approval",  # HITL: 쿼리 승인 응답 처리
                "request_routing_clarification": "request_routing_clarification",  # HITL: 라우팅 클리어리피케이션 요청
            },
        )
        
        # 라우팅 클리어리피케이션 후 다시 라우팅
        workflow.add_conditional_edges(
            "request_routing_clarification",
            self.routing.route_initial_query_condition,
            {
                "sql_workflow": "list_tables",
                "rag_workflow": "generate_query_or_respond",
                "direct_response": "direct_response",
                "out_of_scope_workflow": "out_of_scope_response",
                "reject_workflow": "reject_response",
                "request_routing_clarification": "request_routing_clarification",  # 응답이 명확하지 않으면 다시 요청
                END: END,  # 사용자 응답 대기
            },
        )
        
        # SQL workflow edges
        # list_tables에서 스키마 검증 실패 시 END로 가도록 조건부 엣지 추가
        def check_schema_validation(state: MessagesState) -> Literal[END, "call_get_schema"]:
            """Check if schema validation failed in list_tables."""
            messages = state["messages"]
            # 마지막 메시지가 스키마 검증 오류 메시지인지 확인
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, 'content') and last_msg.content:
                    content = str(last_msg.content)
                    # 스키마 검증 실패 메시지 패턴 확인
                    if "존재하지 않습니다" in content or "테이블은 데이터베이스에 존재하지 않습니다" in content:
                        logger.info("🔍 [SCHEMA VALIDATION] 스키마 검증 실패로 워크플로우 종료")
                        return END
            return "call_get_schema"
        
        workflow.add_conditional_edges(
            "list_tables",
            check_schema_validation,
            {
                END: END,
                "call_get_schema": "call_get_schema",
            },
        )
        workflow.add_edge("call_get_schema", "get_schema")
        workflow.add_edge("get_schema", "generate_query")
        workflow.add_conditional_edges(
            "generate_query",
            self.sql_nodes.should_continue_sql,
            {
                "check_query": "check_query",
                END: END,
            },
        )
        # check_query 후 쿼리 승인 요청 (HITL)
        workflow.add_edge("check_query", "request_query_approval")
        
        # 쿼리 승인 요청 후 사용자 응답 대기 또는 승인 처리
        def should_process_approval(state: MessagesState) -> Literal[END, "process_query_approval"]:
            """쿼리 승인 요청 후 사용자 응답이 있는지 확인"""
            messages = state["messages"]
            last_msg = messages[-1] if messages else None
            
            # 마지막 메시지가 승인 요청인지 확인
            if last_msg and hasattr(last_msg, 'metadata') and last_msg.metadata:
                if last_msg.metadata.get("query_approval_pending", False):
                    # 승인 요청 메시지인 경우, 사용자 응답을 기다림 (END)
                    # 다음 호출 시 사용자 응답이 있으면 process_query_approval로 라우팅됨
                    return END
            
            # 마지막 메시지가 HumanMessage면 사용자 응답이 온 것
            # (승인 요청 후 사용자가 응답한 경우)
            if isinstance(last_msg, HumanMessage):
                # 이전 메시지 중 승인 요청이 있었는지 확인
                for msg in reversed(messages[:-1]):
                    if hasattr(msg, 'metadata') and msg.metadata:
                        if msg.metadata.get("query_approval_pending", False):
                            return "process_query_approval"
            
            return END
        
        workflow.add_conditional_edges(
            "request_query_approval",
            should_process_approval,
            {
                END: END,  # 사용자 응답 대기
                "process_query_approval": "process_query_approval",
            },
        )
        
        # 승인 처리 후 실행 또는 종료
        def should_execute_query(state: MessagesState) -> Literal[END, "run_query", "generate_query"]:
            """쿼리 승인 처리 후 실행 여부 결정"""
            messages = state["messages"]
            last_msg = messages[-1] if messages else None
            
            # 거부 피드백이 있는 경우: 쿼리 재생성
            if isinstance(last_msg, HumanMessage) and "수정 요청:" in last_msg.content:
                logger.info("🔄 [QUERY REGENERATION] 거부 피드백 기반 쿼리 재생성으로 라우팅")
                return "generate_query"
            
            # 마지막 메시지의 메타데이터 확인
            if last_msg and hasattr(last_msg, 'metadata') and last_msg.metadata:
                # 승인된 경우
                if last_msg.metadata.get("query_approved", False):
                    return "run_query"
                # 거부된 경우
                if last_msg.metadata.get("query_rejected", False):
                    return END
                # 명확하지 않은 응답으로 다시 확인 요청
                if last_msg.metadata.get("needs_user_response", False):
                    return END
            
            # tool_call이 있으면 실행 (승인 후 tool_call이 추가된 경우)
            if last_msg and hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
                for tool_call in last_msg.tool_calls:
                    if tool_call.get('name') == 'sql_db_query':
                        return "run_query"
            
            return END
        
        workflow.add_conditional_edges(
            "process_query_approval",
            should_execute_query,
            {
                "run_query": "run_query",
                "generate_query": "generate_query",  # 거부 피드백 시 쿼리 재생성
                END: END,  # 거부 또는 대기
                "run_query": "run_query",
            },
        )
        
        # run_query 후 조건부로 format_results, generate_query 또는 END
        def should_retry_after_query(state: MessagesState) -> Literal[END, "format_results", "generate_query"]:
            """쿼리 실행 후 재시도 여부 결정 - 무한 루프 방지"""
            messages = state["messages"]
            
            # 최근 메시지에서 에러 확인
            for msg in reversed(messages[-5:]):
                if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                    if hasattr(msg, 'content') and msg.content:
                        content = str(msg.content).lower()
                        if 'error' in content or 'syntax error' in content or 'operationalerror' in content:
                            logger.warning("Query execution error detected, ending workflow")
                            return END
                        is_schema_info = False
                        if 'table_info' in content or 'pragma' in content:
                            is_schema_info = True
                        elif 'integer' in content and 'varchar' in content:
                            if not (content.strip().startswith('[') or content.strip().startswith('(') or '),' in content):
                                is_schema_info = True
                        
                        if is_schema_info:
                            logger.warning("Schema inspection query detected in results, ending workflow")
                            return END
                        break
            
            # 무한 루프 방지
            recent_messages = messages[-30:]
            query_results_count = 0
            for msg in recent_messages:
                if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                    query_results_count += 1
            
            if query_results_count > 5:
                logger.warning("Too many query results in recent workflow, ending to prevent infinite loop")
                return END
            
            # 쿼리 결과가 있는지 확인
            has_query_results = False
            for msg in reversed(messages[-5:]):
                if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                    has_query_results = True
                    break
                elif hasattr(msg, 'content') and msg.content:
                    content = str(msg.content)
                    if (content.strip().startswith('[') and '),' in content) or \
                       (content.strip().startswith('(') and '),' in content):
                        if 'table_info' not in content.lower() and 'pragma' not in content.lower():
                            has_query_results = True
                            break
            
            if has_query_results:
                return "format_results"
            
            last_message = messages[-1]
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                return "generate_query"
            return END
        
        workflow.add_conditional_edges(
            "run_query",
            should_retry_after_query,
            {
                "format_results": "format_results",
                "generate_query": "generate_query",
                END: END,
            },
        )
        
        workflow.add_edge("format_results", END)
        
        # RAG workflow edges
        if self.retriever_tool:
            workflow.add_conditional_edges(
                "generate_query_or_respond",
                tools_condition,
                {
                    "tools": "retrieve",
                    END: END,
                },
            )
            
            workflow.add_conditional_edges(
                "retrieve",
                self.rag_nodes.grade_documents,
            )
            workflow.add_edge("rewrite_question", "generate_query_or_respond")
        
        workflow.add_edge("generate_answer", END)
        workflow.add_edge("direct_response", END)
        workflow.add_edge("reject_response", END)
        
        # Compile with checkpointer for thread-scoped memory
        return workflow.compile(checkpointer=self.agent.checkpointer)

