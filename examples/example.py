"""
Example usage of the Logistics Text2SQL + RAG Agent.
"""
import sys
sys.dont_write_bytecode = True

from src.logistics_agent import LogisticsAgent
from scripts.index_documents import create_vector_store, load_documents
from src.config import DATABASE_URI


def main():
    """Main example function."""
    print("=" * 60)
    print("Logistics Text2SQL + RAG Agent Example")
    print("=" * 60)
    
    # Try to load and index documents for RAG
    print("\n1. Loading documents for RAG...")
    documents = load_documents()
    vector_store = None
    
    if documents:
        print(f"   Loaded {len(documents)} documents.")
        vector_store = create_vector_store(documents)
        print("   Vector store created successfully.")
    else:
        print("   No documents found. RAG will be disabled.")
        print("   Add documents to 'data/' directory to enable RAG.")
    
    # Initialize agent
    print("\n2. Initializing agent...")
    try:
        agent = LogisticsAgent(
            db_uri=DATABASE_URI,
            vector_store=vector_store,
        )
        print("   Agent initialized successfully.")
    except Exception as e:
        print(f"   Error initializing agent: {e}")
        print("   Make sure you have:")
        print("   - A valid database at the DATABASE_URI")
        print("   - API keys set in .env file")
        return
    
    # Example queries
    print("\n3. Running example queries...")
    print("-" * 60)
    
    queries = [
        "What tables are available in the database?",
        "Show me the schema of the shipments table",
    ]
    
    # Add RAG query if vector store is available
    if vector_store:
        queries.append("What is cross-docking in logistics?")
    
    for i, query in enumerate(queries, 1):
        print(f"\nQuery {i}: {query}")
        print("-" * 60)
        
        try:
            for chunk in agent.stream(query):
                for node, update in chunk.items():
                    if "messages" in update:
                        last_msg = update["messages"][-1]
                        if hasattr(last_msg, "content") and last_msg.content:
                            print(f"[{node}] {last_msg.content}")
                        elif hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            tool_names = [tc["name"] for tc in last_msg.tool_calls]
                            print(f"[{node}] Calling tools: {', '.join(tool_names)}")
        except Exception as e:
            print(f"Error: {e}")
        
        print()
    
    print("=" * 60)
    print("Example completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()

