import re

prompt = """
A company has:
- Net income: ₹50 crore
- Existing shares: 10 crore
- Convertible bonds: ₹100 crore at 5% interest
- Conversion ratio: 20 shares per ₹1,000 bond
- Tax rate: 30%
Question: Calculate diluted EPS.
"""

def parse(prompt):
    try:
        # Net income
        ni_match = re.search(r'Net income:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)\s*(crore|lakh|million)?', prompt, re.IGNORECASE)
        if not ni_match: return None
        ni = float(ni_match.group(1).replace(',', ''))
        # we can just keep everything in base units of whatever it is, but easier to just use the numbers if units match.
        # Let's assume all are in crores or we just do the math in the provided units.
        
        shares_match = re.search(r'Existing shares:.*?([\d,]+(?:.\d+)?)\s*(crore|lakh|million)?', prompt, re.IGNORECASE)
        shares = float(shares_match.group(1).replace(',', ''))
        
        bonds_match = re.search(r'Convertible bonds:.*?(?:₹|Rs\.?)?\s*([\d,]+(?:.\d+)?)\s*(crore|lakh)?.*?(\d+(?:\.\d+)?)\s*%', prompt, re.IGNORECASE)
        bonds = float(bonds_match.group(1).replace(',', ''))
        interest = float(bonds_match.group(3)) / 100.0
        
        conv_match = re.search(r'Conversion ratio:\s*(\d+)\s*shares per\s*(?:₹|Rs\.?)?\s*([\d,]+)', prompt, re.IGNORECASE)
        conv_shares = float(conv_match.group(1))
        conv_per_bond = float(conv_match.group(2).replace(',', ''))
        
        tax_match = re.search(r'Tax rate:\s*(\d+(?:\.\d+)?)\s*%', prompt, re.IGNORECASE)
        tax = float(tax_match.group(1)) / 100.0
        
        # Calculate
        interest_saved = (bonds * interest) * (1 - tax)
        adj_earnings = ni + interest_saved
        
        # Additional shares: (bonds / conv_per_bond) * conv_shares
        # Wait, bonds is in crores (100 crore). conv_per_bond is 1000.
        # 100 crore = 1,000,000,000
        bonds_actual = bonds * 10000000
        new_shares_actual = (bonds_actual / conv_per_bond) * conv_shares
        
        # shares is in crores (10 crore = 100,000,000)
        shares_actual = shares * 10000000
        total_shares_actual = shares_actual + new_shares_actual
        
        ni_actual = ni * 10000000
        adj_earnings_actual = ni_actual + (interest_saved * 10000000)
        
        eps = adj_earnings_actual / total_shares_actual
        return eps
        
    except Exception as e:
        return f"Error: {e}"

print("Calculated EPS:", parse(prompt))
