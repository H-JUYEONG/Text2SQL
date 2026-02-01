"""
Graph builder for LangGraph workflow.
"""
import sys
sys.dont_write_bytecode = True

import logging
from typing import Literal
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

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
        workflow.add_node("run_query", self.sql_nodes._run_query_with_logging)
        workflow.add_node("format_results", self.sql_nodes.format_query_results)
        
        # RAG Workflow Nodes
        workflow.add_node("generate_query_or_respond", self.rag_nodes.generate_query_or_respond)
        if self.retriever_tool:
            workflow.add_node("retrieve", ToolNode([self.retriever_tool]))
        workflow.add_node("rewrite_question", self.rag_nodes.rewrite_question)
        workflow.add_node("generate_answer", self.rag_nodes.generate_answer)
        
        # Routing Node
        workflow.add_node("route_initial_query", self.routing.route_initial_query_node)
        
        # Direct Response
        def direct_response(state: MessagesState):
            """Direct response without tools."""
            korean_prompt = get_korean_prompt()
            messages_with_prompt = [korean_prompt] + state["messages"]
            response = self.model.invoke(messages_with_prompt)
            return {"messages": [response]}
        
        workflow.add_node("direct_response", direct_response)
        
        # Edges
        workflow.add_edge(START, "route_initial_query")
        
        # Route to SQL or RAG workflow
        workflow.add_conditional_edges(
            "route_initial_query",
            self.routing.route_initial_query_condition,
            {
                "sql_workflow": "list_tables",
                "rag_workflow": "generate_query_or_respond",
                "direct_response": "direct_response",
            },
        )
        
        # SQL workflow edges
        workflow.add_edge("list_tables", "call_get_schema")
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
        workflow.add_edge("check_query", "run_query")
        
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
        
        # Compile with checkpointer for thread-scoped memory
        return workflow.compile(checkpointer=self.agent.checkpointer)

