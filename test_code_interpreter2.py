import requests
import json

system_prompt = (
    "You are a Python execution agent. You MUST write a python script to calculate the answer. "
    "Output ONLY the python script inside ```python ... ``` blocks. Do not explain anything. Just write the code."
)

prompt = "A bond has: Face value: ₹1,000 Coupon: 8% Maturity: 3 years Yield: 10% Calculate the Macaulay duration."

payload = {
    "model": "llama3.1:8b",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ],
    "stream": False
}

r = requests.post("http://127.0.0.1:11434/api/chat", json=payload)
print(r.json().get('message', {}).get('content', ''))
