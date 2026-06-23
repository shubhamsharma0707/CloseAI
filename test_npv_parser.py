import re

prompt = """
1. NPV vs IRR Conflict
A project requires an initial investment of ₹1,00,00,000 and generates the following cash flows:
Year                        Cash Flow (₹)
1                           80,00,000
2                           70,00,000
3                           -30,00,000

The discount rate is 12%.
"""

def parse(prompt):
    rate_match = re.search(r'(\d+(?:\.\d+)?)\s*%', prompt)
    if not rate_match: return "No rate"
    rate = float(rate_match.group(1)) / 100.0
    
    inv_match = re.search(r'investment of\s*₹?([\d,]+)', prompt, re.IGNORECASE)
    if not inv_match: return "No inv"
    initial = float(inv_match.group(1).replace(',', ''))
    
    # Match lines that look like "1    80,00,000" or "Year 1:  80,00,000"
    # Basically a digit 1-9, followed by space/colon, followed by a large number with commas
    cfs = []
    # finditer to find all matches of year number and cash flow
    matches = re.finditer(r'(?:Year\s*)?([1-9])(?:[\s:]+)(?:₹\s*)?(-?[\d,]{4,})', prompt, re.IGNORECASE)
    for m in matches:
        cf = float(m.group(2).replace(',', ''))
        cfs.append(cf)
        
    if not cfs: return "No cfs"
    
    npv = -initial
    for t, cf in enumerate(cfs):
        npv += cf / ((1 + rate) ** (t + 1))
        
    return f"NPV: {npv}"

print(parse(prompt))
