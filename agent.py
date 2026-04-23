# app.py

import os
import json
from typing import TypedDict

import google.generativeai as genai
from langgraph.graph import StateGraph, END

from prompts.intention_detection import prompt as idp
from prompts.info_extract import prompt as iep 

from utils import mock_lead_capture, is_valid_lead, load_knowledge, is_lead_incomplete  


# ---------- GEMINI SETUP ----------
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("❌ GEMINI_API_KEY not found")

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-flash")


# ---------- STATE ----------
class AgentState(TypedDict):
    user_input: str
    intent: str
    response: str
    lead_state: dict
    messages: list
    summary: str

def update_memory(state: AgentState, role: str, content: str):
    state["messages"].append({"role": role, "content": content})


def summarize_memory(state: AgentState):
    """
    Summarize older messages if >5
    """
    if len(state["messages"]) <= 5:
        return state

    old_messages = state["messages"][:-5]
    recent_messages = state["messages"][-5:]

    summary_prompt = f"""
Existing Summary:
{state["summary"]}

New Messages to Summarize:
{old_messages}

Update the summary concisely.
"""

    response = model.generate_content(summary_prompt)
    state["summary"] = response.text.strip()

    state["messages"] = recent_messages
    return state


def get_memory_context(state: AgentState):
    return f"""
Conversation Summary:
{state["summary"]}

Recent Messages:
{state["messages"]}
"""
# ---------- INTENT ----------
def intent_detection(user_query: str, state: AgentState):
    memory_context = get_memory_context(state)

    modified_prompt = f"""
{idp}

{memory_context}

User Query:
{user_query}

Return ONLY the intent label.
"""
    response = model.generate_content(modified_prompt)
    return response.text.strip()




def rag_answer(query: str, state: AgentState):
    kb = load_knowledge()
    context = json.dumps(kb, indent=2)
    memory_context = get_memory_context(state)

    prompt_rag = f"""
{memory_context}

Answer the user strictly using the knowledge base below.

Knowledge Base:
{context}

User Question:
{query}
"""
    response = model.generate_content(prompt_rag)
    return response.text


# ---------- EXTRACTOR ----------
def extract_info(user_query: str):
    modified_prompt = f"""
{iep}

User message:
{user_query}
"""

    response = model.generate_content(modified_prompt)

    try:
        return json.loads(response.text)
    except:
        return {"name": None, "email": None}


# ---------- NODES ----------
def general_node(state: AgentState):
    user_query = state["user_input"]

    memory_context = get_memory_context(state)

    prompt_general = f"""
You are an assistant for AutoStream (AI video editing SaaS).

You also have access to conversation memory.

{memory_context}

Your job:
1. If the user is asking about past conversation (e.g. "what did I ask before"), answer using memory
2. If the question is unrelated, briefly respond
3. Then gently steer the conversation back to AutoStream

Rules:
- Keep responses concise
- Do NOT hallucinate past messages
- Use only provided memory
- Always bring the conversation back to AutoStream

User:
{user_query}
"""

    response = model.generate_content(prompt_general)
    state["response"] = response.text

    # store response in memory
    update_memory(state, "assistant", state["response"])

    return state

def intent_node(state: AgentState):
    update_memory(state, "user", state["user_input"])

    state["intent"] = intent_detection(state["user_input"], state)

    return state


def greeting_node(state: AgentState):
    if state["intent"] == "casual_greeting_introductory":
        state["response"] = "Welcome to AutoStream. How can I help you?"
    else:
        state["response"] = "It was nice talking to you. Visit again."

    update_memory(state, "assistant", state["response"])
    return state


def rag_node(state: AgentState):
    state["response"] = rag_answer(state["user_input"], state)
    update_memory(state, "assistant", state["response"])
    return state


def lead_node(state: AgentState):
    lead_state = state["lead_state"]

    extracted = extract_info(state["user_input"])

    if extracted.get("name") and not lead_state["name"]:
        lead_state["name"] = True
        lead_state["name_value"] = extracted["name"]

    if extracted.get("email") and not lead_state["email"]:
        lead_state["email"] = True
        lead_state["email_value"] = extracted["email"]

    if not lead_state["name"]:
        state["response"] = "Could you tell me your name?"
        update_memory(state, "assistant", state["response"])
        return state

    if not lead_state["email"]:
        state["response"] = "May I have your email address?"
        update_memory(state, "assistant", state["response"])
        return state
    if not lead_state["platform"]:
        state["response"]="Which platform you want to utilise our services for?"
        update_memory(state, "assistant", state["response"])
        return state

    if is_valid_lead(
        lead_state["name_value"],
        lead_state["email_value"],
        lead_state(["platform_value"])
    ):
        state["response"] = mock_lead_capture(
            lead_state["name_value"],
            lead_state["email_value"],
            lead_state["platform_value"]
        )
    else:
        state["response"] = "The details seem invalid. Please recheck your email."

    update_memory(state, "assistant", state["response"])
    return state


# ---------- ROUTER ----------
def router(state: AgentState):
    intent = state["intent"]
    lead_state = state["lead_state"]

    # 🔴 EXIT (LLM decides via intent)
    if intent == "casual_greeting_end":
        lead_state["active"] = False
        return "greeting"

    # 🔥 STICKY LEAD MODE (only if active)
    if lead_state["active"] and is_lead_incomplete(lead_state):
        return "lead"

    # 🟢 START LEAD MODE
    if intent == "high_intent_lead":
        lead_state["active"] = True
        return "lead"

    # normal routing
    if intent == "casual_greeting_introductory":
        return "greeting"

    elif intent == "product_or_pricing_inquiry":
        return "rag"

    elif intent == "general_purpose":
        return "general"

    return "general"

# ---------- GRAPH ----------
builder = StateGraph(AgentState)

builder.add_node("intent", intent_node)
builder.add_node("greeting", greeting_node)
builder.add_node("rag", rag_node)
builder.add_node("lead", lead_node)

builder.set_entry_point("intent")

builder.add_conditional_edges(
    "intent",
    router,
    {
        "greeting": "greeting",
        "rag": "rag",
        "lead": "lead"
    }
)

builder.add_edge("greeting", END)
builder.add_edge("rag", END)
builder.add_edge("lead", END)

graph = builder.compile()


# ---------- RUN LOOP ----------
if __name__ == "__main__":
    print("🚀 AutoStream Agent (LangGraph + Memory) Ready!\n")

    state = {
        "user_input": "",
        "intent": "",
        "response": "",
        "lead_state": {
            "name": False,
            "email": False,
            "name_value": None,
            "email_value": None
        },
        "messages": [],
        "summary": ""
    }

    while True:
        user_input = input("You: ")

        state["user_input"] = user_input

        result = graph.invoke(state)

        state = summarize_memory(result)

        print("Agent:", state["response"])