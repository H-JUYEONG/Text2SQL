"""
Index documents for RAG system.
This script loads logistics-related documents, splits them, and indexes them into a vector store.
"""
import sys
sys.dont_write_bytecode = True

import os
from pathlib import Path
from langchain_community.document_loaders import (
    DirectoryLoader,
    TextLoader,
    PyPDFLoader,
    CSVLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from src.config import (
    EMBEDDINGS_MODEL,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    OPENAI_API_KEY,
)

# Set API key
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY


def load_documents(data_dir: str = "data"):
    """Load documents from the data directory."""
    data_path = Path(data_dir)
    
    if not data_path.exists():
        print(f"Data directory '{data_dir}' not found. Creating it...")
        data_path.mkdir(exist_ok=True)
        print(f"Please add your logistics documents to '{data_dir}' directory.")
        return []
    
    documents = []
    
    # Load text files
    if (data_path / "txt").exists():
        loader = DirectoryLoader(
            str(data_path / "txt"),
            glob="**/*.txt",
            loader_cls=TextLoader,
        )
        documents.extend(loader.load())
    
    # Load PDF files
    if (data_path / "pdf").exists():
        loader = DirectoryLoader(
            str(data_path / "pdf"),
            glob="**/*.pdf",
            loader_cls=PyPDFLoader,
        )
        documents.extend(loader.load())
    
    # Load CSV files
    if (data_path / "csv").exists():
        loader = DirectoryLoader(
            str(data_path / "csv"),
            glob="**/*.csv",
            loader_cls=CSVLoader,
        )
        documents.extend(loader.load())
    
    return documents


def create_vector_store(documents, embeddings_model_name: str = None):
    """Create and populate a vector store with documents."""
    if not documents:
        print("No documents to index.")
        return None
    
    # Initialize embeddings
    embeddings = OpenAIEmbeddings(model=embeddings_model_name or EMBEDDINGS_MODEL)
    
    # Split documents
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
    )
    splits = text_splitter.split_documents(documents)
    
    print(f"Split {len(documents)} documents into {len(splits)} chunks.")
    
    # Create vector store
    vector_store = InMemoryVectorStore(embeddings)
    
    # Add documents to vector store
    vector_store.add_documents(splits)
    
    print(f"Indexed {len(splits)} document chunks into vector store.")
    
    return vector_store


def main():
    """Main function to index documents."""
    print("Loading documents...")
    documents = load_documents()
    
    if not documents:
        print("No documents found. Please add documents to the 'data' directory.")
        return None
    
    print(f"Loaded {len(documents)} documents.")
    
    print("Creating vector store...")
    vector_store = create_vector_store(documents)
    
    if vector_store:
        print("Document indexing completed successfully!")
        print("\nNote: InMemoryVectorStore is used, so the index exists only in memory.")
        print("For persistent storage, consider using Chroma, FAISS, or other vector stores.")
    
    return vector_store


if __name__ == "__main__":
    main()

