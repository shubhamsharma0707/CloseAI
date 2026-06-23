import re

prompt = "A project requires an initial investment of 1,00,00,000 and generates the following cash flows: Year 1: 80,00,000. Year 2: 70,00,000. Year 3: -30,00,000. The discount rate is 12%."

# Find all numbers (including negatives and commas)
numbers = re.findall(r'-?[\d,]+', prompt)
clean_numbers = [float(n.replace(',', '')) for n in numbers if any(c.isdigit() for c in n)]
print("Numbers found:", clean_numbers)
