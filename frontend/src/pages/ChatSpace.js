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
          <input type="text" id="chat-input" class="input-field" placeholder="Enter your instructions for the agents..." autocomplete="off" />
          <button class="btn-primary" id="chat-send" style="padding: 0.5rem 1.5rem;">
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
      <div class="chat-message ${msg.sender} reveal" data-delay="${idx * 0.1}s">
        <span style="font-size: 0.7rem; color: var(--text-muted); padding: 0 0.5rem;">
          ${msg.sender === 'agent' ? 'RISHI Orchestrator' : 'You'}
        </span>
        <div class="chat-bubble">
          ${msg.text}
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

      // Mock agent reply for now
      setTimeout(() => {
        this.messages.push({ sender: 'agent', text: 'Initializing Chanakya Agents... <ul><li>Phase 1: Math and Ledger analysis starting.</li></ul>' });
        history.innerHTML = this.renderMessages();
        history.scrollTop = history.scrollHeight;
        initScrollReveals();
      }, 1000);
      
      initScrollReveals();
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
