from typing import Optional, Tuple

RULES = [
    {"intent":"greet","keywords":["hi","hello","hey","good morning","good evening"],"response":"Hello! 👋 How can I help you today?"},
    {"intent":"goodbye","keywords":["bye","goodbye","see you","talk later"],"response":"Goodbye! Have a great day."},
    {"intent":"thanks","keywords":["thank","thanks","thx"],"response":"You're welcome! Anything else I can help with?"},
    {"intent":"hours","keywords":["open","hours","timing","when are you open","working hours"],"response":"Our support hours are 9 AM to 6 PM, Monday to Friday."},
    {"intent":"contact","keywords":["contact","support","email","phone","call"],"response":"Contact support at support@acme.com or call +1-800-123-987."},
    {"intent":"refund","keywords":["refund","return","money back"],"response":"Refunds are processed within 5–7 business days after approval."},
    {"intent":"products","keywords":["product","service","what do you offer","services"],"response":"We offer Acme Cloud Storage, Smart Devices, Data Backup, and Premium Support."},
    {"intent":"troubleshoot","keywords":["not working","issue","error","problem","device"],"response":"Try restarting the device, check firmware, ensure network connectivity. If problem persists, I can escalate."},
    {"intent":"escalate","keywords":["agent","human","real person","escalate"],"response":"Ok, I'll escalate this to a human agent. They will contact you."},
    {"intent":"small_talk","keywords":["how are you","what's up","how is it going"],"response":"I'm a bot, running smoothly 😄 — how can I help?"}
]

def rule_based_intent_and_response(text: str) -> Tuple[Optional[str], Optional[str]]:
    t = text.lower()
    for r in RULES:
        for kw in r["keywords"]:
            if kw in t:
                return r["intent"], r["response"]
    return None, None
