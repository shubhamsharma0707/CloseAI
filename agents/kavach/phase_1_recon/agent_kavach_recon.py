import logging
import asyncio
import subprocess
import shutil

logger = logging.getLogger("Kavach.ReconAgent")

class ReconAgent:
    def __init__(self):
        self.name = "AGENT_KAVACH_RECON"

    async def execute_recon(self, target: str) -> dict:
        """
        Simulates gathering public info and mapping the attack surface,
        or uses real tools if installed.
        """
        logger.info(f"[{self.name}] Initiating reconnaissance on target: {target}")
        
        discovered_assets = []
        open_ports = []
        
        # 1. Run Subfinder
        if shutil.which("subfinder"):
            logger.info(f"[{self.name}] Running subfinder on {target}...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "subfinder", "-d", target, "-silent",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                if stdout:
                    discovered_assets = [line.strip() for line in stdout.decode().split('\n') if line.strip()]
            except Exception as e:
                logger.error(f"[{self.name}] subfinder failed: {e}")
        else:
            logger.info(f"[{self.name}] subfinder not found, falling back to mock data.")
            discovered_assets = [f"api.{target}", f"dev.{target}", f"admin.{target}"]
            await asyncio.sleep(1)
            
        if target not in discovered_assets:
            discovered_assets.insert(0, target)

        # 2. Run Nmap (Fast scan on main target)
        if shutil.which("nmap"):
            logger.info(f"[{self.name}] Running nmap on {target}...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "nmap", "-F", target, "-oG", "-",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                if stdout:
                    for line in stdout.decode().split('\n'):
                        if "Ports:" in line:
                            parts = line.split("Ports:")[1].split(",")
                            for port_info in parts:
                                port = port_info.strip().split("/")[0]
                                if port.isdigit():
                                    open_ports.append(int(port))
            except Exception as e:
                logger.error(f"[{self.name}] nmap failed: {e}")
        else:
            logger.info(f"[{self.name}] nmap not found, falling back to mock data.")
            open_ports = [80, 443, 22, 3306]
            await asyncio.sleep(1)

        logger.info(f"[{self.name}] Discovered subdomains: {discovered_assets}")
        logger.info(f"[{self.name}] Open ports detected: {open_ports}")
        
        return {
            "status": "COMPLETED",
            "target": target,
            "discovered_assets": discovered_assets,
            "open_ports": open_ports,
            "risk_score": "MEDIUM"
        }
