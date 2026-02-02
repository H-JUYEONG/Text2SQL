"""
Routing logic for SQL vs RAG workflow selection.
"""
import sys
sys.dont_write_bytecode = True

import logging
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import MessagesState

from src.agents.prompts import get_routing_prompt

logger = logging.getLogger(__name__)


class Routing:
    """Routing logic for the logistics agent."""
    
    def __init__(self, agent):
        """Initialize with reference to the main agent."""
        self.agent = agent
        self.model = agent.model
    
    def route_initial_query_node(self, state: MessagesState):
        """Route initial query to SQL or RAG workflow - node function."""
        routing_prompt = get_routing_prompt()
        
        messages = state["messages"]
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        
        if not last_human_message:
            question = messages[0].content if messages else ""
        else:
            question = last_human_message.content
        
        # 라우팅 결정 전 로깅
        logger.info("=" * 80)
        logger.info("🔀 [ROUTING] 라우팅 결정 시작")
        logger.info(f"질문: {question}")
        logger.info("=" * 80)
        
        response = self.model.invoke([{"role": "user", "content": routing_prompt + f"\n\nQuestion: {question}"}])
        decision = response.content.strip().upper()
        
        # LLM의 라우팅 결정 로깅
        logger.info("=" * 80)
        logger.info("🤖 [ROUTING DECISION] LLM 라우팅 결정")
        logger.info(f"LLM 응답 (원본): {response.content}")
        logger.info(f"정규화된 결정: {decision}")
        logger.info("=" * 80)
        
        return {"messages": state["messages"] + [AIMessage(content=decision)]}
    
    def route_initial_query_condition(self, state: MessagesState) -> str:
        """Route condition function for conditional edge."""
        messages = state["messages"]
        
        # 사용자 질문 추출
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        # 라우팅 결정 추출
        selected_workflow = "sql_workflow"  # 기본값
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                decision = msg.content.strip().upper()
                if "SQL" in decision:
                    selected_workflow = "sql_workflow"
                    break
                elif "RAG" in decision:
                    selected_workflow = "rag_workflow"
                    break
                else:
                    selected_workflow = "direct_response"
                    break
        
        # 최종 라우팅 결정 로깅
        workflow_name = {
            "sql_workflow": "SQL 워크플로우 (데이터베이스 조회)",
            "rag_workflow": "RAG 워크플로우 (문서 검색)",
            "direct_response": "DIRECT 응답 (직접 답변)"
        }.get(selected_workflow, selected_workflow)
        
        logger.info("=" * 80)
        logger.info("✅ [ROUTING RESULT] 최종 라우팅 결정")
        logger.info(f"질문: {user_question}")
        logger.info(f"선택된 워크플로우: {workflow_name}")
        logger.info(f"워크플로우 코드: {selected_workflow}")
        logger.info("=" * 80)
        
        return selected_workflow

