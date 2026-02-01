"""
Logistics Text2SQL + RAG Agent using LangGraph 1.0+
Based on Custom SQL Agent and Custom RAG Agent patterns from LangChain documentation.
"""
import os
import re
import logging
from typing import Literal, Tuple
from pydantic import BaseModel, Field

from langchain.chat_models import init_chat_model
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.tools import tool
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from config import (
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
        
        # Get specific SQL tools (following Custom SQL Agent pattern)
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
        
        # Create RAG retriever tool if vector store is available (following Custom RAG Agent pattern)
        self.retriever_tool = None
        if self.vector_store:
            self.retriever_tool = self._create_rag_tool()
        
        # Build the graph
        self.graph = self._build_graph()
    
    def _validate_query_security(self, query: str) -> Tuple[bool, str]:
        """Validate SQL query for security - enterprise requirement."""
        if not query or not query.strip():
            return False, "빈 쿼리는 실행할 수 없습니다."
        
        query_upper = query.upper().strip()
        
        # 위험한 SQL 키워드 차단
        dangerous_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE', 
            'ALTER', 'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
            'MERGE', 'REPLACE', 'LOAD', 'COPY', 'IMPORT', 'EXPORT'
        ]
        
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                logger.warning(f"Blocked dangerous SQL keyword: {keyword}")
                return False, f"보안상의 이유로 {keyword} 문은 실행할 수 없습니다. 읽기 전용 쿼리만 허용됩니다."
        
        # SELECT로 시작하는지 확인
        if not query_upper.startswith('SELECT'):
            return False, "SELECT 쿼리만 실행할 수 있습니다."
        
        # 시스템 테이블 접근 차단 (SQLite의 경우)
        system_tables = ['sqlite_master', 'sqlite_temp_master', 'sqlite_sequence']
        for table in system_tables:
            if table in query_upper:
                logger.warning(f"Blocked system table access: {table}")
                return False, "시스템 테이블에 대한 접근은 허용되지 않습니다."
        
        return True, ""
    
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
    
    # ========== SQL Agent Nodes (following Custom SQL Agent pattern) ==========
    
    def list_tables(self, state: MessagesState):
        """List all available tables - predetermined tool call pattern."""
        tool_call = {
            "name": "sql_db_list_tables",
            "args": {},
            "id": "list_tables_001",
            "type": "tool_call",
        }
        tool_call_message = AIMessage(content="", tool_calls=[tool_call])
        
        tool_message = self.list_tables_tool.invoke(tool_call)
        response = AIMessage(f"Available tables: {tool_message.content}")
        
        return {"messages": [tool_call_message, tool_message, response]}
    
    def call_get_schema(self, state: MessagesState):
        """Call the get schema tool - force tool call pattern."""
        llm_with_tools = self.model.bind_tools([self.get_schema_tool], tool_choice="any")
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}
    
    def generate_query(self, state: MessagesState):
        """Generate SQL query - following Custom SQL Agent pattern."""
        max_results = min(5, self.max_query_results)
        generate_query_system_prompt = f"""
You are an agent designed to interact with a SQL database for logistics operations.
Given an input question, create a syntactically correct {self.db.dialect} query to run,
then look at the results of the query and return the answer in natural, conversational Korean.

CRITICAL: When you receive query results, you MUST interpret and format them as a natural language answer.
- Query results may come as tuples, lists, or raw data - you MUST convert them to readable Korean text
- NEVER return raw query results like tuples or lists - always format as natural sentences
- Interpret each row of data and present it in a user-friendly format
- For list queries, format as numbered items or bullet points in Korean
- Include all relevant information from the query results in your answer

Unless the user specifies a specific number of examples they wish to obtain, always limit your
query to at most {max_results} results for performance and usability.

GENERAL QUERY GENERATION PRINCIPLES:
1. Understand the question intent first - is it asking for:
   - A list of records? (use SELECT with appropriate filters)
   - Aggregated statistics? (use COUNT, SUM, AVG, MAX, MIN with GROUP BY)
   - Comparisons or rankings? (use ORDER BY with LIMIT)
   - Time-based analysis? (use date functions and date range filters)
   - Relationships between entities? (use appropriate JOINs)
   - Status or state information? (MUST JOIN with the table containing status/state columns)

CRITICAL: When the question mentions status, state, or completion status (e.g., "배송이 완료되지 않은", "미완료", "완료된", "지연된", "배송 상태"):
   - You MUST identify which table contains the status/state information (check schema to find the table with status column)
   - You MUST JOIN with that table to access the status column
   - You MUST include the status column in your SELECT clause so users can see the status
   - You MUST filter by the status column using explicit comparison with ACTUAL database enum values (English, NOT Korean)
   - For deliveries.status: Use 'delivered', 'shipped', 'pending', 'delayed' (English lowercase), NOT '배송 완료', '배송중', etc.
   - NEVER query only the primary table when status information is needed from a related table
   - If you query orders alone when delivery status is asked, you are WRONG - you MUST JOIN with deliveries table
   - Do NOT say "additional information is needed" - you have access to all tables via JOINs

2. Table Relationships:
   - 1:1 relationships: Every record in primary table has exactly one related record
   - 1:N relationships: One record can have multiple related records (use GROUP BY for aggregations)
   - N:1 relationships: Multiple records reference one parent record
   - Always check the schema to understand foreign key relationships

3. Status and State Columns:
   - Status columns typically represent current state and are usually NOT NULL
   - CRITICAL: Status values in the database are stored in their original format (usually English enum values)
   - ABSOLUTELY CRITICAL: NEVER use Korean or translated status values in SQL queries
   - NEVER use values like '배송 완료', '배송중', '대기중', '지연' in SQL - these are Korean translations, NOT database values
   - You MUST check the schema first to see what actual values are stored (typically English lowercase strings)
   
   MANDATORY STATUS VALUE MAPPING (for deliveries.status column):
   - Korean "배송 완료" or "완료된" → English 'delivered' (NOT '배송 완료')
   - Korean "배송중" or "배송 중" → English 'shipped' (NOT '배송중')
   - Korean "대기중" or "대기" → English 'pending' (NOT '대기중')
   - Korean "지연" or "지연된" → English 'delayed' (NOT '지연')
   
   - When checking for "incomplete" or "not completed", use explicit status comparison with the ACTUAL database enum value
   - If user asks "배송이 완료되지 않은", translate this to: status != 'delivered' (English value), NOT status != '배송 완료' (Korean)
   - If user asks "배송 완료된", translate this to: status = 'delivered' (English value), NOT status = '배송 완료' (Korean)
   - NEVER translate status values to other languages in SQL queries - use the actual values stored in the database
   - Check the schema or sample data to understand what status values are actually stored in the database
   - The deliveries.status column contains these exact values: 'delivered', 'shipped', 'pending', 'delayed' (all lowercase English)
   - NEVER use "status IS NULL" to check for incomplete states unless the schema explicitly allows NULL
   - When filtering by status from a related table, use INNER JOIN (not LEFT JOIN with NULL check)
   - CRITICAL: When user asks about "not completed" or "incomplete" items, they mean items with status != completion_value, NOT items missing from the related table
   - Example pattern: When user asks about "not completed" or "incomplete" items, it means items with status != completion_value (check actual DB values), NOT items missing from the related table
   - Always JOIN with the status table and filter by status column, never use NOT IN to find missing records
   - MANDATORY: If the question asks about delivery status, shipping status, completion status, or any status-related information:
     * You MUST identify which table contains the status column (e.g., deliveries table for delivery status)
     * You MUST JOIN with that table to access the status column
     * You MUST include the status column in your SELECT clause so users can see the status
     * You MUST filter by the status column in WHERE clause using explicit comparison
     * Do NOT query only the primary table (e.g., orders) when status information is needed - you MUST JOIN
     * If you query orders alone when delivery status is asked, you are making a mistake - JOIN with deliveries table
     * Do NOT respond saying "additional information is needed" or "need to check delivery table" - you have access to all tables via JOINs, just use them

4. JOIN Operations:
   - Use INNER JOIN when you need records that exist in both tables
   - Use LEFT JOIN only when you need all records from the left table regardless of matches
   - When filtering by columns from joined tables, prefer INNER JOIN
   - Always include relevant columns from ALL joined tables in SELECT clause
   - When filtering by a column, include that column in SELECT so users can see the filter criteria

5. Aggregations and Grouping:
   - Use GROUP BY when calculating statistics per category (e.g., per driver, per region, per category)
   - Include the grouping column(s) in SELECT clause
   - Use appropriate aggregate functions: COUNT, SUM, AVG, MAX, MIN
   - Use HAVING for filtering aggregated results (not WHERE)

6. Date and Time Handling:
   - Use appropriate date functions for date comparisons and calculations
   - For "this week", "this month", "recent" queries, use date range filters
   - Calculate time differences using date arithmetic functions
   - Consider timezone if applicable

7. Filtering and Sorting:
   - Apply WHERE clauses for record-level filtering
   - Use ORDER BY to sort results meaningfully
   - For "most", "top", "highest" queries, use ORDER BY ... DESC LIMIT
   - For "least", "lowest" queries, use ORDER BY ... ASC LIMIT

8. Column Selection:
   - Only select columns relevant to the question
   - Include columns used in WHERE, GROUP BY, ORDER BY clauses
   - Include status/state columns when they're part of the answer
   - Never select all columns with SELECT * unless specifically needed

CRITICAL: You MUST respond in Korean (한국어). All answers must be written in natural, conversational Korean.

When formatting the final answer from query results in Korean:
- CRITICAL: You MUST convert raw query results (tuples, lists) into natural Korean sentences
- NEVER return raw data like tuples, lists, or raw database output - always format as readable text
- Always respond in natural, conversational Korean
- For list queries, format as numbered items with clear labels for each column
- Example format pattern: "[Question topic] 목록은 다음과 같습니다:\n\n1. [Column1 Label]: [value1] / [Column2 Label]: [value2] / [Column3 Label]: [value3]\n2. [Column1 Label]: [value1] / [Column2 Label]: [value2] / [Column3 Label]: [value3]\n\n총 [count]개의 [item type]이 [condition]입니다."
- Translate any English status values or technical terms to appropriate Korean equivalents naturally
- Adapt the format based on the actual query results and question asked
- Use a friendly, easy-to-read format with simple separators like "/" or "·"
- Include all relevant columns from the query results in your response
- When status or state information is part of the query results, always include it in the answer
- Format the answer to be clear and readable, showing all important information from the query results
- Make the answer sound natural and conversational, adapting to the specific data returned by the query
- Do not use hardcoded example values - use the actual data from the query results
- Always provide a summary or count when appropriate, adapting to the context of the question

SECURITY REQUIREMENTS (CRITICAL for enterprise use):
- ONLY generate SELECT queries for data retrieval
- NEVER generate DML statements: INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE
- NEVER generate queries that could modify data, schema, or system settings
- NEVER generate queries that access system tables or sensitive metadata
- Always use read-only operations
- If the user asks for data modification, politely explain that only read operations are allowed
"""
        
        system_message = {
            "role": "system",
            "content": generate_query_system_prompt,
        }
        # 사용자 질문 로깅
        if self.enable_logging:
            user_question = state["messages"][0].content if state["messages"] else "Unknown"
            logger.info("=" * 80)
            logger.info("📝 [USER QUESTION] 사용자 질문:")
            logger.info(f"질문: {user_question}")
            logger.info("=" * 80)
        
        # Check if we have query results in the messages (after query execution)
        # If so, we should format the answer, not generate a new query
        has_query_results = False
        # Look for tool messages from sql_db_query (actual query results)
        for msg in reversed(state["messages"][-10:]):  # Check last 10 messages
            # Check if this is a tool message from sql_db_query
            if hasattr(msg, 'name') and msg.name == 'sql_db_query':
                has_query_results = True
                if self.enable_logging:
                    logger.info("📊 [QUERY RESULTS DETECTED] 쿼리 결과가 감지되었습니다. 답변 포맷팅을 진행합니다.")
                break
            # Also check content for actual query result patterns (tuples/lists with data)
            elif hasattr(msg, 'content') and msg.content:
                content = str(msg.content)
                # More specific check: looks like actual data results, not schema info
                if (content.strip().startswith('[') and '),' in content) or \
                   (content.strip().startswith('(') and '),' in content):
                    # Make sure it's not schema information
                    if 'table_info' not in content.lower() and 'pragma' not in content.lower() and \
                       'integer' not in content.lower() or ('),' in content and len(content) > 50):
                        has_query_results = True
                        if self.enable_logging:
                            logger.info("📊 [QUERY RESULTS DETECTED] 쿼리 결과가 감지되었습니다. 답변 포맷팅을 진행합니다.")
                        break
        
        # If we have results, don't bind tools - just format the answer
        if has_query_results:
            # Add instruction to format the results
            format_instruction = {
                "role": "system",
                "content": "You have received SQL query results. Convert them into a natural, conversational Korean answer. Format the raw data (tuples, lists) as readable text with proper formatting. Include all information from the results."
            }
            response = self.model.invoke([format_instruction] + state["messages"])
            if self.enable_logging:
                logger.info("📝 [ANSWER FORMATTING] 쿼리 결과를 자연어로 포맷팅 중...")
        else:
            # We do not force a tool call here, to allow the model to
            # respond naturally when it obtains the solution.
            if self.enable_logging:
                logger.info("🤖 [LLM PROCESSING] LLM이 쿼리를 생성하는 중...")
            llm_with_tools = self.model.bind_tools([self.run_query_tool])
            response = llm_with_tools.invoke([system_message] + state["messages"])
        
        # 쿼리 생성 로깅 (기업 환경)
        if self.enable_logging:
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tool_call in response.tool_calls:
                    if tool_call.get('name') == 'sql_db_query':
                        generated_query = tool_call.get('args', {}).get('query', '')
                        if generated_query:
                            logger.info("=" * 80)
                            logger.info("🔍 [QUERY GENERATION] 에이전트가 생성한 SQL 쿼리:")
                            logger.info(f"SQL: {generated_query}")
                            logger.info("=" * 80)
            elif hasattr(response, 'content') and response.content:
                # LLM이 직접 답변한 경우 (쿼리 없이)
                logger.info("💬 [DIRECT RESPONSE] LLM이 직접 답변을 생성했습니다.")
                logger.info(f"답변: {response.content[:200]}...")
        
        return {"messages": [response]}
    
    def check_query(self, state: MessagesState):
        """Check SQL query for common mistakes and security - following Custom SQL Agent pattern."""
        check_query_system_prompt = f"""
You are a SQL expert with a strong attention to detail and security.
Double check the {self.db.dialect} query for common mistakes and security issues, including:

SQL SYNTAX AND LOGIC CHECKS:
- Using NOT IN with NULL values (use NOT EXISTS or handle NULLs properly)
- Using UNION when UNION ALL should have been used
- Using BETWEEN for exclusive ranges (check if endpoints should be included)
- Data type mismatch in predicates
- Properly quoting identifiers
- Using the correct number of arguments for functions
- Casting to the correct data type
- Using the proper columns for joins (foreign key relationships)

QUERY LOGIC AND DOMAIN CHECKS:
- Verify JOIN types are appropriate:
  * INNER JOIN when filtering by columns from joined table
  * LEFT JOIN only when you need all records from left table
  * If filtering by status/state from related table, INNER JOIN is usually correct
- Verify status/state filtering:
  * Status columns are typically NOT NULL - use explicit comparisons
  * "Incomplete" or "not completed" should use != or NOT IN, not IS NULL
  * CRITICAL: Status values in WHERE clauses MUST be the actual database enum values (usually English)
  * NEVER allow Korean or translated status values in SQL queries (e.g., '배송 완료', '배송중')
  * If you see Korean status values in the query, they MUST be replaced with actual database values
  * Check schema to understand valid status values - they are typically English lowercase strings
  * Common mistake: Using translated values like '배송 완료' instead of actual DB value 'delivered'
- Verify aggregation logic:
  * GROUP BY columns match non-aggregated columns in SELECT
  * HAVING used for aggregated filters, WHERE for record-level filters
  * Aggregate functions used correctly (COUNT, SUM, AVG, etc.)
- Verify date/time handling:
  * Date comparisons use appropriate functions
  * Date ranges are inclusive/exclusive as intended
  * Time calculations are correct
- Verify filtering logic:
  * WHERE conditions match the question intent
  * Multiple conditions combined correctly (AND/OR)
  * NULL handling is appropriate for the data model
- Verify result ordering and limiting:
  * ORDER BY matches the question intent (ASC/DESC)
  * LIMIT is appropriate for the question type
  * Top N / Bottom N queries use correct ordering

SECURITY CHECKS (CRITICAL for enterprise use):
- REJECT any DML statements: INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER, CREATE, GRANT, REVOKE
- REJECT any statements that could modify data or schema
- REJECT queries that attempt to access system tables or sensitive information
- REJECT schema inspection queries like PRAGMA, INFORMATION_SCHEMA, or DESCRIBE - these are not data queries
- Only allow SELECT statements for data retrieval
- Ensure queries are read-only operations only

CRITICAL: Do NOT change a valid SELECT query into a schema inspection query (PRAGMA, DESCRIBE, etc.)
If the original query is a valid SELECT query, keep it as SELECT - only fix syntax or logic errors
If there are any mistakes, security violations, or domain logic errors, rewrite the query to be safe and correct while maintaining the SELECT structure.
If there are no mistakes, just reproduce the original query EXACTLY as it was.

You will call the appropriate tool to execute the query after running this check.
""".format(dialect=self.db.dialect)
        
        system_message = {
            "role": "system",
            "content": check_query_system_prompt,
        }
        
        # 먼저 보안 검증 수행
        tool_call = state["messages"][-1].tool_calls[0]
        query = tool_call["args"]["query"]
        
        # 쿼리 검증 전 로깅
        if self.enable_logging:
            logger.info("=" * 80)
            logger.info("🔒 [QUERY VALIDATION] 쿼리 검증 시작")
            logger.info(f"Original Query: {query}")
            logger.info("=" * 80)
        
        # 한국어 상태 값 사용 검증 및 수정
        korean_status_values = ['배송 완료', '배송완료', '배송중', '대기중', '지연', '배송 지연']
        query_upper = query.upper()
        has_korean_status = any(kv in query for kv in korean_status_values)
        
        if has_korean_status:
            logger.warning("⚠️  [STATUS VALUE ERROR] 한국어 상태 값이 쿼리에 사용되었습니다!")
            logger.warning(f"문제가 있는 쿼리: {query}")
            # 한국어를 영어로 매핑 (일반적인 경우)
            query_fixed = query
            query_fixed = query_fixed.replace("'배송 완료'", "'delivered'")
            query_fixed = query_fixed.replace("'배송완료'", "'delivered'")
            query_fixed = query_fixed.replace("'배송중'", "'shipped'")
            query_fixed = query_fixed.replace("'대기중'", "'pending'")
            query_fixed = query_fixed.replace("'지연'", "'delayed'")
            query_fixed = query_fixed.replace("'배송 지연'", "'delayed'")
            
            if query_fixed != query:
                logger.warning("🔧 [AUTO FIX] 한국어 상태 값을 영어로 자동 수정합니다.")
                logger.warning(f"수정된 쿼리: {query_fixed}")
                # 수정된 쿼리로 tool_call 업데이트
                tool_call["args"]["query"] = query_fixed
                query = query_fixed
        
        is_valid, error_msg = self._validate_query_security(query)
        if not is_valid:
            logger.warning(f"❌ [SECURITY BLOCK] Query security validation failed: {error_msg}")
            logger.warning(f"Blocked Query: {query}")
            error_response = AIMessage(
                content=f"쿼리 검증 실패: {error_msg}",
                id=state["messages"][-1].id
            )
            return {"messages": [error_response]}
        
        logger.info("✅ [SECURITY PASS] 쿼리 보안 검증 통과")
        
        # Generate an artificial user message to check
        user_message = {"role": "user", "content": query}
        llm_with_tools = self.model.bind_tools([self.run_query_tool], tool_choice="any")
        response = llm_with_tools.invoke([system_message, user_message])
        response.id = state["messages"][-1].id
        
        # 검증 후 최종 쿼리 로깅
        if self.enable_logging and hasattr(response, 'tool_calls') and response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.get('name') == 'sql_db_query':
                    validated_query = tool_call.get('args', {}).get('query', '')
                    if validated_query:
                        logger.info("=" * 80)
                        logger.info("✅ [QUERY VALIDATED] 검증 완료된 최종 SQL 쿼리:")
                        logger.info(f"SQL: {validated_query}")
                        if validated_query != query:
                            logger.info("⚠️  [QUERY MODIFIED] 원본 쿼리가 수정되었습니다.")
                            logger.info(f"Original: {query}")
                        logger.info("=" * 80)
        
        return {"messages": [response]}
    
    # ========== RAG Agent Nodes (following Custom RAG Agent pattern) ==========
    
    def generate_query_or_respond(self, state: MessagesState):
        """Call the model to generate a response or retrieve - following Custom RAG Agent pattern."""
        if not self.retriever_tool:
            # No RAG tool available, just respond
            korean_prompt = {
                "role": "system",
                "content": "You are a helpful assistant. Always respond in Korean (한국어) in a natural, conversational style."
            }
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
        GRADE_PROMPT = (
            "You are a grader assessing relevance of a retrieved document to a user question. \n "
            "Here is the retrieved document: \n\n {context} \n\n"
            "Here is the user question: {question} \n"
            "If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. \n"
            "Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question."
        )
        
        question = state["messages"][0].content
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
        REWRITE_PROMPT = (
            "Look at the input and try to reason about the underlying semantic intent / meaning.\n"
            "Here is the initial question:"
            "\n ------- \n"
            "{question}"
            "\n ------- \n"
            "Formulate an improved question:"
        )
        
        messages = state["messages"]
        question = messages[0].content
        prompt = REWRITE_PROMPT.format(question=question)
        response = self.model.invoke([{"role": "user", "content": prompt}])
        return {"messages": [HumanMessage(content=response.content)]}
    
    def generate_answer(self, state: MessagesState):
        """Generate an answer - following Custom RAG Agent pattern."""
        GENERATE_PROMPT = (
            "You are an assistant for question-answering tasks. "
            "Use the following pieces of retrieved context to answer the question. "
            "If you don't know the answer, just say that you don't know. "
            "Use three sentences maximum and keep the answer concise. "
            "IMPORTANT: Always respond in Korean (한국어) in a natural, conversational style.\n"
            "Question: {question} \n"
            "Context: {context}"
        )
        
        question = state["messages"][0].content
        context = state["messages"][-1].content
        prompt = GENERATE_PROMPT.format(question=question, context=context)
        response = self.model.invoke([{"role": "user", "content": prompt}])
        return {"messages": [response]}
    
    # ========== Routing Logic ==========
    
    def route_initial_query_node(self, state: MessagesState):
        """Route initial query to SQL or RAG workflow - node function."""
        routing_prompt = """
You are a routing agent for a logistics question-answering system.
Based on the user's question, decide which workflow to use:

1. If the question requires querying the database (e.g., asking for data, counts, lists, aggregations, or table information), use SQL workflow.
2. If the question is about concepts, policies, processes, or general knowledge (e.g., "what is X", "how does Y work"), use RAG workflow.
3. If it's a simple greeting or doesn't require data or knowledge retrieval, respond directly.

Respond with only "SQL" or "RAG" or "DIRECT".

IMPORTANT: All responses must be in Korean (한국어).
"""
        
        question = state["messages"][0].content
        response = self.model.invoke([{"role": "user", "content": routing_prompt + f"\n\nQuestion: {question}"}])
        decision = response.content.strip().upper()
        
        # Store decision in state for conditional edge
        return {"messages": state["messages"] + [AIMessage(content=decision)]}
    
    def route_initial_query_condition(self, state: MessagesState) -> str:
        """Route condition function for conditional edge."""
        messages = state["messages"]
        # Get the last AI message which contains the routing decision
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                decision = msg.content.strip().upper()
                if "SQL" in decision:
                    return "sql_workflow"
                elif "RAG" in decision:
                    return "rag_workflow"
                else:
                    return "direct_response"
        
        # Default to SQL workflow
        return "sql_workflow"
    
    def _run_query_with_logging(self, state: MessagesState):
        """Run query with detailed logging for enterprise monitoring."""
        # ToolNode를 직접 사용하되, 실행 전후에 로깅 추가
        tool_node = ToolNode([self.run_query_tool])
        
        # 실행 전 쿼리 추출 및 로깅
        if self.enable_logging:
            messages = state["messages"]
            for msg in reversed(messages):
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        if tool_call.get('name') == 'sql_db_query':
                            query_to_execute = tool_call.get('args', {}).get('query', '')
                            if query_to_execute:
                                logger.info("=" * 80)
                                logger.info("🚀 [QUERY EXECUTION] SQL 쿼리 실행 시작")
                                logger.info(f"SQL: {query_to_execute}")
                                logger.info("=" * 80)
                            break
                    break
        
        # 쿼리 실행
        result = tool_node.invoke(state)
        
        # 실행 후 결과 로깅
        if self.enable_logging:
            if result and 'messages' in result:
                last_msg = result['messages'][-1]
                if hasattr(last_msg, 'content'):
                    result_preview = str(last_msg.content)[:500]  # 처음 500자만
                    logger.info("=" * 80)
                    logger.info("✅ [QUERY RESULT] 쿼리 실행 완료")
                    logger.info(f"Result Preview: {result_preview}...")
                    logger.info("=" * 80)
        
        return result
    
    def should_continue_sql(self, state: MessagesState) -> Literal[END, "check_query"]:
        """Determine next step in SQL workflow - following Custom SQL Agent pattern."""
        messages = state["messages"]
        last_message = messages[-1]
        
        # 무한 루프 방지: 같은 쿼리가 반복되면 중단
        if len(messages) > 10:  # 메시지가 너무 많으면 중단
            logger.warning("Too many messages in SQL workflow, stopping to prevent infinite loop")
            return END
        
        # 에러 메시지가 있으면 중단
        for msg in reversed(messages[-5:]):  # 최근 5개 메시지 확인
            if hasattr(msg, 'content') and msg.content:
                content = str(msg.content).lower()
                if 'error' in content or 'syntax error' in content or 'operationalerror' in content:
                    logger.warning("Error detected in messages, stopping SQL workflow")
                    return END
        
        if not last_message.tool_calls:
            return END
        else:
            return "check_query"
    
    def _build_graph(self):
        """Build the LangGraph workflow following reference patterns."""
        workflow = StateGraph(MessagesState)
        
        # ========== SQL Workflow Nodes (following Custom SQL Agent pattern) ==========
        workflow.add_node("list_tables", self.list_tables)
        workflow.add_node("call_get_schema", self.call_get_schema)
        workflow.add_node("get_schema", ToolNode([self.get_schema_tool]))
        workflow.add_node("generate_query", self.generate_query)
        workflow.add_node("check_query", self.check_query)
        workflow.add_node("run_query", self._run_query_with_logging)
        
        # ========== RAG Workflow Nodes (following Custom RAG Agent pattern) ==========
        workflow.add_node("generate_query_or_respond", self.generate_query_or_respond)
        if self.retriever_tool:
            workflow.add_node("retrieve", ToolNode([self.retriever_tool]))
        workflow.add_node("rewrite_question", self.rewrite_question)
        workflow.add_node("generate_answer", self.generate_answer)
        
        # ========== Routing Node ==========
        workflow.add_node("route_initial_query", self.route_initial_query_node)
        
        # ========== Direct Response ==========
        def direct_response(state: MessagesState):
            """Direct response without tools."""
            korean_prompt = {
                "role": "system",
                "content": "You are a helpful assistant. Always respond in Korean (한국어) in a natural, conversational style."
            }
            messages_with_prompt = [korean_prompt] + state["messages"]
            response = self.model.invoke(messages_with_prompt)
            return {"messages": [response]}
        
        workflow.add_node("direct_response", direct_response)
        
        # ========== Edges ==========
        workflow.add_edge(START, "route_initial_query")
        
        # Route to SQL or RAG workflow
        workflow.add_conditional_edges(
            "route_initial_query",
            self.route_initial_query_condition,
            {
                "sql_workflow": "list_tables",
                "rag_workflow": "generate_query_or_respond",
                "direct_response": "direct_response",
            },
        )
        
        # SQL workflow edges (following Custom SQL Agent pattern)
        workflow.add_edge("list_tables", "call_get_schema")
        workflow.add_edge("call_get_schema", "get_schema")
        workflow.add_edge("get_schema", "generate_query")
        workflow.add_conditional_edges(
            "generate_query",
            self.should_continue_sql,
            {
                "check_query": "check_query",
                END: END,
            },
        )
        workflow.add_edge("check_query", "run_query")
        
        # run_query 후 조건부로 generate_query 또는 END (무한 루프 방지)
        def should_retry_after_query(state: MessagesState) -> Literal[END, "generate_query"]:
            """쿼리 실행 후 재시도 여부 결정 - 무한 루프 방지"""
            messages = state["messages"]
            
            # 최근 메시지에서 에러 확인
            for msg in reversed(messages[-3:]):
                if hasattr(msg, 'content') and msg.content:
                    content = str(msg.content).lower()
                    if 'error' in content or 'syntax error' in content or 'operationalerror' in content:
                        logger.warning("Query execution error detected, ending workflow")
                        return END
                    # 스키마 정보가 결과로 나온 경우 (PRAGMA 등) - 재시도하지 않고 종료
                    if 'table_info' in content or 'pragma' in content or ('delivery_id' in content and 'integer' in content and 'varchar' in content):
                        logger.warning("Schema inspection query detected in results, ending workflow")
                        return END
            
            # 메시지가 너무 많으면 중단
            if len(messages) > 15:
                logger.warning("Too many messages, ending workflow to prevent infinite loop")
                return END
            
            # tool_calls가 있으면 재시도, 없으면 종료
            last_message = messages[-1]
            if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                return "generate_query"
            return END
        
        workflow.add_conditional_edges(
            "run_query",
            should_retry_after_query,
            {
                "generate_query": "generate_query",
                END: END,
            },
        )
        
        # RAG workflow edges (following Custom RAG Agent pattern)
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
                self.grade_documents,
            )
            workflow.add_edge("rewrite_question", "generate_query_or_respond")
        
        workflow.add_edge("generate_answer", END)
        workflow.add_edge("direct_response", END)
        
        return workflow.compile()
    
    def invoke(self, query: str, config: dict = None):
        """Invoke the agent with a query."""
        config = config or {}
        result = self.graph.invoke(
            {"messages": [{"role": "user", "content": query}]},
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
