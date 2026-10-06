const quickButtons = document.querySelectorAll('.quick-chip');
const chatForm = document.getElementById('chatForm');
const userInput = document.getElementById('userInput');
const chatMessages = document.getElementById('chatMessages');
const errorAlert = document.getElementById('errorAlert');

// Generate or retrieve session ID
const sessionId = localStorage.getItem('carebot_session_id') || `carebot-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
localStorage.setItem('carebot_session_id', sessionId);

console.log('✅ CareBot Initialized');
console.log('Session ID:', sessionId);

// Markdown to HTML converter with improved table handling
function parseMarkdown(text) {
  let html = text;

  // Headers
  html = html.replace(/^### (.*?)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.*?)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.*?)$/gm, '<h1>$1</h1>');

  // Bold and italic
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__(.*?)__/g, '<strong>$1</strong>');
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  html = html.replace(/_(.*?)_/g, '<em>$1</em>');

  // Code blocks with triple backticks
  html = html.replace(/```[\s\S]*?```/g, (match) => {
    const code = match.replace(/```/g, '').trim();
    return `<pre><code>${escapeHtml(code)}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Process tables - improved handling
  html = html.replace(/(\|.+\|\s*\n(?:\|[-:\s|]+\|\s*\n)?(?:\|.+\|\s*\n)*)/g, (match) => {
    const rows = match.trim().split('\n').filter(row => row.trim());
    if (rows.length < 2) return match;

    let table = '<table class="markdown-table">';
    let isHeader = true;

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];

      // Skip separator rows (contain dashes)
      if (row.includes('---') || row.includes(':-') || row.includes('-:')) {
        continue;
      }

      const cells = row.split('|').filter(cell => cell.trim());

      if (cells.length > 0) {
        if (isHeader) {
          table += '<thead><tr>';
          cells.forEach(cell => {
            table += `<th>${cell.trim()}</th>`;
          });
          table += '</tr></thead>';
          isHeader = false;
        } else {
          if (!table.includes('<tbody>')) {
            table += '<tbody>';
          }
          table += '<tr>';
          cells.forEach(cell => {
            table += `<td>${cell.trim()}</td>`;
          });
          table += '</tr>';
        }
      }
    }

    if (table.includes('<tbody>')) {
      table += '</tbody>';
    }
    table += '</table>';
    return table;
  });

  // Lists with proper bullet points
  html = html.replace(/^\* (.*?)$/gm, '<li>$1</li>');
  html = html.replace(/^- (.*?)$/gm, '<li>$1</li>');

  // Wrap consecutive list items
  html = html.replace(/(<li>.*?<\/li>)(\n<li>)/g, '$1$2');
  html = html.replace(/(<li>.*?<\/li>)(?!.*?<li>)/s, (match, p1) => {
    // Only wrap if not already in a list
    if (!match.includes('</ul>') && !match.includes('</ol>')) {
      return '<ul>' + match.replace(/(<li>.*?<\/li>)/s, (item) => item) + '</ul>';
    }
    return match;
  });

  // Better list wrapping
  html = html.split('\n').map(line => {
    if (line.includes('<li>')) {
      return line;
    }
    return line;
  }).join('\n');

  // Wrap all consecutive li tags in ul
  html = html.replace(/(<li>(?:[^]*?)<\/li>(?:\n<li>(?:[^]*?)<\/li>)*)/g, (match) => {
    return '<ul>' + match + '</ul>';
  });

  html = html.replace(/<\/ul>\n<ul>/g, '');

  // Line breaks - convert double newlines to paragraphs
  html = html.replace(/\n\n+/g, '</p><p>');

  // Wrap in paragraphs but avoid wrapping tables, headers, lists
  let parts = html.split(/(?=<(?:table|h[1-6]|ul|ol|pre))|(?<=<\/(?:table|h[1-6]|ul|ol|pre)>)/);
  html = parts.map(part => {
    if (part.match(/^<(?:table|h[1-6]|ul|ol|pre|li)/)) {
      return part;
    }
    if (part.trim() && !part.match(/^<\/(?:table|h[1-6]|ul|ol|pre)>/)) {
      return '<p>' + part + '</p>';
    }
    return part;
  }).join('');

  // Clean up empty paragraphs
  html = html.replace(/<p><\/p>/g, '');
  html = html.replace(/<p>\s*<ul>/g, '<ul>');
  html = html.replace(/<\/ul>\s*<\/p>/g, '</ul>');
  html = html.replace(/<p>\s*<table>/g, '<table>');
  html = html.replace(/<\/table>\s*<\/p>/g, '</table>');
  html = html.replace(/<p>\s*<pre>/g, '<pre>');
  html = html.replace(/<\/pre>\s*<\/p>/g, '</pre>');
  html = html.replace(/<p>\s*<h/g, '<h');
  html = html.replace(/<\/h[1-6]>\s*<\/p>/g, '</h$1>');

  return html;
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return text.replace(/[&<>"']/g, m => map[m]);
}

function showError(message) {
  errorAlert.textContent = message;
  errorAlert.style.display = 'block';
  setTimeout(() => {
    errorAlert.style.display = 'none';
  }, 6000);
}

function addMessage(role, text) {
  const row = document.createElement('div');
  row.className = `message-row ${role}`;

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';

  if (role === 'assistant') {
    // Parse markdown for assistant messages
    bubble.innerHTML = parseMarkdown(text);
  } else {
    // Plain text for user messages
    bubble.textContent = text;
  }

  row.appendChild(bubble);
  chatMessages.appendChild(row);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  console.log(`[${role.toUpperCase()}] Message added to chat`);
}

function setLoading(isLoading) {
  const input = document.getElementById('userInput');
  const button = document.querySelector('.send-btn');

  if (isLoading) {
    input.disabled = true;
    button.disabled = true;
    button.textContent = 'Thinking...';
    console.log('🔄 Loading state ON');
  } else {
    input.disabled = false;
    button.disabled = false;
    button.textContent = 'Send';
    console.log('✅ Loading state OFF');
  }
}

async function sendChatMessage(message) {
  try {
    console.log('📤 Sending message to server...');
    console.log('URL: /api/chat');
    console.log('Method: POST');
    console.log('Payload:', { message: message.substring(0, 50) + '...', session_id: sessionId });

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
      },
      body: JSON.stringify({
        message: message,
        session_id: sessionId,
      }),
    });

    console.log('📥 Response received');
    console.log('Status:', response.status);
    console.log('Content-Type:', response.headers.get('content-type'));

    // Check if response is JSON
    const contentType = response.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
      const text = await response.text();
      console.error('❌ Non-JSON response:', text.substring(0, 100));
      throw new Error(`Server returned non-JSON response: ${text.substring(0, 100)}`);
    }

    const data = await response.json();
    console.log('✅ JSON parsed successfully');
    console.log('Response data:', data);

    if (!response.ok) {
      throw new Error(data.error || `HTTP Error: ${response.status}`);
    }

    if (!data.reply) {
      throw new Error('No reply received from server');
    }

    console.log('✅ Reply validated');
    return data.reply;
  } catch (error) {
    console.error('❌ Error in sendChatMessage:', error);
    throw error;
  }
}

// Handle form submission
chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const text = userInput.value.trim();

  if (!text) {
    console.log('⚠️ Empty message, focusing input');
    userInput.focus();
    return;
  }

  console.log('📝 Form submitted');
  console.log('Message text:', text.substring(0, 50) + '...');

  // Add user message to chat
  addMessage('user', text);
  userInput.value = '';
  setLoading(true);
  errorAlert.style.display = 'none';

  try {
    const reply = await sendChatMessage(text);
    console.log('🤖 Adding assistant reply to chat');
    addMessage('assistant', reply);
  } catch (error) {
    console.error('💥 Chat error:', error.message);
    const errorMsg = `Sorry, error: ${error.message}. Try again in a moment.`;
    showError(errorMsg);
    addMessage('assistant', 'I encountered an error. Please try your message again.');
  } finally {
    setLoading(false);
    userInput.focus();
  }
});

// Quick chip button handlers
quickButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const chipText = button.textContent.trim();
    console.log('🔘 Quick chip clicked:', chipText);
    userInput.value = chipText;
    userInput.focus();
  });
});

// Auto-focus on input when page loads
window.addEventListener('load', () => {
  console.log('📄 Page loaded, setting focus to input');
  userInput.focus();

  // Test API health
  fetch('/api/health')
    .then(r => r.json())
    .then(data => {
      console.log('✅ API Health Check OK:', data);
    })
    .catch(err => {
      console.error('❌ API Health Check Failed:', err);
    });
});
