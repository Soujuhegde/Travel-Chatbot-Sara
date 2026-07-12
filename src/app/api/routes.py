from fastapi import APIRouter
from app.schemas.chat import ChatRequest, ChatResponse
from app.orchestrator.graph import graph
from langchain_core.messages import HumanMessage
import uuid
import pickle
import os

router = APIRouter()

SESSIONS_FILE = "sessions.pkl"
sessions = {}

def load_sessions():
    global sessions
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "rb") as f:
                sessions = pickle.load(f)
            print(f"Loaded {len(sessions)} active sessions from {SESSIONS_FILE}")
        except Exception as e:
            print(f"Error loading sessions: {e}")

def save_sessions():
    try:
        with open(SESSIONS_FILE, "wb") as f:
            pickle.dump(sessions, f)
    except Exception as e:
        print(f"Error saving sessions: {e}")

# Load sessions on startup / reload
load_sessions()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    
    # Get or create state
    state = sessions.get(session_id, {
        "messages": [],
        "session_id": session_id,
        "intent": None,
        "flight_params": {},
        "hotel_params": {},
        "pending_clarification": None,
        "flight_result": None,
        "hotel_result": None,
        "final_response": None,
        "options_to_show": []
    })
    
    # Add new message
    state["messages"].append(HumanMessage(content=request.message))
    
    # Run graph
    new_state = graph.invoke(state)
    
    final_resp = new_state.get("final_response", "I encountered an error processing that.")
    # Append bot's response to the context
    from langchain_core.messages import AIMessage
    new_state["messages"].append(AIMessage(content=final_resp))
    
    # Update session and persist to disk
    sessions[session_id] = new_state
    save_sessions()
    
    options_to_show = new_state.get("options_to_show") or []
    current_step = new_state.get("current_step")
    ticket = new_state.get("ticket") if current_step in ["booking_confirmed", "hotel_booking_confirmed"] else None
    is_clarifying = current_step not in [
        "ready_to_search", "flight_selecting", "hotel_ready_to_search", "hotel_selecting",
        "booking_confirmed", "hotel_booking_confirmed",
        "plan_itinerary", "general_qa", "start", None
    ]
    clarification_needed = new_state.get("pending_clarification") or is_clarifying
    quick_replies = new_state.get("quick_replies", [])

    return ChatResponse(
        message=final_resp,
        options=options_to_show,
        clarification_needed=bool(clarification_needed),
        quick_replies=quick_replies,
        ticket=ticket
    )
