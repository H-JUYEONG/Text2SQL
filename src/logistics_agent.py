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
    LLM_MAX_TOKENS,
    DATABASE_URI,
    OPENAI_API_KEY,
    ANTHROPIC_API_KEY,
    MAX_QUERY_RESULTS,
    QUERY_TIMEOUT_SECONDS,
    ENABLE_QUERY_LOGGING,
    LOG_LEVEL,
    CHECKPOINT_DB_URI,
    USE_DB_CHECKPOINTER,
)

from src.agents.sql_nodes import SQLNodes
from src.agents.rag_nodes import RAGNodes
from src.agents.routing import Routing
from src.agents.question_agent import QuestionAgent
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
            max_tokens=LLM_MAX_TOKENS,  # 응답이 잘리지 않도록 충분한 토큰 수 설정
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
        # HITL을 위해 DB 기반 체크포인터 사용 가능 (선택사항)
        # 최신 LangGraph 방식: PostgresSaver 사용 (3.0.4+)
        if USE_DB_CHECKPOINTER:
            try:
                # 최신 LangGraph checkpoint-postgres 3.0.4+ 방식
                from langgraph.checkpoint.postgres import PostgresSaver
                
                # SQLAlchemy 형식(postgresql+psycopg2://)을 LangGraph 형식(postgresql://)으로 변환
                checkpoint_uri = CHECKPOINT_DB_URI.replace("postgresql+psycopg2://", "postgresql://")
                
                # 최신 방식: from_conn_string()은 context manager를 반환
                # context manager를 사용하여 PostgresSaver 인스턴스 얻기
                cm = PostgresSaver.from_conn_string(checkpoint_uri)
                # context manager 진입하여 실제 인스턴스 얻기
                self.checkpointer = cm.__enter__()
                # context manager를 저장하여 나중에 정리할 수 있도록 함
                self._checkpoint_cm = cm
                
                # 테이블 자동 생성 (setup 메서드 호출)
                # checkpoints, checkpoint_blobs 테이블이 없으면 자동 생성
                try:
                    self.checkpointer.setup()
                    logger.info("✅ 체크포인트 테이블 생성 완료 (checkpoints, checkpoint_blobs)")
                except Exception as setup_error:
                    # 테이블이 이미 존재하는 경우 무시
                    if "already exists" not in str(setup_error).lower():
                        logger.warning(f"⚠️  체크포인트 테이블 생성 중 오류 (무시 가능): {setup_error}")
                
                logger.info("✅ DB 기반 체크포인터 초기화 완료 (PostgreSQL - 최신 방식)")
                logger.info(f"   체크포인트 DB: {checkpoint_uri.split('@')[1] if '@' in checkpoint_uri else checkpoint_uri}")
            except ImportError as e:
                logger.warning("⚠️  langgraph-checkpoint-postgres 패키지가 없습니다. MemorySaver를 사용합니다.")
                logger.warning("   DB 체크포인터를 사용하려면: pip install langgraph-checkpoint-postgres")
                logger.debug(f"   ImportError: {e}")
                self.checkpointer = MemorySaver()
                self._checkpoint_cm = None
            except Exception as e:
                logger.warning(f"⚠️  DB 체크포인터 초기화 실패: {e}. MemorySaver를 사용합니다.")
                logger.warning(f"   에러 상세: {type(e).__name__}: {str(e)}")
                import traceback
                logger.debug(traceback.format_exc())
                self.checkpointer = MemorySaver()
                self._checkpoint_cm = None
        else:
            self.checkpointer = MemorySaver()
            self._checkpoint_cm = None
            logger.info("✅ 메모리 기반 체크포인터 초기화 완료 (MemorySaver)")
        
        # Initialize modular components
        self.sql_nodes = SQLNodes(self)
        self.rag_nodes = RAGNodes(self)
        self.routing = Routing(self)
        self.question_agent = QuestionAgent(self)
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

