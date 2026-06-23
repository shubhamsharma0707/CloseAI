import { initScrollReveals } from '../utils/animations.js';

export class ChatSpace {
  constructor(container) {
    this.container = container;
    this.messages = [
      { sender: 'agent', text: 'Hello! I am the RISHI Node Orchestrator. Provide your financial intent or prompt, and I will dispatch the Chanakya agents to process it.' }
    ];
    this.render();
  }

  render() {
    this.container.innerHTML = `
      <div class="chat-container" style="animation: fadeIn 0.6s ease both;">
        <div class="chat-history" id="chat-history">
          ${this.renderMessages()}
        </div>
        
        <div class="chat-input-area" style="animation: fadeSlideUp 0.6s ease 0.2s both;">
          <input type="text" id="chat-input" class="input-field" placeholder="Message RISHI Orchestrator..." autocomplete="off" />
          <button class="btn-primary" id="chat-send" style="padding: 0.5rem 1.5rem; border-radius: 8px;">
            Send
          </button>
        </div>
      </div>
    `;

    this.bindEvents();
    setTimeout(() => initScrollReveals(), 50);
  }

  renderMessages() {
    return this.messages.map((msg, idx) => `
      <div class="chat-message ${msg.sender} reveal is-visible">
        ${msg.sender === 'agent' ? `
          <div class="chat-avatar bot-avatar">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a2 2 0 0 1 2 2c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2zm0 14a2 2 0 0 1 2 2c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2zM4.93 4.93a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83 2 2 0 0 1-2.83-2.83zm11.31 11.31a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83 2 2 0 0 1-2.83-2.83zM2 12a2 2 0 0 1 2-2c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2zm16 0a2 2 0 0 1 2-2c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2zM4.93 19.07a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0 2 2 0 0 1-2.83 2.83zm11.31-11.31a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0 2 2 0 0 1-2.83 2.83z"/></svg>
          </div>
        ` : ''}
        <div class="chat-content-wrapper">
          <div class="chat-sender-name">
            ${msg.sender === 'agent' ? 'RISHI Orchestrator' : 'You'}
          </div>
          <div class="chat-bubble">
            ${msg.text.replace(/\n/g, '<br>')}
          </div>
        </div>
      </div>
    `).join('');
  }

  bindEvents() {
    const btn = document.getElementById('chat-send');
    const input = document.getElementById('chat-input');

    const sendMessage = () => {
      const text = input.value.trim();
      if (!text) return;
      
      this.messages.push({ sender: 'user', text });
      input.value = '';
      
      // Re-render chat
      const history = document.getElementById('chat-history');
      history.innerHTML = this.renderMessages();
      history.scrollTop = history.scrollHeight;

      // Disable input while typing
      input.disabled = true;
      btn.disabled = true;

      // Mock agent streaming reply like GPT/Claude
      setTimeout(() => {
        const fullText = "Initializing Chanakya Agents...\n\nPhase 1: Math and Ledger analysis starting.\nPhase 2: Verifying financial data structures...\nPhase 3: Ready for final execution and orchestration.";
        const words = fullText.split(' ');
        
        const agentMsg = { sender: 'agent', text: '' };
        this.messages.push(agentMsg);
        
        let i = 0;
        const typingInterval = setInterval(() => {
          agentMsg.text += (i === 0 ? '' : ' ') + words[i];
          history.innerHTML = this.renderMessages();
          history.scrollTop = history.scrollHeight;
          i++;
          
          if (i === words.length) {
            clearInterval(typingInterval);
            input.disabled = false;
            btn.disabled = false;
            input.focus();
            initScrollReveals();
          }
        }, 50);
      }, 400);
    };

    btn.addEventListener('click', sendMessage);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sendMessage();
    });
  }

  destroy() {
    // cleanup if needed
  }
}
