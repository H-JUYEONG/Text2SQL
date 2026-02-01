// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const userInput = document.getElementById('userInput');
const sendButton = document.getElementById('sendButton');

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

// Get current time
function getCurrentTime() {
    const now = new Date();
    return now.toLocaleTimeString('ko-KR', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

// Add message to chat
function addMessage(text, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}-message`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = type === 'user' ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    messageText.textContent = text;
    
    const messageTime = document.createElement('div');
    messageTime.className = 'message-time';
    messageTime.textContent = getCurrentTime();
    
    content.appendChild(messageText);
    content.appendChild(messageTime);
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    chatMessages.appendChild(messageDiv);
    
    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return messageDiv;
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
    
    // Disable input
    userInput.disabled = true;
    sendButton.disabled = true;
    
    // Add user message to chat
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
            },
            body: JSON.stringify({ message: message })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Remove loading message and add bot response
        removeLoadingMessage(loadingMessageId);
        addMessage(data.response || '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.', 'bot');
        
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
