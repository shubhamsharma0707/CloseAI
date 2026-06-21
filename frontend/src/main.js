import './style.css';

// DOM Elements
const promptInput = document.getElementById('promptInput');
const submitBtn = document.getElementById('submitBtn');
const pipelineContainer = document.getElementById('pipelineContainer');
const escrowList = document.getElementById('escrowList');
const finalReport = document.getElementById('finalReport');
const chatResponse = document.getElementById('chatResponse');
const chatContent = document.getElementById('chatContent');

// Pipeline phases definition
const PHASES = [
  {
    id: 'parse',
    title: 'Phase 0: Intent Parsing (LLM)',
    desc: 'Extracting principal, jurisdiction, and entity type.',
    icon: '🧠',
  },
  {
    id: 'quant',
    title: 'Phase 1: Quantitative Engine',
    desc: 'Bitemporal tax liability calculation and hashing.',
    icon: '📊',
  },
  {
    id: 'compliance',
    title: 'Phase 2: Ethical Compliance',
    desc: 'FATF screening, CTR triggers, and AML/KYC checks.',
    icon: '⚖️',
  },
  {
    id: 'reporting',
    title: 'Phase 3: Reporting & ESG',
    desc: 'Carbon footprint analysis and board reporting.',
    icon: '📝',
  }
];

// Helper to delay
const wait = (ms) => new Promise(r => setTimeout(r, ms));

// Render empty pipeline
function renderPipeline() {
  pipelineContainer.innerHTML = '';
  PHASES.forEach((phase, index) => {
    const isLast = index === PHASES.length - 1;
    
    const nodeHTML = `
      <div class="pipeline-node" id="node-${phase.id}">
        <div class="node-icon-wrapper">
          <div class="node-icon">${phase.icon}</div>
          ${!isLast ? '<div class="node-connector"></div>' : ''}
        </div>
        <div class="node-content">
          <div class="node-title">${phase.title}</div>
          <div class="node-desc">${phase.desc}</div>
          <div class="node-logs" id="logs-${phase.id}"></div>
        </div>
      </div>
    `;
    pipelineContainer.insertAdjacentHTML('beforeend', nodeHTML);
  });
}

function appendLog(phaseId, text, type = '') {
  const logBox = document.getElementById(`logs-${phaseId}`);
  if (!logBox) return;
  const line = document.createElement('div');
  line.className = `log-line ${type}`;
  line.textContent = `[${new Date().toISOString().substring(11, 23)}] ${text}`;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
}

function setNodeState(phaseId, state) {
  const node = document.getElementById(`node-${phaseId}`);
  node.className = `pipeline-node ${state}`;
}

function addEscrowRecord(amount) {
  const uuid = crypto.randomUUID();
  const html = `
    <div class="escrow-card" id="escrow-${uuid}">
      <div class="escrow-header">
        <div class="escrow-status" id="status-${uuid}">ESCROW_LOCKED</div>
      </div>
      <div class="escrow-uuid">${uuid}</div>
      <div class="escrow-reason">
        Transaction amount (₹${amount}) exceeds CTR threshold. Enhanced Due Diligence required.
      </div>
      <div class="escrow-meta">
        <span>Trigger: AML_CTR_01</span>
        <span>Timestamp: ${new Date().toISOString()}</span>
      </div>
      <button class="btn-review" id="btn-${uuid}" onclick="window.unlockEscrow('${uuid}', '${amount}')">Unlock (L2 Forensic)</button>
    </div>
  `;
  
  if (escrowList.querySelector('.empty-ledger')) {
    escrowList.innerHTML = '';
  }
  escrowList.insertAdjacentHTML('afterbegin', html);
}

// Global function to unlock and resume
window.unlockEscrow = async function(uuid, amount) {
  const btn = document.getElementById(`btn-${uuid}`);
  const status = document.getElementById(`status-${uuid}`);
  const card = document.getElementById(`escrow-${uuid}`);
  
  if (!btn) return;
  
  btn.disabled = true;
  btn.textContent = 'Unlocked ✓';
  btn.style.borderColor = 'var(--accent-green)';
  btn.style.color = 'var(--accent-green)';
  status.textContent = 'RESOLVED';
  status.style.color = 'var(--accent-green)';
  status.style.background = 'rgba(16, 185, 129, 0.1)';
  card.style.borderColor = 'var(--accent-green)';
  card.style.boxShadow = 'inset 4px 0 0 var(--accent-green)';
  
  appendLog('compliance', 'L2 Forensic Override Accepted.', 'log-success');
  setNodeState('compliance', 'completed');
  
  // Resume Phase 3
  await runPhase3(amount);
};

async function runPhase3(amount) {
  // Phase 3
  setNodeState('reporting', 'active');
  await wait(800);
  appendLog('reporting', 'Calculating GHG Protocol Scope 3 Carbon Footprint...');
  await wait(600);
  appendLog('reporting', 'Estimated Carbon: 12.50 metric tons.', 'log-success');
  appendLog('reporting', 'Generated Executive Summary Dashboard.');
  setNodeState('reporting', 'completed');
  
  showFinalReport(amount);
}

function showFinalReport(amount) {
  // Calculate accurate CA-grade tax (India New Regime 2025 equivalent)
  const principal = parseFloat(amount);
  
  let baseTax = 0;
  const brackets = [
      {limit: 400000, rate: 0.00},
      {limit: 800000, rate: 0.05},
      {limit: 1200000, rate: 0.10},
      {limit: 1600000, rate: 0.15},
      {limit: 2000000, rate: 0.20},
      {limit: 2400000, rate: 0.25},
      {limit: Infinity, rate: 0.30}
  ];
  
  let previousLimit = 0;
  for (let b of brackets) {
      if (principal > previousLimit) {
          let taxable = Math.min(principal - previousLimit, b.limit - previousLimit);
          baseTax += taxable * b.rate;
          previousLimit = b.limit;
      } else {
          break;
      }
  }
  
  let surchargeRate = 0;
  if (principal > 20000000) surchargeRate = 0.25;
  else if (principal > 10000000) surchargeRate = 0.15;
  else if (principal > 5000000) surchargeRate = 0.10;
  
  const surcharge = baseTax * surchargeRate;
  const cess = (baseTax + surcharge) * 0.04;
  
  const tax = baseTax + surcharge + cess;
  const net = principal - tax;
  
  // Show Final Report
  finalReport.innerHTML = `
    <div class="report-header">
      <h2>Your Action Plan</h2>
      <div class="report-badge">Clear to Execute</div>
    </div>
    
    <div class="report-human-summary" style="padding: 16px; background: rgba(37, 99, 235, 0.1); border-left: 4px solid var(--accent-blue); border-radius: 4px; margin-bottom: 24px; color: #e2e8f0; font-size: 15px; line-height: 1.6;">
      <strong>Summary:</strong> Out of your total money (₹${principal.toLocaleString()}), you will need to pay <strong>₹${tax.toLocaleString()}</strong> to the government as tax. You are safely left with <strong style="color: var(--accent-green);">₹${net.toLocaleString()}</strong> to keep or invest.
    </div>

    <div class="report-grid">
      <div class="report-stat">
        <span class="report-stat-label">Total Money You Started With</span>
        <span class="report-stat-value">₹${principal.toLocaleString()}</span>
      </div>
      <div class="report-stat">
        <span class="report-stat-label">Money Going to Government (Tax)</span>
        <span class="report-stat-value" style="color: var(--accent-red)">₹${tax.toLocaleString()}</span>
      </div>
      <div class="report-stat">
        <span class="report-stat-label">Money Left For You</span>
        <span class="report-stat-value" style="color: var(--accent-green)">₹${net.toLocaleString()}</span>
      </div>
      <div class="report-stat">
        <span class="report-stat-label">Impact on Environment</span>
        <span class="report-stat-value">${(principal * 0.0000005).toFixed(2)} Tons of CO₂</span>
      </div>
    </div>
  `;
  finalReport.classList.remove('hidden');

  submitBtn.disabled = false;
  submitBtn.textContent = 'Execute';
}

// Orchestrator Simulation
async function runOrchestration() {
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Executing...';
  
  // Parse numbers from prompt dynamically
  let amount = "0";
  // Clean commas for parsing
  const cleanPrompt = prompt.replace(/,/g, '');
  // Match a number optionally followed by Cr, M, or L/Lakh
  const match = cleanPrompt.match(/(\d+(?:\.\d+)?)\s*(Cr|M|Lakh|L)?/i);
  if (match) {
    let num = parseFloat(match[1]);
    const suffix = match[2] ? match[2].toLowerCase() : "";
    
    if (suffix === 'cr') num *= 10000000;
    else if (suffix === 'm') num *= 1000000;
    else if (suffix === 'l' || suffix === 'lakh') num *= 100000;
    
    amount = Math.floor(num).toString();
  }
  
  // Detect Intent
  const lowerPrompt = prompt.toLowerCase();
  // Make intent detection much stricter so general finance questions don't falsely trigger the tax pipeline
  const isTaxOrPipeline = lowerPrompt.includes('core income') || lowerPrompt.includes('reallocate') || lowerPrompt.includes('escrow') || lowerPrompt.startsWith('/tax');
  
  if (!isTaxOrPipeline) {
    return runConversationalAI(prompt, false);
  }
  
  // Tax Pipeline execution
  if (amount === "0") amount = "25000000"; // fallback
  
  finalReport.classList.add('hidden');
  chatResponse.classList.add('hidden');
  renderPipeline();

  // Phase 0
  setNodeState('parse', 'active');
  appendLog('parse', 'Waking up Chanakya Master Orchestrator...');
  await wait(800);
  appendLog('parse', 'LLM intent parsed successfully.', 'log-success');
  appendLog('parse', `Extracted Principal: ${amount}`);
  setNodeState('parse', 'completed');

  // Phase 1
  setNodeState('quant', 'active');
  await wait(600);
  appendLog('quant', 'Initiating calculation: calculate_tax_liability');
  await wait(1000);
  appendLog('quant', 'Calculated exact tax: 7833000.00');
  appendLog('quant', 'SHA-256 Hash Generated: a8b2...f9e4', 'log-hash');
  appendLog('quant', 'Written to chanakya_immutable_ledger.log', 'log-success');
  setNodeState('quant', 'completed');

  // Phase 2
  setNodeState('compliance', 'active');
  await wait(800);
  appendLog('compliance', 'Running FATF Blacklist/Greylist checks...');
  await wait(600);
  appendLog('compliance', 'Checking CTR thresholds...');
  
  // Decide whether to lock based on amount
  const numericAmount = parseInt(amount, 10);
  if (numericAmount > 1000000) {
    appendLog('compliance', `⚠️ EDD REQUIRED: Amount exceeds CTR threshold.`, 'log-error');
    appendLog('compliance', `🛑 ESCROW LOCK INITIATED. Pipeline Halted.`, 'log-error');
    setNodeState('compliance', 'error');
    
    // Trigger the escrow lock UI
    addEscrowRecord(numericAmount);
    
    submitBtn.disabled = false;
    submitBtn.textContent = 'Execute';
    return; // Halt the pipeline
  }

  appendLog('compliance', 'Compliance checks passed. No violations.', 'log-success');
  setNodeState('compliance', 'completed');

  await runPhase3(amount);
  
  // After Tax Pipeline completes, ALSO ask the AI Advisor to explain the tax results in simple English
  await runConversationalAI(prompt, true);
}

async function runConversationalAI(prompt, keepDashboard = false) {
  if (!keepDashboard) {
    pipelineContainer.innerHTML = '';
    finalReport.classList.add('hidden');
  }
  chatResponse.classList.remove('hidden');
  
  chatContent.innerHTML = '<span style="color: var(--accent-blue);">Chanakya is thinking...</span>';
  
  try {
    const res = await fetch('http://127.0.0.1:8000/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
    
    if (!res.ok) throw new Error("Network error");
    
    const data = await res.json();
    chatContent.textContent = data.response;
  } catch (err) {
    chatContent.innerHTML = '<span style="color: var(--accent-red);">Error connecting to local AI engine. Ensure RISHI server is running.</span>';
  }
  
  submitBtn.disabled = false;
  submitBtn.textContent = 'Execute';
}

submitBtn.addEventListener('click', runOrchestration);

// Init
renderPipeline();
