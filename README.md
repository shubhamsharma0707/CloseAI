# CloseAI — Multi-Agent AI Orchestration System

CloseAI is a secure, high-performance multi-agent framework designed to orchestrate suites of specialized AI agents. The platform translates natural language intents into highly structured, autonomous workflows using a centralized architecture managed by the **RISHI Core Node**. 

The system leverages **local LLMs (like Ollama llama3.1:8b)** to parse human intents securely and privately. It then delegates the work to dedicated agent teams that act as subject matter experts, enforcing strict rules, human-approval locks, and cryptographic auditing at each step.

Currently, the project features two primary Orchestrators:
1. **Chanakya** (The Chief Financial Officer): Handles quantitative finance, strategy, and ethical compliance.
2. **Kavach** (The Chief Information Security Officer): Handles ethical hacking, penetration testing, and continuous security monitoring.

---

## 🌟 Key Features

- **Centralized Blackboard Architecture**: Run on FastAPI (**RISHI**), allowing real-time SSE stream handshakes, safe concurrent memory updates, and strict memory limits.
- **Local LLM Intent Parsing**: Uses local `llama3.1:8b` to extract variables securely from unstructured human inputs, preventing sensitive data from leaving the local machine.
- **Strict Safe Agent Design**: Agents are sandboxed by their roles. High-risk actions (like simulated exploits or questionable financial moves) trigger **Human Approval Locks** and halt the workflow.
- **Cryptographic Audit Trails**: Real-time HMAC token comparison and state integrity hashing written to immutable ledger files.

---

## 🏛️ The Orchestrators

### 1. Chanakya (Financial Orchestrator)
Chanakya is an autonomous financial pipeline that processes monetary actions through 4 distinct phases:
- **Phase 1: Quantitative** - Mathematical modeling and tax liability calculations.
- **Phase 2: Qualitative** - Ethical compliance and edge-case stress testing.
- **Phase 3: Output** - Executive summaries, visualization dashboards, and ESG scoring.
- **Phase 4: Evolution** - Adaptability and regulatory research.

### 2. Kavach (Cybersecurity Orchestrator)
Kavach ("Shield") acts as a CISO, taking natural language targets (e.g., "Scan my portal for vulnerabilities") and executing a safe, ethical hacking workflow:
- **Phase 1: Reconnaissance** - Discovers subdomains, assets, and open ports.
- **Phase 2: Vulnerability Scanning** - Identifies weak configurations and exposed services.
- **Phase 3: Penetration Testing** - Exploits vulnerabilities safely (strictly gated by **Human Approval** for high-risk actions).
- **Phase 4: Reporting** - Compiles actionable JSON security reports.
- **Phase 5: Retesting** - Verifies if engineering patches have actually closed the security gap.

---

## 🔒 Security & Token Verification

To prevent unauthorized blackboard updates, every communication within the internal system requires a cryptographically-secure authorization header. 

1. **HMAC Protection**: The RISHI node performs token validation via `hmac.compare_digest()` to protect against timing attacks.
2. **Environment Compartmentalization**: Tokens are read from `.env` (which is never pushed to git).
3. **RAM Guardrails**: Built-in OS memory tracking to prevent host out-of-memory crashes while running local LLMs.

---

## 🚀 Setup & Execution

### Prerequisites

1. **Python 3.10+**
2. **Ollama**: Install [Ollama](https://ollama.com) and pull the `llama3.1:8b` model:
   ```bash
   ollama pull llama3.1:8b
   ```
3. **Security Tools (Kavach)**:
   - **nmap**: `brew install nmap` or `apt-get install nmap`
   - **subfinder**: `go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest`
   - **nuclei**: `go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest`
4. **Python Dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install reportlab
   ```

### 1. Installation
Clone the repository and install the dependencies:
```bash
git clone https://github.com/shubhamsharma0707/CloseAI.git
cd CloseAI
pip install -r requirements.txt
```

### 2. Configure Environment Tokens
Run the one-shot setup script to generate secure tokens for all agent nodes and configure the local RAM parameters:
```bash
python setup_dev.py
```

### 3. Run the Workflows

**Start the RISHI Core Node server (Terminal 1):**
```bash
python RISHI.py
```

**Run the Chanakya Financial Orchestrator (Terminal 2):**
```bash
python agents/chanakya/orchestrator.py
```

**Run the Kavach Security Orchestrator (Terminal 3):**
```bash
python agents/kavach/orchestrator.py
```

---

## 💻 Frontend UI
CloseAI also includes a modern, GPT-style React/Vite web interface.
```bash
cd frontend
npm install
npm run dev
```
