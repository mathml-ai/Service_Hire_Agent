import json
def mock_lead_capture(name: str, email: str, platform: str):
    """
    Simulates capturing a qualified lead.
    This should ONLY be called after collecting all required fields.
    """
    print("\n✅ Lead captured successfully!")
    print(f"Name     : {name}")
    print(f"Email    : {email}")
    print(f"Platform : {platform}")
    
    return {
        "status": "success",
        "message": "Lead captured successfully",
        "data": {
            "name": name,
            "email": email,
            "platform": platform
        }
    }
def is_valid_lead(name, email, platform):
    if not name or not email or not platform:
        return False
    
    if "@" not in email or "." not in email:
        return False
    
    return True
def load_knowledge(path="kb.json"):
    with open(path, "r") as f:
        return json.load(f)
def is_lead_incomplete(lead_state: dict):
    return not (lead_state["name"] and lead_state["email"] and lead_state["platform"])