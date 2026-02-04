"""
RAG Agent Nodes for LangGraph workflow.
"""
import sys
sys.dont_write_bytecode = True

from typing import Literal
from langchain_core.messages import HumanMessage
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
            from langchain_core.messages import AIMessage
            rejection_message = AIMessage(
                content="죄송합니다. 문서 생성, 수정, 삭제 등의 작업은 보안상의 이유로 허용되지 않습니다. 문서 조회만 가능합니다."
            )
            return {"messages": [rejection_message]}
        
        if not self.retriever_tool:
            korean_prompt = get_korean_prompt()
            messages_with_prompt = [korean_prompt] + state["messages"]
            response = self.model.invoke(messages_with_prompt)
            return {"messages": [response]}
        
        response = (
            self.model
            .bind_tools([self.retriever_tool]).invoke(state["messages"])
        )
        return {"messages": [response]}
    
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

