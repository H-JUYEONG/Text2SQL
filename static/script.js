// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const userInput = document.getElementById('userInput');
const sendButton = document.getElementById('sendButton');

// Admin key (no-login): save once in browser and send as header automatically.
const adminKeyBtn = document.getElementById('adminKeyBtn');
const adminKeyStatus = document.getElementById('adminKeyStatus');
const ADMIN_KEY_STORAGE = 'text2sql_admin_key';

function getAdminKey() {
    try {
        return localStorage.getItem(ADMIN_KEY_STORAGE) || '';
    } catch (e) {
        return '';
    }
}

function setAdminKey(key) {
    try {
        if (key) localStorage.setItem(ADMIN_KEY_STORAGE, key);
        else localStorage.removeItem(ADMIN_KEY_STORAGE);
    } catch (e) {
        // ignore
    }
    renderAdminKeyStatus();
}

function renderAdminKeyStatus() {
    if (!adminKeyStatus) return;
    const key = getAdminKey();
    adminKeyStatus.textContent = key ? 'ADMIN: ON' : 'ADMIN: OFF';
}

function getAuthHeaders() {
    const key = getAdminKey();
    return key ? { 'X-ADMIN-KEY': key } : {};
}

// Set welcome message time
document.getElementById('welcomeTime').textContent = getCurrentTime();

// Auto-resize textarea
userInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

// Send message on Enter (Shift+Enter for new line)
userInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// Send button click
sendButton.addEventListener('click', sendMessage);

// Admin key button click (prompt once)
if (adminKeyBtn) {
    adminKeyBtn.addEventListener('click', () => {
        const current = getAdminKey();
        const input = window.prompt(
            '관리자 키를 입력하세요.\\n\\n- 설정 시: 스키마/테이블 명세 조회 권한이 활성화됩니다.\\n- 비우고 확인하면: 키가 제거됩니다.',
            current
        );
        if (input === null) return; // cancelled
        const key = (input || '').trim();
        setAdminKey(key);
        addMessage(key ? '[로컬 설정] 관리자 키가 설정되었습니다. 이제부터 요청에 X-ADMIN-KEY 헤더가 자동 포함됩니다.'
                       : '[로컬 설정] 관리자 키가 제거되었습니다.',
                   'bot');
    });
}
renderAdminKeyStatus();

// Get current time
function getCurrentTime() {
    const now = new Date();
    return now.toLocaleTimeString('ko-KR', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

// Add message to chat
function addMessage(text, type, needsUserResponse = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}-message`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = type === 'user' ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    // Convert markdown-style formatting to HTML
    let htmlText = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')  // **bold** -> <strong>
        .replace(/\*(.*?)\*/g, '<em>$1</em>')              // *italic* -> <em>
        .replace(/\n/g, '<br>');                             // newlines -> <br>
    messageText.innerHTML = htmlText;
    
    const messageTime = document.createElement('div');
    messageTime.className = 'message-time';
    messageTime.textContent = getCurrentTime();
    
    content.appendChild(messageText);
    
    // 쿼리 승인 요청인 경우 버튼 추가
    // 마커를 원본 텍스트와 HTML 변환 후 모두 체크
    // 또는 "SQL 쿼리 실행 승인 요청" 텍스트가 있고 "승인 방법" 텍스트가 없으면 버튼 표시
    const hasApprovalMarker = text.includes('<!-- QUERY_APPROVAL_BUTTONS -->') || 
                               text.includes('QUERY_APPROVAL_BUTTONS');
    
    const isApprovalRequest = type === 'bot' && 
                              text.includes('SQL 쿼리 실행 승인 요청') && 
                              text.includes('생성된 SQL 쿼리:') &&
                              !text.includes('승인 방법') && 
                              !text.includes('✅ 승인:') &&
                              !text.includes('❌ 거부:');
    
    if (hasApprovalMarker || isApprovalRequest) {
        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'approval-buttons';
        
        const approveButton = document.createElement('button');
        approveButton.className = 'approve-button';
        approveButton.textContent = '승인';
        approveButton.onclick = () => handleApproval('승인');
        
        const rejectButton = document.createElement('button');
        rejectButton.className = 'reject-button';
        rejectButton.textContent = '거부';
        rejectButton.onclick = () => handleRejection();
        
        buttonContainer.appendChild(approveButton);
        buttonContainer.appendChild(rejectButton);
        content.appendChild(buttonContainer);
        
        // 마커 제거 (원본 텍스트와 HTML 모두)
        messageText.innerHTML = messageText.innerHTML
            .replace(/<!--\s*QUERY_APPROVAL_BUTTONS\s*-->/gi, '')
            .replace(/QUERY_APPROVAL_BUTTONS/gi, '');
    }
    
    // 거부 피드백 요청인 경우 기존 입력창을 피드백 모드로 전환
    if (type === 'bot' && (text.includes('수정이 필요한 부분을 알려주시면') || text.includes('피드백을 받았습니다'))) {
        // 기존 입력창을 피드백 입력 모드로 전환
        userInput.placeholder = '피드백을 입력하세요 (예: 조건이 잘못됨, 컬럼이 틀림, JOIN이 필요함 등)';
        userInput.dataset.feedbackMode = 'true';
        userInput.focus();
    }
    
    content.appendChild(messageTime);
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    chatMessages.appendChild(messageDiv);
    
    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return messageDiv;
}

// Handle approval button click
async function handleApproval(action) {
    await sendApprovalMessage(action);
}

// Handle rejection button click
async function handleRejection() {
    // 거부 메시지 전송 (피드백 없이)
    // 서버에서 피드백 요청 메시지를 받으면 기존 입력창이 피드백 모드로 전환됨
    await sendApprovalMessage('거부');
}

// Handle feedback submit (더 이상 사용하지 않음 - 기존 입력창 사용)

// Send approval/rejection message
async function sendApprovalMessage(message) {
    // Disable input
    userInput.disabled = true;
    sendButton.disabled = true;
    
    // Add user message to chat
    addMessage(message, 'user');
    
    // Show loading message in chat
    const loadingMessageId = addLoadingMessage();
    
    try {
        // Call API
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...getAuthHeaders(),
            },
            body: JSON.stringify({ message: message })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Remove loading message and add bot response
        removeLoadingMessage(loadingMessageId);
        addMessage(data.response || '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.', 'bot', data.needs_user_response || false);
        
    } catch (error) {
        console.error('Error:', error);
        // Remove loading message and add error message
        removeLoadingMessage(loadingMessageId);
        addMessage('죄송합니다. 서버와의 통신 중 오류가 발생했습니다. 다시 시도해주세요.', 'bot');
    } finally {
        // Re-enable input
        userInput.disabled = false;
        sendButton.disabled = false;
        userInput.focus();
    }
}

// Add loading message to chat
function addLoadingMessage() {
    const messageDiv = document.createElement('div');
    const loadingId = 'loading-' + Date.now();
    messageDiv.id = loadingId;
    messageDiv.className = 'message bot-message';
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    messageText.innerHTML = '<div style="display: flex; align-items: center; gap: 8px;"><div style="width: 16px; height: 16px; border: 2px solid #f3f3f3; border-top: 2px solid #5ca8fe; border-radius: 50%; animation: spin 1s linear infinite;"></div><span>답변을 생성하고 있습니다...</span></div>';
    
    content.appendChild(messageText);
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    chatMessages.appendChild(messageDiv);
    
    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return loadingId;
}

// Remove loading message
function removeLoadingMessage(loadingId) {
    if (loadingId) {
        const loadingElement = document.getElementById(loadingId);
        if (loadingElement) {
            loadingElement.remove();
        }
    }
}

// Send message function
async function sendMessage() {
    const message = userInput.value.trim();
    
    if (!message) return;
    
    // 피드백 모드인지 확인
    const isFeedbackMode = userInput.dataset.feedbackMode === 'true';
    let messageToSend = message;
    
    // 피드백 모드인 경우 "거부: [피드백]" 형식으로 전송
    if (isFeedbackMode) {
        messageToSend = `거부: ${message}`;
    }
    
    // Disable input
    userInput.disabled = true;
    sendButton.disabled = true;
    
    // Add user message to chat (원본 메시지 표시)
    addMessage(message, 'user');
    
    // Clear input
    userInput.value = '';
    userInput.style.height = 'auto';
    
    // Show loading message in chat
    const loadingMessageId = addLoadingMessage();
    
    try {
        // Call API
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...getAuthHeaders(),
            },
            body: JSON.stringify({ message: messageToSend })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Remove loading message and add bot response
        removeLoadingMessage(loadingMessageId);
        addMessage(data.response || '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.', 'bot', data.needs_user_response || false);
        
        // 피드백 모드 해제 (응답 받은 후)
        if (isFeedbackMode) {
            userInput.dataset.feedbackMode = 'false';
            userInput.placeholder = '질문을 입력하세요.';
        }
        
    } catch (error) {
        console.error('Error:', error);
        // Remove loading message and add error message
        removeLoadingMessage(loadingMessageId);
        addMessage('죄송합니다. 서버와의 통신 중 오류가 발생했습니다. 다시 시도해주세요.', 'bot');
        
        // 에러 발생 시에도 피드백 모드 해제
        if (isFeedbackMode) {
            userInput.dataset.feedbackMode = 'false';
            userInput.placeholder = '질문을 입력하세요.';
        }
    } finally {
        // Re-enable input
        userInput.disabled = false;
        sendButton.disabled = false;
        userInput.focus();
    }
}
