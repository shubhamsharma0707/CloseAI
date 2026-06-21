import { animateCounter, initScrollReveals } from '../utils/animations.js';

export class Dashboard {
  constructor(container) {
    this.container = container;
    this.interval = null;
    this.render();
  }

  render() {
    this.container.innerHTML = `
      <div class="section" style="padding-top: calc(var(--nav-h) + 3rem);">
        <h1 class="section-title" style="animation: fadeSlideUp 0.8s ease 0.1s both; margin-bottom: 2rem;">
          CloseAI Dashboard
        </h1>

        <div class="metrics-banner" style="animation: fadeIn 0.8s ease 0.3s both; margin-bottom: 3rem;">
          <div class="stat-grid">
            <div class="stat-card reveal" data-delay="0.1s">
              <div class="stat-value"><span id="dash-ram">0</span>%</div>
              <div class="stat-label">RAM Usage</div>
            </div>
            <div class="stat-card reveal" data-delay="0.2s">
              <div class="stat-value"><span id="dash-sessions">0</span></div>
              <div class="stat-label">Active Sessions</div>
            </div>
            <div class="stat-card reveal" data-delay="0.3s">
              <div class="stat-value"><span id="dash-agents">8</span></div>
              <div class="stat-label">Registered Agents</div>
            </div>
            <div class="stat-card reveal" data-delay="0.4s">
              <div class="stat-value"><span id="dash-blackboard">0</span></div>
              <div class="stat-label">Blackboard Entries</div>
            </div>
          </div>
        </div>

        <h3 style="font-family: 'Outfit'; font-size: 1.5rem; margin-bottom: 1.5rem; animation: fadeIn 0.8s ease 0.5s both;">Chanakya Agents Overview</h3>
        <div class="features-grid" style="animation: fadeIn 0.8s ease 0.6s both;">
          
          <div class="feature-card reveal" data-delay="0.1s">
            <div class="feature-title">Phase 1: Quantitative</div>
            <div class="feature-desc">
              <ul style="list-style: none; display: flex; flex-direction: column; gap: 0.5rem; margin-top: 1rem;">
                <li class="policy-card neutral" style="padding: 0.75rem 1rem;">
                  <strong style="color: var(--text-primary); font-size: 0.85rem;">Deterministic Agent</strong>
                  <div style="font-size: 0.75rem; margin-top: 4px;">Math modeling & logic</div>
                </li>
                <li class="policy-card neutral" style="padding: 0.75rem 1rem;">
                  <strong style="color: var(--text-primary); font-size: 0.85rem;">Auditability Agent</strong>
                  <div style="font-size: 0.75rem; margin-top: 4px;">Hash integrity & ledger</div>
                </li>
              </ul>
            </div>
          </div>

          <div class="feature-card reveal" data-delay="0.2s">
            <div class="feature-title">Phase 2: Qualitative</div>
            <div class="feature-desc">
              <ul style="list-style: none; display: flex; flex-direction: column; gap: 0.5rem; margin-top: 1rem;">
                <li class="policy-card neutral" style="padding: 0.75rem 1rem;">
                  <strong style="color: var(--text-primary); font-size: 0.85rem;">Ethical Compliance</strong>
                  <div style="font-size: 0.75rem; margin-top: 4px;">ESG & legal validation</div>
                </li>
                <li class="policy-card neutral" style="padding: 0.75rem 1rem;">
                  <strong style="color: var(--text-primary); font-size: 0.85rem;">Critical Scenario</strong>
                  <div style="font-size: 0.75rem; margin-top: 4px;">Stress & edge cases</div>
                </li>
              </ul>
            </div>
          </div>

          <div class="feature-card reveal" data-delay="0.3s">
            <div class="feature-title">Phase 3: Output</div>
            <div class="feature-desc">
              <ul style="list-style: none; display: flex; flex-direction: column; gap: 0.5rem; margin-top: 1rem;">
                <li class="policy-card neutral" style="padding: 0.75rem 1rem;">
                  <strong style="color: var(--text-primary); font-size: 0.85rem;">Communication Agent</strong>
                  <div style="font-size: 0.75rem; margin-top: 4px;">Executive summaries</div>
                </li>
                <li class="policy-card neutral" style="padding: 0.75rem 1rem;">
                  <strong style="color: var(--text-primary); font-size: 0.85rem;">Visualization Agent</strong>
                  <div style="font-size: 0.75rem; margin-top: 4px;">Visual metrics</div>
                </li>
              </ul>
            </div>
          </div>

        </div>
      </div>
    `;

    setTimeout(() => initScrollReveals(), 100);
    this.fetchHealth();
    this.interval = setInterval(() => this.fetchHealth(), 5000);
  }

  async fetchHealth() {
    try {
      const res = await fetch('http://127.0.0.1:8000/health');
      if (!res.ok) throw new Error('Network error');
      const data = await res.json();
      
      const elRam = document.getElementById('dash-ram');
      const elSessions = document.getElementById('dash-sessions');
      const elAgents = document.getElementById('dash-agents');
      const elBb = document.getElementById('dash-blackboard');

      if (elRam) animateCounter(elRam, data.ram_percent, 1, 1000);
      if (elSessions) animateCounter(elSessions, data.active_sessions, 0, 1000);
      if (elAgents) animateCounter(elAgents, data.registered_agent_count, 0, 1000);
      if (elBb) animateCounter(elBb, data.blackboard_entry_count, 0, 1000);

      // Change RAM badge color based on threshold
      if (elRam && data.ram_percent > data.ram_critical_threshold) {
        elRam.parentElement.style.color = 'var(--red)';
      } else if (elRam) {
        elRam.parentElement.style.color = 'var(--text-primary)';
      }

    } catch (err) {
      console.warn('Failed to fetch health data:', err);
    }
  }

  destroy() {
    if (this.interval) clearInterval(this.interval);
  }
}
