"""
Question Agent: 모호성 분석, 해소, 질문 분할
"""
import sys
sys.dont_write_bytecode = True

import logging
from typing import Literal, List, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import MessagesState, END

logger = logging.getLogger(__name__)


class QuestionAgent:
    """Question Agent for ambiguity analysis, clarification, and question splitting."""
    
    def __init__(self, agent):
        """Initialize with reference to the main agent."""
        self.agent = agent
        self.model = agent.model
        self.enable_logging = agent.enable_logging
    
    def analyze_question(self, state: MessagesState):
        """Analyze question for ambiguity and determine if clarification is needed."""
        messages = state["messages"]
        user_question = ""
        
        # 사용자 질문 추출
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        if not user_question:
            if self.enable_logging:
                logger.warning("⚠️  [ANALYZE QUESTION] 사용자 질문을 찾을 수 없습니다.")
            return {"messages": messages}
        
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("🔍 [ANALYZE QUESTION] 모호성 분석 시작")
            logger.info(f"질문: {user_question}")
            logger.info("=" * 80)
        
        # 모호성 분석 프롬프트
        ambiguity_analysis_prompt = f"""당신은 사용자의 질문을 분석하여 모호성을 판단하는 전문가입니다.

사용자 질문: "{user_question}"

다음 두 가지 유형의 모호성을 구분하세요:

1. 자연스러운 모호성: 업계 표준이나 보편적 상식으로 가장 가능성 높은 해석이 존재하는 경우
   - 예: "이번 달 매출액" → 일반적으로 SUM(총매출액)을 의미
   - 예: "주문 테이블 조회" → 명확한 테이블명
   - 이 경우 자동으로 처리 가능

2. 치명적인 모호성: 여러 갈래로 해석될 수 있어 임의 판단 시 사용자 의도와 전혀 다른 결과를 제공할 위험
   - 예: "성과가 좋은 고객/기사/제품" → 성과의 기준이 불명확 (매출액? 건수? 속도? 등)
   - 예: "인기 있는 제품" → 인기의 기준이 불명확 (판매량? 조회수? 평점? 등)
   - 예: "잘 팔리는 상품" → 판매량 기준? 매출 기준? 기간은?
   - 이 경우 반드시 사용자에게 질문하여 명확히 해야 함

중요 규칙:
- "성과", "인기", "좋은", "나쁜", "많은", "적은" 같은 주관적 표현이 있으면 무조건 "NEEDS_CLARIFICATION"
- 구체적인 기준(매출액, 건수, 기간 등)이 명시되지 않으면 "NEEDS_CLARIFICATION"
- 데이터베이스에서 직접 조회 가능한 명확한 정보만 "CLEAR"

응답 형식:
- 모호성이 없거나 자연스러운 모호성만 있는 경우: "CLEAR" 또는 "AUTO_RESOLVE"
- 치명적인 모호성이 있는 경우: 반드시 "NEEDS_CLARIFICATION"으로 시작하고 어떤 부분이 모호한지 설명

응답:"""
        
        response = self.model.invoke([{"role": "user", "content": ambiguity_analysis_prompt}])
        decision = response.content.strip().upper()
        
        # 코드 레벨에서 모호성 키워드 체크 (이중 안전장치)
        ambiguous_keywords = ["성과", "인기", "좋은", "나쁜", "많은", "적은", "잘", "나쁘게", "인기있는", "인기 있는"]
        question_lower = user_question.lower()
        has_ambiguous_keyword = any(keyword in question_lower for keyword in ambiguous_keywords)
        
        # 모호성 키워드가 있고, 구체적인 기준이 없으면 강제로 명확화 필요
        if has_ambiguous_keyword:
            # 구체적인 기준 키워드 체크
            specific_criteria = ["매출", "건수", "개수", "수량", "금액", "기간", "속도", "시간", "기준", "순위"]
            has_specific_criteria = any(criteria in question_lower for criteria in specific_criteria)
            
            if not has_specific_criteria:
                # 구체적인 기준이 없으면 강제로 명확화 필요
                decision = "NEEDS_CLARIFICATION"
                response.content = f"NEEDS_CLARIFICATION\n질문에 '성과', '인기' 등의 주관적 표현이 있지만 구체적인 기준이 명시되지 않았습니다. 사용자에게 명확한 기준을 물어봐야 합니다."
        
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("🔍 [QUESTION AGENT] 모호성 분석 결과")
            logger.info(f"질문: {user_question}")
            logger.info(f"LLM 결정: {decision}")
            logger.info(f"모호성 키워드 감지: {has_ambiguous_keyword}")
            logger.info(f"최종 결정: {decision}")
            logger.info("=" * 80)
        
        # 결정을 메시지에 추가
        analysis_message = AIMessage(
            content=f"모호성 분석 결과: {decision}\n{response.content}"
        )
        
        return {"messages": messages + [analysis_message]}
    
    def clarify_question(self, state: MessagesState):
        """Clarify ambiguous question by asking user (HITL)."""
        messages = state["messages"]
        
        # 이미 명확화 질문이 있고, 사용자 응답이 있는지 확인
        clarification_asked = False
        clarification_msg_index = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                if msg.metadata.get("needs_user_response"):
                    clarification_asked = True
                    clarification_msg_index = i
                    break
        
        # 명확화 질문이 있고, 사용자 응답이 있으면 원래 질문과 결합하여 다음 단계로
        if clarification_asked and clarification_msg_index >= 0:
            # 가장 최근 HumanMessage 찾기 (새 질문일 가능성이 높음)
            last_human_message = None
            last_human_index = -1
            for i in range(len(messages) - 1, -1, -1):
                if isinstance(messages[i], HumanMessage):
                    last_human_message = messages[i]
                    last_human_index = i
                    break
            
            if not last_human_message or last_human_index <= clarification_msg_index:
                # 명확화 질문 이후에 HumanMessage가 없으면 명확화 질문 생성
                pass
            else:
                # 가장 최근 HumanMessage가 명확화 질문 이후에 있음
                clarification_response = last_human_message.content
                
                # 명확화 질문 이후에 쿼리 실행이나 결과가 있는지 확인
                # (이전 질문이 이미 완료되었는지 확인)
                has_completed_workflow = False
                for i in range(clarification_msg_index + 1, last_human_index):
                    msg = messages[i]
                    # 쿼리 결과, 포맷팅된 응답, 또는 승인 요청이 있으면 이전 워크플로우가 완료된 것
                    if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                        has_completed_workflow = True
                        break
                    elif isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                        # 쿼리 승인 요청이나 포맷팅된 결과가 있으면 완료된 것
                        if msg.metadata.get("query_approval_pending") or \
                           (hasattr(msg, 'content') and msg.content and len(str(msg.content)) > 100 and ("총" in str(msg.content) or "건" in str(msg.content))):
                            has_completed_workflow = True
                            break
                
                # 이전 워크플로우가 완료되었거나, 가장 최근 메시지가 명확화 질문과 멀리 떨어져 있으면 새 질문으로 처리
                if has_completed_workflow or (last_human_index - clarification_msg_index > 3):
                    # 새 질문인지 추가 확인: 명확화 응답이 아닌 새로운 질문인 경우
                    is_new_question = len(clarification_response.strip()) > 15 or \
                                     any(keyword in clarification_response for keyword in ["누구", "어떤", "몇", "언제", "어디", "왜", "어떻게", "가장", "최고", "최대", "기사", "처리한", "누구인가"])
                    
                    if is_new_question:
                        if self.enable_logging:
                            logger.info("=" * 80)
                            logger.info("🆕 [NEW QUESTION DETECTED] 이전 워크플로우 완료 후 새 질문 감지")
                            logger.info(f"새 질문: {clarification_response}")
                            logger.info("이전 질문 컨텍스트 무시하고 새 질문만 사용")
                            logger.info("=" * 80)
                        # 새 질문만 HumanMessage로 추가
                        new_question_message = HumanMessage(content=clarification_response)
                        return {"messages": messages + [new_question_message]}
                
                # 명확화 질문 이후의 첫 번째 HumanMessage 찾기 (명확화 응답일 가능성)
                later_human_messages = [msg for i, msg in enumerate(messages) if isinstance(msg, HumanMessage) and i > clarification_msg_index]
                
                if later_human_messages:
                    # 첫 번째 HumanMessage가 명확화 응답인지 확인
                    first_response = later_human_messages[0].content
                    
                    # 명확화 응답인지 새 질문인지 구분
                    # 명확화 응답은 보통 짧고 간단하며, 새 질문은 더 구체적임
                    is_clarification_response = len(first_response.strip()) <= 30 and \
                                               not any(keyword in first_response for keyword in ["누구", "어떤", "몇", "언제", "어디", "왜", "어떻게", "가장", "최고", "최대", "기사", "처리한", "누구인가"])
                    
                    # 가장 최근 메시지가 첫 번째 응답과 다르면 새 질문
                    if last_human_message.content != first_response:
                        # 가장 최근 메시지가 새 질문
                        if self.enable_logging:
                            logger.info("=" * 80)
                            logger.info("🆕 [NEW QUESTION DETECTED] 가장 최근 메시지가 새 질문으로 감지")
                            logger.info(f"명확화 응답: {first_response}")
                            logger.info(f"새 질문: {last_human_message.content}")
                            logger.info("=" * 80)
                        new_question_message = HumanMessage(content=last_human_message.content)
                        return {"messages": messages + [new_question_message]}
                    
                    # 명확화 응답으로 처리
                    clarification_response = first_response
                    
                    # 사용자 응답이 있음 - 원래 질문과 결합하여 완전한 질문 생성
                    original_question = ""
                    for msg in messages[:clarification_msg_index]:
                        if isinstance(msg, HumanMessage):
                            original_question = msg.content
                            break
                    
                    # 사용자 응답이 충분한지 간단히 판단 (너무 짧거나 불명확한 경우만 재질문)
                    # "배송 완료 건수 기준으로", "수도권으로" 같은 응답은 충분함
                    if len(clarification_response.strip()) < 3:
                        # 응답이 너무 짧으면 재질문
                        if self.enable_logging:
                            logger.info("⚠️  [INSUFFICIENT RESPONSE] 사용자 응답이 너무 짧음 - 재질문 필요")
                    else:
                        # 원래 질문과 명확화 응답을 결합
                        combined_question = f"{original_question} ({clarification_response})"
                        
                        if self.enable_logging:
                            logger.info("=" * 80)
                            logger.info("✅ [CLARIFICATION COMPLETE] 명확화 응답 받음")
                            logger.info(f"원래 질문: {original_question}")
                            logger.info(f"명확화 응답: {clarification_response}")
                            logger.info(f"결합된 질문: {combined_question}")
                            logger.info("=" * 80)
                        
                        # 결합된 질문을 새로운 HumanMessage로 추가하여 다음 단계로 진행
                        combined_message = HumanMessage(content=combined_question)
                        return {"messages": messages + [combined_message]}
        
        # 명확화 질문이 아직 없거나 사용자 응답이 없는 경우 - 명확화 질문 생성
        # 이미 명확화 질문이 생성되었는지 확인 (중복 방지)
        existing_clarification = False
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                if msg.metadata.get("needs_user_response"):
                    existing_clarification = True
                    break
        
        if existing_clarification:
            # 이미 명확화 질문이 있으면 그대로 반환 (재생성 방지)
            if self.enable_logging:
                logger.info("⏸️  [CLARIFICATION EXISTS] 이미 명확화 질문이 있음 - 사용자 응답 대기")
            return {"messages": messages}
        
        # 모호성 분석 결과 찾기
        ambiguity_found = False
        ambiguous_parts = []
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and "모호성 분석 결과" in str(msg.content):
                content = str(msg.content)
                if "NEEDS_CLARIFICATION" in content.upper():
                    ambiguity_found = True
                    # 모호한 부분 추출
                    ambiguous_parts.append(content)
                break
        
        if not ambiguity_found:
            # 모호성이 없으면 다음 단계로
            return {"messages": messages}
        
        # 사용자에게 명확화 질문 생성 (한 번만)
        clarification_prompt = f"""사용자의 질문에서 모호한 부분을 발견했습니다. 사용자에게 명확화 질문을 생성하세요.

모호성 분석 결과:
{ambiguous_parts[-1] if ambiguous_parts else ""}

사용자에게 친절하고 구체적인 질문을 한국어로 생성하세요. 예를 들어:
"성과가 어떤 기준으로 정의되는지 명확하지 않습니다. 매출액, 구매 빈도 등 구체적인 성과 지표를 명시해주십시오."

중요: 한 번만 질문하고, 사용자가 답변하면 그 답변을 받아들여야 합니다.

명확화 질문:"""
        
        response = self.model.invoke([{"role": "user", "content": clarification_prompt}])
        clarification_question = response.content.strip()
        
        # 명확화 질문을 사용자에게 반환하고 워크플로우 중단
        clarification_message = AIMessage(
            content=clarification_question,
            metadata={"needs_user_response": True, "workflow_paused": True}
        )
        
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("⏸️  [HITL] 사용자 응답 대기 중")
            logger.info(f"명확화 질문: {clarification_question}")
            logger.info("=" * 80)
        
        return {"messages": messages + [clarification_message]}
    
    def split_question(self, state: MessagesState):
        """Split complex question into multiple sub-questions."""
        messages = state["messages"]
        user_question = ""
        original_question = ""
        
        # 가장 최근 HumanMessage 찾기
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        
        if not last_human_message:
            return {"messages": messages}
        
        # 가장 최근 HumanMessage가 새 질문인지 확인
        # 이전 명확화 질문 이후에 쿼리 실행이나 결과가 있으면 새 질문
        user_question = last_human_message.content
        
        # 명확화 질문 찾기
        clarification_msg_index = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                if msg.metadata.get("needs_user_response"):
                    clarification_msg_index = i
                    break
        
        # 명확화 질문 이후에 완료된 워크플로우가 있는지 확인
        is_new_question = False
        if clarification_msg_index >= 0:
            last_human_index = messages.index(last_human_message) if last_human_message in messages else -1
            if last_human_index > clarification_msg_index:
                # 명확화 질문과 최근 HumanMessage 사이에 완료된 워크플로우가 있는지 확인
                for i in range(clarification_msg_index + 1, last_human_index):
                    msg = messages[i]
                    if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                        is_new_question = True
                        break
                    elif isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                        if msg.metadata.get("query_approval_pending") or \
                           (hasattr(msg, 'content') and msg.content and len(str(msg.content)) > 100 and ("총" in str(msg.content) or "건" in str(msg.content))):
                            is_new_question = True
                            break
        
        # 새 질문이면 그대로 사용
        if is_new_question:
            if self.enable_logging:
                logger.info(f"🆕 [SPLIT QUESTION] 새 질문으로 처리: {user_question}")
            original_question = user_question
        else:
            # 명확화 응답이 있는 경우: 원래 질문 + 명확화 응답 결합
            human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
            if len(human_messages) >= 2:
                original_question = human_messages[0].content
                clarification_response = human_messages[-1].content
                # 원래 질문과 명확화 응답을 결합
                user_question = f"{original_question} ({clarification_response})"
            elif len(human_messages) == 1:
                # 명확화 응답이 없는 경우: 원래 질문만 사용
                user_question = human_messages[0].content
                original_question = user_question
        
        if not user_question:
            return {"messages": messages}
        
        # 질문 분할 필요성 판단
        split_analysis_prompt = f"""당신은 사용자의 질문을 분석하여 복합적인 분석이 필요한지 판단하는 전문가입니다.

사용자 질문: "{user_question}"

다음과 같은 경우 질문 분할이 필요합니다:
- "분석해줘", "비교해줘", "요약해줘" 같은 포괄적 요청
- 여러 관점에서 접근해야 하는 질문 (예: 시간별, 제품별, 지역별)
- 여러 지표를 동시에 요청하는 질문

응답 형식:
- 분할이 필요 없는 경우: "NO_SPLIT"
- 분할이 필요한 경우: "SPLIT"과 함께 분할된 질문들을 JSON 배열로 제공
  예: ["시간별 매출 추이 조회", "제품별 매출 비교", "지역별 매출 분포"]

응답:"""
        
        response = self.model.invoke([{"role": "user", "content": split_analysis_prompt}])
        decision = response.content.strip()
        
        if "NO_SPLIT" in decision.upper():
            # 분할 불필요
            return {"messages": messages}
        
        # 질문 분할 실행
        split_prompt = f"""사용자의 포괄적인 질문을 여러 개의 구체적인 분석 질의로 분할하세요.

원본 질문: "{user_question}"

분할 규칙:
1. 각 분할된 질문은 독립적으로 실행 가능해야 함
2. 원본 질문의 핵심 맥락과 조건을 모두 포함
3. 데이터 분석가의 사고 방식을 모방하여 체계적으로 분해
4. 비즈니스 중요도에 따라 우선순위 정렬

분할된 질문들을 JSON 배열로 제공하세요:
["질문1", "질문2", "질문3"]

분할된 질문들:"""
        
        split_response = self.model.invoke([{"role": "user", "content": split_prompt}])
        
        # JSON 파싱 시도
        import json
        import re
        
        try:
            # JSON 배열 추출
            json_match = re.search(r'\[.*?\]', split_response.content, re.DOTALL)
            if json_match:
                split_questions = json.loads(json_match.group())
            else:
                # JSON이 없으면 줄바꿈으로 분리
                lines = [line.strip() for line in split_response.content.split('\n') if line.strip()]
                split_questions = [line for line in lines if not line.startswith('#')]
        except:
            # 파싱 실패 시 원본 질문 그대로
            split_questions = [user_question]
        
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("✂️  [QUESTION SPLIT] 질문 분할 결과")
            logger.info(f"원본 질문: {user_question}")
            logger.info(f"분할된 질문 수: {len(split_questions)}")
            for i, q in enumerate(split_questions, 1):
                logger.info(f"  {i}. {q}")
            logger.info("=" * 80)
        
        # 분할된 질문들을 메타데이터에 저장
        split_message = AIMessage(
            content=f"질문이 {len(split_questions)}개로 분할되었습니다.",
            metadata={"split_questions": split_questions, "original_question": user_question}
        )
        
        return {"messages": messages + [split_message]}
    
    def should_clarify(self, state: MessagesState) -> Literal[END, "clarify_question", "split_question"]:
        """Determine if clarification or splitting is needed."""
        messages = state["messages"]
        
        # 쿼리 승인/거부 응답인지 먼저 확인 (HITL - 최우선)
        last_human_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_msg = msg
                break
        
        if last_human_msg:
            user_response = last_human_msg.content.lower().strip()
            approval_keywords = ["승인", "실행", "예", "ok", "yes", "y", "확인", "좋아", "좋아요"]
            rejection_keywords = ["거부", "취소", "아니오", "no", "n", "수정", "다시", "재생성"]
            
            is_approval_response = any(keyword in user_response for keyword in approval_keywords)
            is_rejection_response = any(keyword in user_response for keyword in rejection_keywords)
            
            if is_approval_response or is_rejection_response:
                # 이전 메시지 중 승인 요청이 있었는지 확인
                for msg in reversed(messages):
                    if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                        if msg.metadata.get("query_approval_pending", False):
                            # 승인/거부 응답이면 split_question으로 보내서 route_initial_query로 가도록
                            if self.enable_logging:
                                logger.info("🔍 [SHOULD_CLARIFY] 쿼리 승인/거부 응답 감지 → split_question으로 라우팅")
                            return "split_question"
        
        # 마지막 메시지 확인 (사용자 응답 대기 중인지)
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, 'metadata') and last_msg.metadata:
                if last_msg.metadata.get("needs_user_response"):
                    # 사용자 응답 대기 중
                    if self.enable_logging:
                        logger.info("⏸️  [WAITING] 사용자 응답 대기 중")
                    return END
        
        # 사용자 질문 추출 (코드 레벨 키워드 체크 - 최우선)
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content
                break
        
        # 코드 레벨에서 모호성 키워드 강제 체크 (최우선 - 이중 안전장치)
        if user_question:
            ambiguous_keywords = ["성과", "인기", "좋은", "나쁜", "많은", "적은", "잘", "나쁘게", "인기있는", "인기 있는"]
            question_lower = user_question.lower()
            has_ambiguous_keyword = any(keyword in question_lower for keyword in ambiguous_keywords)
            
            if has_ambiguous_keyword:
                # 구체적인 기준 키워드 체크
                specific_criteria = ["매출", "건수", "개수", "수량", "금액", "기간", "속도", "시간", "기준", "순위"]
                has_specific_criteria = any(criteria in question_lower for criteria in specific_criteria)
                
                if not has_specific_criteria:
                    # 구체적인 기준이 없으면 강제로 명확화 필요
                    if self.enable_logging:
                        logger.info("=" * 80)
                        logger.info("🔒 [FORCE CLARIFICATION] 코드 레벨에서 모호성 키워드 감지")
                        logger.info(f"질문: {user_question}")
                        logger.info("구체적인 기준이 없어 강제로 명확화 필요")
                        logger.info("=" * 80)
                    return "clarify_question"
        
        # 모호성 분석 결과 확인
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and "모호성 분석 결과" in str(msg.content):
                content = str(msg.content).upper()
                if "NEEDS_CLARIFICATION" in content:
                    if self.enable_logging:
                        logger.info("🔍 [CLARIFICATION NEEDED] 모호성 분석 결과: 명확화 필요")
                    return "clarify_question"
                elif "CLEAR" in content or "AUTO_RESOLVE" in content:
                    # 명확하거나 자동 해결 가능하면 분할 검사
                    if self.enable_logging:
                        logger.info("✅ [CLEAR] 모호성 분석 결과: 명확함 - 분할 단계로")
                    return "split_question"
                break
        
        # 명확화 응답이 이미 있는지 확인 (원래 질문 + 명확화 응답)
        # 주의: 명확화 질문(AIMessage with needs_user_response) 이후의 HumanMessage가 있어야 함
        human_messages = [msg for msg in messages if isinstance(msg, HumanMessage)]
        ai_messages_with_hitl = [msg for msg in messages if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata and msg.metadata.get("needs_user_response")]
        
        if len(human_messages) >= 2 and ai_messages_with_hitl:
            # 명확화 질문이 있고, 사용자 응답이 있으면 바로 분할 단계로 (재분석 불필요)
            if self.enable_logging:
                logger.info("✅ [CLARIFICATION RESPONSE] 명확화 응답 확인 - 분할 단계로 진행")
            return "split_question"
        
        # 기본값: 분할 단계로 (명확한 질문으로 간주)
        if self.enable_logging:
            logger.info("➡️  [DEFAULT] 분할 단계로 진행")
        return "split_question"
    
    def should_continue_after_clarification(self, state: MessagesState) -> Literal[END, "split_question"]:
        """Check if user has responded to clarification."""
        messages = state["messages"]
        
        # 명확화 질문이 방금 생성되었는지 확인 (마지막 메시지가 명확화 질문인지)
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, AIMessage) and hasattr(last_msg, 'metadata') and last_msg.metadata:
                if last_msg.metadata.get("needs_user_response"):
                    # 명확화 질문이 방금 생성되었음 - 사용자 응답 대기
                    if self.enable_logging:
                        logger.info("=" * 80)
                        logger.info("⏸️  [HITL PAUSE] 명확화 질문 생성됨 - 사용자 응답 대기")
                        logger.info(f"명확화 질문: {last_msg.content[:100]}...")
                        logger.info("=" * 80)
                    return END
        
        # 명확화 질문이 이미 있고, 사용자 응답이 있는지 확인
        clarification_asked = False
        clarification_msg_index = -1
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'metadata') and msg.metadata:
                if msg.metadata.get("needs_user_response"):
                    clarification_asked = True
                    clarification_msg_index = i
                    break
        
        # 명확화 질문이 있고, 사용자 응답이 있으면 분할 단계로
        if clarification_asked and clarification_msg_index >= 0:
            # 명확화 질문 이후의 HumanMessage가 있는지 확인
            later_human_messages = [msg for i, msg in enumerate(messages) if isinstance(msg, HumanMessage) and i > clarification_msg_index]
            
            if later_human_messages:
                # 사용자 응답이 있음
                if self.enable_logging:
                    logger.info("✅ [CLARIFICATION RESPONSE] 사용자 응답 확인 - 분할 단계로 진행")
                return "split_question"
            else:
                # 아직 응답 대기 중
                if self.enable_logging:
                    logger.info("⏸️  [WAITING] 사용자 응답 대기 중")
                return END
        
        # 명확화 질문이 없으면 분할 단계로
        return "split_question"

