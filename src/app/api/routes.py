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
        "options_to_show": [],
        "serpapi_calls": []
    })
    
    # Reset serpapi calls list for this turn
    state["serpapi_calls"] = []
    
    # Add new message
    state["messages"].append(HumanMessage(content=request.message))
    
    # Run graph
    new_state = graph.invoke(state)
    
    final_resp = new_state.get("final_response", "I encountered an error processing that.")
    # Append bot's response to the context
    from langchain_core.messages import AIMessage
    new_state["messages"].append(AIMessage(content=final_resp))
    
    followup_msg = new_state.get("followup_message")
    followup_replies = new_state.get("followup_quick_replies") or []
    
    # Update session and persist to disk
    sessions[session_id] = new_state
    # Clear one-shot fields so they don't bleed into next response
    sessions[session_id]["followup_message"] = None
    sessions[session_id]["followup_quick_replies"] = []
    save_sessions()
    
    options_to_show = new_state.get("options_to_show") or []
    current_step = new_state.get("current_step")
    
    current_flow = None
    if current_step:
        if current_step.startswith("hotel_"):
            current_flow = "Hotel Booking"
        elif current_step.startswith("itinerary_") or current_step == "plan_itinerary":
            current_flow = "Itinerary Plan"
        elif current_step in ["awaiting_origin_dest", "awaiting_departure_date", "invalid_departure_date", "awaiting_journey_type", "ready_to_search", "flight_selecting", "awaiting_passenger_count", "verify_passenger_count", "awaiting_passenger_details", "awaiting_payment", "booking_confirmed"]:
            current_flow = "Flight Booking"
            
    ticket = new_state.get("ticket") if current_step in ["booking_confirmed", "hotel_booking_confirmed"] else None
    is_clarifying = current_step not in [
        "ready_to_search", "flight_selecting", "hotel_ready_to_search", "hotel_selecting",
        "booking_confirmed", "hotel_booking_confirmed",
        "plan_itinerary", "general_qa", "start", None
    ]
    clarification_needed = new_state.get("pending_clarification") or is_clarifying
    quick_replies = new_state.get("quick_replies", [])

    # Write the actual request and response of this turn to a JSON file
    try:
        import json
        from datetime import datetime
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "chatbot_api": {
                "request": {
                    "message": request.message,
                    "session_id": session_id
                },
                "response": {
                    "message": final_resp,
                    "options": options_to_show,
                    "clarification_needed": bool(clarification_needed),
                    "quick_replies": quick_replies,
                    "ticket": ticket,
                    "followup_message": followup_msg,
                    "followup_quick_replies": followup_replies,
                    "current_flow": current_flow
                }
            },
            "serpapi_calls": new_state.get("serpapi_calls") or []
        }
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(base_dir, "../../../"))
        log_filepath = os.path.join(project_root, "chat_req_resp.json")
        with open(log_filepath, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        print(f"Logged current interaction to {log_filepath}")
    except Exception as e:
        print(f"Error logging interaction to JSON: {e}")

    return ChatResponse(
        message=final_resp,
        options=options_to_show,
        clarification_needed=bool(clarification_needed),
        quick_replies=quick_replies,
        ticket=ticket,
        followup_message=followup_msg,
        followup_quick_replies=followup_replies,
        current_flow=current_flow
    )
