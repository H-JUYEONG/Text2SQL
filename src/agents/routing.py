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
        
        # 현재 질문만 분석하도록 명시적으로 강조
        routing_instruction = routing_prompt + f"\n\n## CURRENT QUESTION TO ANALYZE:\n{question}\n\nIMPORTANT: Analyze ONLY this question above. Ignore any previous conversation context."
        response = self.model.invoke([{"role": "user", "content": routing_instruction}])
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
        
        # 라우팅 클리어리피케이션 대기 중인지 확인
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                if msg.metadata.get("routing_clarification_pending", False):
                    # 사용자 응답이 아직 없으면 END (대기)
                    last_human_msg = None
                    for h_msg in reversed(messages):
                        if isinstance(h_msg, HumanMessage):
                            last_human_msg = h_msg
                            break
                    
                    # 라우팅 클리어리피케이션 메시지 이후에 사용자 응답이 없으면 대기
                    clarification_idx = messages.index(msg) if msg in messages else -1
                    if last_human_msg:
                        human_idx = messages.index(last_human_msg) if last_human_msg in messages else -1
                        if human_idx <= clarification_idx:
                            # 사용자 응답이 클리어리피케이션 요청 이전이면 대기
                            logger.info("=" * 80)
                            logger.info("⏳ [ROUTING HITL] 사용자 응답 대기 중...")
                            logger.info("=" * 80)
                            return END
                    else:
                        # 사용자 응답이 없으면 대기
                        logger.info("=" * 80)
                        logger.info("⏳ [ROUTING HITL] 사용자 응답 대기 중...")
                        logger.info("=" * 80)
                        return END
        
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
        
        # 라우팅 클리어리피케이션 응답인지 확인 (HITL)
        if last_human_msg:
            user_response = last_human_msg.content.lower().strip()
            # 라우팅 클리어리피케이션 응답 키워드
            sql_keywords = ["sql", "데이터베이스", "데이터", "db", "조회", "통계", "수치"]
            rag_keywords = ["rag", "문서", "프로세스", "방법", "원칙", "개념", "정책", "가이드"]
            
            # 이전에 라우팅 클리어리피케이션 요청이 있었는지 확인
            for msg in reversed(messages[:-1]):  # 마지막 HumanMessage 제외
                if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                    if msg.metadata.get("routing_clarification_pending", False):
                        # 사용자 응답에 SQL 또는 RAG 의도가 있는지 확인
                        has_sql_intent = any(keyword in user_response for keyword in sql_keywords)
                        has_rag_intent = any(keyword in user_response for keyword in rag_keywords)
                        
                        if has_sql_intent:
                            logger.info("=" * 80)
                            logger.info("🔍 [ROUTING] 사용자가 SQL 선택")
                            logger.info(f"사용자 응답: {user_response}")
                            logger.info("→ sql_workflow로 라우팅")
                            logger.info("=" * 80)
                            return "sql_workflow"
                        elif has_rag_intent:
                            logger.info("=" * 80)
                            logger.info("🔍 [ROUTING] 사용자가 RAG 선택")
                            logger.info(f"사용자 응답: {user_response}")
                            logger.info("→ rag_workflow로 라우팅")
                            logger.info("=" * 80)
                            return "rag_workflow"
                        else:
                            # 명확하지 않으면 다시 클리어리피케이션 요청
                            logger.info("=" * 80)
                            logger.info("🔍 [ROUTING] 사용자 응답이 명확하지 않음")
                            logger.info(f"사용자 응답: {user_response}")
                            logger.info("→ request_routing_clarification으로 다시 라우팅")
                            logger.info("=" * 80)
                            return "request_routing_clarification"
        
        # 라우팅 결정 추출 - LLM의 판단을 신뢰
        selected_workflow = "sql_workflow"  # 기본값
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                decision = msg.content.strip().upper()
                # LLM의 라우팅 결정을 그대로 따름
                if "REJECT" in decision:
                    selected_workflow = "reject_workflow"
                    break
                elif "UNCERTAIN" in decision:
                    # 모호한 경우 HITL로 사용자에게 질문
                    selected_workflow = "request_routing_clarification"
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
            "reject_workflow": "REJECT 워크플로우 (보안 거절)",
            "request_routing_clarification": "라우팅 클리어리피케이션 요청 (HITL)"
        }.get(selected_workflow, selected_workflow)
        
        logger.info("=" * 80)
        logger.info("✅ [ROUTING RESULT] 최종 라우팅 결정")
        logger.info(f"질문: {user_question}")
        logger.info(f"선택된 워크플로우: {workflow_name}")
        logger.info(f"워크플로우 코드: {selected_workflow}")
        logger.info("=" * 80)
        
        return selected_workflow
    
    def request_routing_clarification(self, state: MessagesState):
        """Request clarification from user when routing is uncertain (HITL)."""
        messages = state["messages"]
        
        # 사용자 질문 추출
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        # 클리어리피케이션 질문 생성
        clarification_message = AIMessage(
            content=f"""질문의 의도를 정확히 파악하기 어렵습니다. 다음 중 어떤 것을 원하시나요?

1. **데이터베이스 조회 (SQL)**: 특정 데이터, 통계, 수치, 목록 등을 조회하고 싶으시다면
   - 예: "배송 완료된 주문 수는?", "가장 많은 배송을 처리한 기사는?", "최근 주문 목록"

2. **문서 검색 (RAG)**: 프로세스, 방법, 원칙, 개념, 정책 등에 대한 설명을 원하시다면
   - 예: "배송 프로세스는 어떻게 되나요?", "물류 최적화 방법은?", "재고 관리 원칙"

원하시는 유형을 선택해주세요:
- "데이터베이스" 또는 "SQL" 또는 "데이터 조회"
- "문서" 또는 "RAG" 또는 "프로세스/방법" """,
            metadata={
                "routing_clarification_pending": True,
                "needs_user_response": True,
                "workflow_paused": True
            }
        )
        
        logger.info("=" * 80)
        logger.info("❓ [ROUTING HITL] 라우팅 클리어리피케이션 요청")
        logger.info(f"사용자 질문: {user_question}")
        logger.info("=" * 80)
        
        return {"messages": state["messages"] + [clarification_message]}

