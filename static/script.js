// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const userInput = document.getElementById('userInput');
const sendButton = document.getElementById('sendButton');
const loading = document.getElementById('loading');

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
    
    // Show loading
    showLoading();
    
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
        
        // Add bot response
        addMessage(data.response || '죄송합니다. 답변을 생성하는 중 오류가 발생했습니다.', 'bot');
        
    } catch (error) {
        console.error('Error:', error);
        addMessage('죄송합니다. 서버와의 통신 중 오류가 발생했습니다. 다시 시도해주세요.', 'bot');
    } finally {
        // Re-enable input
        userInput.disabled = false;
        sendButton.disabled = false;
        hideLoading();
        userInput.focus();
    }
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
}

// Get current time
function getCurrentTime() {
    const now = new Date();
    return now.toLocaleTimeString('ko-KR', { 
        hour: '2-digit', 
        minute: '2-digit' 
    });
}

// Show loading indicator
function showLoading() {
    loading.style.display = 'flex';
}

// Hide loading indicator
function hideLoading() {
    loading.style.display = 'none';
}

