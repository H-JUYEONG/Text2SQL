"""
RAG Agent Nodes for LangGraph workflow.
"""
import sys
sys.dont_write_bytecode = True

from typing import Literal
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import MessagesState

from src.agents.prompts import GRADE_PROMPT, REWRITE_PROMPT, GENERATE_ANSWER_PROMPT, get_korean_prompt


class RAGNodes:
    """RAG workflow nodes for the logistics agent."""
    
    def __init__(self, agent):
        """Initialize with reference to the main agent."""
        self.agent = agent
        self.model = agent.model
        self.retriever_tool = agent.retriever_tool
    
    def generate_query_or_respond(self, state: MessagesState):
        """Call the model to generate a response or retrieve - following Custom RAG Agent pattern."""
        # Security check: Reject document modification requests
        messages = state["messages"]
        user_question = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_question = msg.content.lower()
                break
        
        # Check for document modification keywords
        modification_keywords = [
            '문서 생성', '문서 수정', '문서 삭제', '문서 작성', '문서 편집', '문서 변경',
            'pdf 생성', 'pdf 수정', 'pdf 삭제', 'pdf 작성', 'pdf 편집',
            'create document', 'modify document', 'delete document', 'write document', 'edit document',
            '업데이트', '수정', '삭제', '생성', '작성', '편집', '변경'
        ]
        
        if any(keyword in user_question for keyword in modification_keywords):
            rejection_message = AIMessage(
                content="죄송합니다. 문서 생성, 수정, 삭제 등의 작업은 보안상의 이유로 허용되지 않습니다. 문서 조회만 가능합니다."
            )
            return {"messages": [rejection_message]}
        
        if not self.retriever_tool:
            korean_prompt = get_korean_prompt()
            messages_with_prompt = [korean_prompt] + state["messages"]
            response = self.model.invoke(messages_with_prompt)
            return {"messages": [response]}
        
        # 이전 대화의 tool_calls가 있는 메시지 필터링
        # tool_calls가 있는 AIMessage는 tool response가 있어야 하므로, 
        # tool response가 없는 tool_calls 메시지는 제거
        filtered_messages = []
        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                # tool_calls가 있는 메시지인 경우, 다음 메시지가 tool response인지 확인
                has_tool_response = False
                if i + 1 < len(messages):
                    next_msg = messages[i + 1]
                    if hasattr(next_msg, 'name') and next_msg.name:
                        # tool response 메시지인 경우
                        has_tool_response = True
                
                # tool response가 없으면 이 메시지를 제거 (이전 대화의 미완료 tool_calls)
                if not has_tool_response:
                    continue
            
            filtered_messages.append(msg)
        
        # 필터링된 메시지 사용
        response = (
            self.model
            .bind_tools([self.retriever_tool]).invoke(filtered_messages)
        )
        return {"messages": state["messages"] + [response]}
    
    def grade_documents(
        self, state: MessagesState
    ) -> Literal["generate_answer", "rewrite_question"]:
        """Determine whether the retrieved documents are relevant - following Custom RAG Agent pattern."""
        messages = state["messages"]
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        question = last_human_message.content if last_human_message else (messages[0].content if messages else "")
        context = state["messages"][-1].content
        
        prompt = GRADE_PROMPT.format(question=question, context=context)
        response = self.model.invoke([{"role": "user", "content": prompt}])
        score = response.content.strip().lower()
        
        if "yes" in score:
            return "generate_answer"
        else:
            return "rewrite_question"
    
    def rewrite_question(self, state: MessagesState):
        """Rewrite the original user question - following Custom RAG Agent pattern."""
        messages = state["messages"]
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        question = last_human_message.content if last_human_message else (messages[0].content if messages else "")
        prompt = REWRITE_PROMPT.format(question=question)
        response = self.model.invoke([{"role": "user", "content": prompt}])
        return {"messages": [HumanMessage(content=response.content)]}
    
    def generate_answer(self, state: MessagesState):
        """Generate an answer - following Custom RAG Agent pattern."""
        messages = state["messages"]
        last_human_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_human_message = msg
                break
        question = last_human_message.content if last_human_message else (messages[0].content if messages else "")
        context = state["messages"][-1].content
        prompt = GENERATE_ANSWER_PROMPT.format(question=question, context=context)
        response = self.model.invoke([{"role": "user", "content": prompt}])
        return {"messages": [response]}

