"""
FastAPI 웹 애플리케이션 - 물류 데이터 분석 에이전트
"""
import sys
# 바이트코드(.pyc) 파일 생성 방지
sys.dont_write_bytecode = True

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from src.logistics_agent import LogisticsAgent
from scripts.create_sample_db import create_sample_database
from scripts.index_documents import load_documents, create_vector_store
from src.config import DATABASE_URI

app = FastAPI(title="물류 데이터 분석 에이전트")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 서빙
app.mount("/static", StaticFiles(directory="static"), name="static")

# 전역 에이전트 인스턴스
agent = None

# 대화 세션 관리 (간단하게 하나의 세션으로 관리, 필요시 세션별로 확장 가능)
# 실제 프로덕션에서는 세션 ID나 사용자 ID를 사용하여 thread_id를 관리해야 합니다
DEFAULT_THREAD_ID = "main_session"


def initialize_agent():
    """에이전트 초기화"""
    global agent
    
    # 데이터베이스는 이미 생성/마이그레이션 되어 있다고 가정합니다.
    # PostgreSQL의 경우 별도로 데이터베이스를 생성해야 합니다.
    
    # RAG 문서 로드 (선택사항)
    vector_store = None
    documents = load_documents()
    if documents:
        print(f"문서 {len(documents)}개를 로드했습니다.")
        vector_store = create_vector_store(documents)
    
    # 에이전트 초기화
    agent = LogisticsAgent(
        db_uri=DATABASE_URI,
        vector_store=vector_store,
    )
    print("에이전트가 초기화되었습니다.")


# 요청 모델
class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    needs_user_response: bool = False  # HITL: 사용자 응답이 필요한지 여부
    workflow_paused: bool = False  # 워크플로우가 일시 정지되었는지 여부


# 시작 시 에이전트 초기화
@app.on_event("startup")
async def startup_event():
    print("=" * 60)
    print("물류 데이터 분석 에이전트 웹 애플리케이션 시작")
    print("=" * 60)
    initialize_agent()


@app.get("/", response_class=HTMLResponse)
async def index():
    """메인 페이지"""
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """채팅 API 엔드포인트 - 기업 환경 고려"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        message = request.message
        
        # 입력 검증
        if not message:
            raise HTTPException(status_code=400, detail="메시지가 없습니다.")
        
        if len(message) > 2000:  # 메시지 길이 제한
            raise HTTPException(status_code=400, detail="메시지가 너무 깁니다. 2000자 이하로 입력해주세요.")
        
        if agent is None:
            logger.error("Agent not initialized")
            raise HTTPException(status_code=500, detail="에이전트가 초기화되지 않았습니다.")
        
        # 사용자 요청 로깅 (기업 환경)
        logger.info(f"User query received: {message[:100]}...")
        
        # 에이전트 호출 (thread_id를 사용하여 대화 히스토리 유지)
        # LangGraph의 checkpointer가 thread_id별로 대화 히스토리를 자동으로 관리합니다
        result = agent.invoke(message, thread_id=DEFAULT_THREAD_ID)
        
        # 마지막 메시지에서 답변 추출
        needs_user_response = False
        workflow_paused = False
        
        if result and 'messages' in result:
            last_message = result['messages'][-1]
            if hasattr(last_message, 'content') and last_message.content:
                response_text = last_message.content
            else:
                logger.warning("Empty response from agent")
                response_text = "답변을 생성할 수 없습니다. 다시 시도해주세요."
            
            # HITL: 메타데이터에서 사용자 응답 필요 여부 확인
            if hasattr(last_message, 'metadata') and last_message.metadata:
                needs_user_response = last_message.metadata.get("needs_user_response", False)
                workflow_paused = last_message.metadata.get("workflow_paused", False)
        else:
            logger.warning("Invalid result structure from agent")
            response_text = "답변을 생성할 수 없습니다. 다시 시도해주세요."
        
        return ChatResponse(
            response=response_text,
            needs_user_response=needs_user_response,
            workflow_paused=workflow_paused
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        # 민감한 정보 노출 방지 - 기업 환경 고려
        error_detail = "요청 처리 중 오류가 발생했습니다. 관리자에게 문의해주세요."
        raise HTTPException(status_code=500, detail=error_detail)


@app.get("/api/health")
async def health():
    """헬스 체크"""
    return {
        'status': 'ok',
        'agent_initialized': agent is not None
    }

