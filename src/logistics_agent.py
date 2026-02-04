"""
Logistics Text2SQL + RAG Agent using LangGraph 1.0+
Refactored with modular components.
"""
import sys
sys.dont_write_bytecode = True

import os
import logging
from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from src.config import (
    LLM_MODEL,
    LLM_TEMPERATURE,
    DATABASE_URI,
    OPENAI_API_KEY,
    ANTHROPIC_API_KEY,
    MAX_QUERY_RESULTS,
    QUERY_TIMEOUT_SECONDS,
    ENABLE_QUERY_LOGGING,
    LOG_LEVEL,
)

from src.agents.sql_nodes import SQLNodes
from src.agents.rag_nodes import RAGNodes
from src.agents.routing import Routing
from src.agents.graph_builder import GraphBuilder

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Set API keys
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY
if ANTHROPIC_API_KEY:
    os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY


class LogisticsAgent:
    """Logistics Text2SQL + RAG Agent following reference patterns."""
    
    def __init__(
        self,
        db_uri: str = None,
        vector_store=None,
        llm_model: str = None,
    ):
        """Initialize the agent with database and vector store."""
        # Initialize database
        self.db_uri = db_uri or DATABASE_URI
        self.db = SQLDatabase.from_uri(self.db_uri)
        
        # Enterprise settings
        self.max_query_results = MAX_QUERY_RESULTS
        self.small_result_threshold = int(os.getenv("SMALL_RESULT_THRESHOLD", "50"))
        self.limit_for_large_results = int(os.getenv("LIMIT_FOR_LARGE_RESULTS", "50"))
        self.query_timeout = QUERY_TIMEOUT_SECONDS
        self.enable_logging = ENABLE_QUERY_LOGGING
        
        # Initialize LLM
        self.llm_model = llm_model or LLM_MODEL
        self.model = init_chat_model(
            self.llm_model,
            temperature=LLM_TEMPERATURE,
        )
        
        # Initialize SQL tools
        self.sql_toolkit = SQLDatabaseToolkit(db=self.db, llm=self.model)
        self.sql_tools = self.sql_toolkit.get_tools()
        
        # Get specific SQL tools
        self.list_tables_tool = next(
            (tool for tool in self.sql_tools if tool.name == "sql_db_list_tables"),
            None
        )
        self.get_schema_tool = next(
            (tool for tool in self.sql_tools if tool.name == "sql_db_schema"),
            None
        )
        self.run_query_tool = next(
            (tool for tool in self.sql_tools if tool.name == "sql_db_query"),
            None
        )
        
        # Initialize vector store for RAG
        self.vector_store = vector_store
        
        # Create RAG retriever tool if vector store is available
        self.retriever_tool = None
        if self.vector_store:
            self.retriever_tool = self._create_rag_tool()
        
        # Initialize checkpointer for thread-scoped memory
        self.checkpointer = MemorySaver()
        
        # Initialize modular components
        self.sql_nodes = SQLNodes(self)
        self.rag_nodes = RAGNodes(self)
        self.routing = Routing(self)
        self.graph_builder = GraphBuilder(self)
        
        # Build the graph
        self.graph = self.graph_builder.build_graph()
    
    def _create_rag_tool(self):
        """Create a RAG retrieval tool following Custom RAG Agent pattern."""
        @tool
        def retrieve_logistics_context(query: str) -> str:
            """Search and return information about logistics documentation."""
            if not self.vector_store:
                return "Vector store not available."
            
            docs = self.vector_store.similarity_search(query, k=3)
            return "\n\n".join([doc.page_content for doc in docs])
        
        return retrieve_logistics_context
    
    def invoke(self, query: str, config: dict = None, thread_id: str = "default"):
        """Invoke the agent with a query and thread_id for conversation memory."""
        config = config or {}
        config["configurable"] = {"thread_id": thread_id}
        
        result = self.graph.invoke(
            {"messages": [HumanMessage(content=query)]},
            config,
        )
        return result
    
    def stream(self, query: str, config: dict = None):
        """Stream the agent's response."""
        config = config or {}
        for chunk in self.graph.stream(
            {"messages": [{"role": "user", "content": query}]},
            config,
        ):
            yield chunk


if __name__ == "__main__":
    # Example usage
    print("Initializing Logistics Agent...")
    agent = LogisticsAgent()
    
    # Test query
    query = "What tables are available in the database?"
    
    print(f"\nQuery: {query}\n")
    print("Response:")
    
    for chunk in agent.stream(query):
        for node, update in chunk.items():
            if "messages" in update:
                last_msg = update["messages"][-1]
                if hasattr(last_msg, "content") and last_msg.content:
                    print(f"[{node}] {last_msg.content}")
                elif hasattr(last_msg, "tool_calls"):
                    print(f"[{node}] Tool calls: {[tc['name'] for tc in last_msg.tool_calls]}")

