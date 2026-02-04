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
        
        # 분할된 질문이 있는지 확인
        split_questions = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                if "split_questions" in msg.metadata:
                    split_questions = msg.metadata["split_questions"]
                    break
        
        # 분할된 질문이 있으면 첫 번째 질문 사용
        if split_questions and len(split_questions) > 0:
            question = split_questions[0]
            logger.info(f"📋 [ROUTING] 분할된 질문 중 첫 번째 질문 사용: {question}")
        else:
            # 일반적인 경우: 사용자 질문 추출
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
        
        # 쿼리 승인/거부 응답인지 먼저 확인 (HITL)
        last_human_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_msg = msg
                break
        
        if last_human_msg:
            user_response = last_human_msg.content.lower().strip()
            approval_keywords = ["승인", "실행", "예", "ok", "yes", "y", "확인", "좋아", "좋아요"]
            rejection_keywords = ["거부", "취소", "아니오", "no", "n", "수정", "다시", "재생성"]
            
            # 승인/거부 키워드가 있고, 이전에 승인 요청이 있었는지 확인
            is_approval_response = any(keyword in user_response for keyword in approval_keywords)
            is_rejection_response = any(keyword in user_response for keyword in rejection_keywords)
            
            if is_approval_response or is_rejection_response:
                # 마지막 HumanMessage 바로 이전에 승인 요청이 있어야 함 (새 질문과 구분)
                # 즉, 마지막 메시지가 승인 요청이고, 그 다음이 사용자 응답이어야 함
                if len(messages) >= 2:
                    prev_msg = messages[-2]  # 마지막 HumanMessage 바로 이전 메시지
                    if isinstance(prev_msg, AIMessage) and hasattr(prev_msg, 'metadata') and prev_msg.metadata:
                        if prev_msg.metadata.get("query_approval_pending", False):
                            logger.info("=" * 80)
                            logger.info("🔍 [ROUTING] 쿼리 승인/거부 응답 감지")
                            logger.info(f"사용자 응답: {user_response}")
                            logger.info(f"승인 요청 메시지 발견: {prev_msg.content[:100] if hasattr(prev_msg, 'content') else 'N/A'}...")
                            logger.info("→ process_query_approval로 라우팅")
                            logger.info("=" * 80)
                            return "process_query_approval"
                
                # 이전 메시지 전체에서 승인 요청 찾기 (fallback)
                for msg in reversed(messages[:-1]):  # 마지막 HumanMessage 제외
                    if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                        if msg.metadata.get("query_approval_pending", False):
                            logger.info("=" * 80)
                            logger.info("🔍 [ROUTING] 쿼리 승인/거부 응답 감지 (fallback)")
                            logger.info(f"사용자 응답: {user_response}")
                            logger.info("→ process_query_approval로 라우팅")
                            logger.info("=" * 80)
                            return "process_query_approval"
                
                # 승인 요청이 없는데 승인/거부 키워드가 있으면 새 질문으로 처리
                logger.info(f"ℹ️  [ROUTING] 승인/거부 키워드가 있으나 이전 승인 요청이 없음 - 새 질문으로 처리: {user_response}")
        
        # 사용자 질문 추출
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        # 조회 의도 키워드 체크 (코드 레벨에서 강제)
        query_intent_keywords = ["조회", "보여줘", "알려줘", "보기", "목록", "리스트", "조회해줘", "보여줘", "알려줘", "찾아줘", "검색", "확인"]
        if user_question:
            question_lower = user_question.lower()
            has_query_intent = any(keyword in question_lower for keyword in query_intent_keywords)
            
            # 조회 의도가 있으면 무조건 SQL로 라우팅 (REJECT 무시)
            if has_query_intent:
                logger.info("🔍 [ROUTING OVERRIDE] 조회 의도가 감지되어 SQL 워크플로우로 강제 라우팅")
                return "sql_workflow"
        
        # 라우팅 결정 추출
        selected_workflow = "sql_workflow"  # 기본값
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                decision = msg.content.strip().upper()
                # REJECT 체크 (조회 의도가 없을 때만)
                if "REJECT" in decision:
                    selected_workflow = "reject_workflow"
                    break
                elif "SQL" in decision:
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
            "direct_response": "DIRECT 응답 (직접 답변)",
            "reject_workflow": "REJECT 워크플로우 (보안 거절)"
        }.get(selected_workflow, selected_workflow)
        
        logger.info("=" * 80)
        logger.info("✅ [ROUTING RESULT] 최종 라우팅 결정")
        logger.info(f"질문: {user_question}")
        logger.info(f"선택된 워크플로우: {workflow_name}")
        logger.info(f"워크플로우 코드: {selected_workflow}")
        logger.info("=" * 80)
        
        return selected_workflow

