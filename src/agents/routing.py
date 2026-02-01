"""
Routing logic for SQL vs RAG workflow selection.
"""
import sys
sys.dont_write_bytecode = True

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import MessagesState

from src.agents.prompts import get_routing_prompt


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
        
        response = self.model.invoke([{"role": "user", "content": routing_prompt + f"\n\nQuestion: {question}"}])
        decision = response.content.strip().upper()
        
        return {"messages": state["messages"] + [AIMessage(content=decision)]}
    
    def route_initial_query_condition(self, state: MessagesState) -> str:
        """Route condition function for conditional edge."""
        messages = state["messages"]
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                decision = msg.content.strip().upper()
                if "SQL" in decision:
                    return "sql_workflow"
                elif "RAG" in decision:
                    return "rag_workflow"
                else:
                    return "direct_response"
        
        return "sql_workflow"

