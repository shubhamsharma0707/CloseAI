import './style.css';

// DOM Elements
const promptInput = document.getElementById('promptInput');
const submitBtn = document.getElementById('submitBtn');
const pipelineContainer = document.getElementById('pipelineContainer');
const escrowList = document.getElementById('escrowList');
const finalReport = document.getElementById('finalReport');

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
        <div class="escrow-status">ESCROW_LOCKED</div>
      </div>
      <div class="escrow-uuid">${uuid}</div>
      <div class="escrow-reason">
        Transaction amount (₹${amount}) exceeds CTR threshold. Enhanced Due Diligence required.
      </div>
      <div class="escrow-meta">
        <span>Trigger: AML_CTR_01</span>
        <span>Timestamp: ${new Date().toISOString()}</span>
      </div>
      <button class="btn-review">Unlock (L2 Forensic)</button>
    </div>
  `;
  
  if (escrowList.querySelector('.empty-ledger')) {
    escrowList.innerHTML = '';
  }
  escrowList.insertAdjacentHTML('afterbegin', html);
}

// Orchestrator Simulation
async function runOrchestration() {
  const prompt = promptInput.value.trim();
  if (!prompt) return;

  submitBtn.disabled = true;
  submitBtn.textContent = 'Executing...';
  
  // Parse numbers from prompt dynamically
  let amount = "0";
  // Match a number optionally followed by Cr, M, or L/Lakh
  const match = prompt.match(/(\d+(?:\.\d+)?)\s*(Cr|M|Lakh|L)?/i);
  if (match) {
    let num = parseFloat(match[1]);
    const suffix = match[2] ? match[2].toLowerCase() : "";
    
    if (suffix === 'cr') num *= 10000000;
    else if (suffix === 'm') num *= 1000000;
    else if (suffix === 'l' || suffix === 'lakh') num *= 100000;
    
    amount = Math.floor(num).toString();
  }
  
  if (amount === "0") amount = "25000000"; // fallback
  
  finalReport.classList.add('hidden');
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

  // Phase 3
  setNodeState('reporting', 'active');
  await wait(800);
  appendLog('reporting', 'Calculating GHG Protocol Scope 3 Carbon Footprint...');
  await wait(600);
  appendLog('reporting', 'Estimated Carbon: 12.50 metric tons.', 'log-success');
  appendLog('reporting', 'Generated Executive Summary Dashboard.');
  setNodeState('reporting', 'completed');
  
  // Calculate fake numbers for the dashboard
  const principal = parseFloat(amount);
  const tax = principal * 0.312; // ~31.2% effective
  const net = principal - tax;
  
  // Show Final Report
  finalReport.innerHTML = `
    <div class="report-header">
      <h2>Executive Summary</h2>
      <div class="report-badge">Clear to Execute</div>
    </div>
    <div class="report-grid">
      <div class="report-stat">
        <span class="report-stat-label">Initial Capital</span>
        <span class="report-stat-value">₹${principal.toLocaleString()}</span>
        <span class="report-stat-sub">Jurisdiction: India</span>
      </div>
      <div class="report-stat">
        <span class="report-stat-label">Tax Liability</span>
        <span class="report-stat-value">₹${tax.toLocaleString()}</span>
        <span class="report-stat-sub">Hash: a8b2...f9e4</span>
      </div>
      <div class="report-stat">
        <span class="report-stat-label">Net Remaining</span>
        <span class="report-stat-value" style="color: var(--accent-green)">₹${net.toLocaleString()}</span>
      </div>
      <div class="report-stat">
        <span class="report-stat-label">ESG Footprint</span>
        <span class="report-stat-value">${(principal * 0.0000005).toFixed(2)} Tons</span>
        <span class="report-stat-sub">Scope 3 Category 15</span>
      </div>
    </div>
  `;
  finalReport.classList.remove('hidden');

  submitBtn.disabled = false;
  submitBtn.textContent = 'Execute';
}

submitBtn.addEventListener('click', runOrchestration);

// Init
renderPipeline();
