import os
import re
from typing import TypedDict, Annotated, Literal, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from app.orchestrator.nlu_parser import parse_intent, llm
from app.orchestrator.flight_flow import flight_node, get_flight_contextual_reminder, handle_flight_clarification
from app.orchestrator.hotel_flow import hotel_node, get_hotel_contextual_reminder, handle_hotel_clarification
from app.orchestrator.itinerary_flow import get_itinerary_contextual_reminder, handle_itinerary_clarification

class ConversationState(TypedDict):
    messages: List[BaseMessage]
    session_id: str
    current_step: str | None
    latest_intent: str | None
    flight_params: Dict[str, Any] | None
    pending_clarification: str | None
    quick_replies: List[str] | None
    flight_result: Dict[str, Any] | None
    final_response: str | None
    options_to_show: List[Dict[str, Any]] | None
    selected_flight: Dict[str, Any] | None
    passenger_details: Dict[str, Any] | None
    
    # Multi-passenger flow
    passenger_count: Dict[str, int] | None
    passengers_details: List[Dict[str, Any]] | None
    current_passenger_index: int | None
    ticket: Dict[str, Any] | None
    
    # Hotel flow
    hotel_params: Dict[str, Any] | None
    hotel_result: Dict[str, Any] | None
    selected_hotel: Dict[str, Any] | None

    # Conversational enhancements
    interruption_question: str | None
    clarification_repeats: Dict[str, int] | None
    followup_message: str | None
    followup_quick_replies: List[str] | None
    serpapi_calls: List[Dict[str, Any]] | None

def route_next(state: ConversationState):
    step = state.get("current_step")
    if step == "ready_to_search":
        return "flight_node"
    if step == "hotel_ready_to_search":
        return "hotel_node"
    return "ask_clarification"

def get_contextual_booking_reminder(step, state):
    if not step:
        return None
    # Check flight steps
    if step in ["awaiting_origin_dest", "awaiting_departure_date", "invalid_departure_date", "awaiting_journey_type", "flight_selecting", "awaiting_passenger_count", "verify_passenger_count", "awaiting_passenger_details", "awaiting_payment"] and not (step == "awaiting_payment" and state.get("selected_hotel", {}).get("name")):
        return get_flight_contextual_reminder(step, state)
    # Check hotel steps
    elif step.startswith("hotel_") or (step == "awaiting_payment" and state.get("selected_hotel", {}).get("name")):
        return get_hotel_contextual_reminder(step, state)
    # Check itinerary steps
    elif step.startswith("itinerary_"):
        return get_itinerary_contextual_reminder(step, state)
    return None

def ask_clarification(state: ConversationState):
    step = state.get("current_step")
    latest_intent = state.get("latest_intent")
    
    flight_params = state.get("flight_params") or {}
    hotel_params = state.get("hotel_params") or {}
    selected_hotel = state.get("selected_hotel") or {}
    selected_flight = state.get("selected_flight") or {}
    
    msg = "How can I help you?"
    replies = []
    options = []
    
    # Conversational QA interruption handling
    interruption_question = state.get("interruption_question")
    interruption_answer = ""
    identified_index = None
    if interruption_question and llm:
        options_to_show = state.get("options_to_show") or []
        options_context = ""
        if options_to_show:
            options_context = "\nOptions currently visible to the user on their screen:\n"
            for idx, opt in enumerate(options_to_show):
                if opt.get("type") == "flight" or "pricing" in opt:
                    pricing_str = ", ".join(f"{p['class']}: {p['price']}" for p in opt.get("pricing", []))
                    options_context += f"- Flight Option {idx}: Airline {opt.get('airline_name')} flight {opt.get('flight_numbers')}, base price {opt.get('price')} ({pricing_str})\n"
                else:
                    options_context += f"- Hotel Option {idx}: Hotel {opt.get('name')}, rating {opt.get('star_rating')}, price per night {opt.get('price_per_night')}, amenities {', '.join(opt.get('amenities', []))}\n"

        qa_prompt = f"""You are a friendly travel assistant chatbot helping the user complete a booking.

The user sent this message while in the middle of a booking: "{interruption_question}"

Classify the message into ONE of these 3 categories and respond accordingly:

CATEGORY 1 — GREETING or CASUAL (hello, hi, hey, thanks, how are you, good morning, ok, sure, etc.):
   Respond warmly and naturally, then gently redirect to the booking.
   Example for "hello": "Hello! 😊 Is there anything I can help you with, or shall we continue with your booking?"
   Example for "thanks": "You're welcome! Shall we continue with your booking? or You are Welcome , Please let me know if u need any help " 
   Keep it short, friendly, and conversational.

CATEGORY 2 — TRAVEL-RELATED QUESTION (airports, airlines, visa, luggage, destination tips, hotel amenities, weather for a trip, "what to eat in [city]", etc.):
   Answer directly and concisely in under 2 sentences.

CATEGORY 3 — COMPLETELY OFF-TOPIC (generic food recipes like "what is biryani", coding, math, science, personal advice, anything unrelated to travel):
   Respond exactly with: "I'm sorry, but I can only assist with travel-related queries such as flight bookings, hotel reservations, and itinerary planning. Please ask a travel-related question."

You must respond with a JSON object inside a ```json ``` block with these keys:
- "answer": your warm conversational response (Category 1, 2, or 3)
- "identified_option_index": if (and only if) the user is comparing or referring to one of the visible options above (e.g. "is the Indigo flight cheaper?" or "which is the expensive one?"), set this to the 0-based index of that option. Otherwise, set it to null.

Ensure you follow the strict formatting and rules. Do not hallucinate fields.
"""
        try:
            msgs = [SystemMessage(content=qa_prompt)] + state["messages"][-2:]
            response = llm.invoke(msgs)
            content = response.content.strip()
            
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                import json
                data = json.loads(match.group(0))
            else:
                import json
                data = json.loads(content)
                
            interruption_answer = data.get("answer", "").strip() + "\n\n"
            identified_index = data.get("identified_option_index")
            if identified_index is not None:
                try:
                    identified_index = int(identified_index)
                except (ValueError, TypeError):
                    identified_index = None
        except Exception as e:
            print(f"Error generating/parsing interruption JSON: {e}")
            try:
                msgs = [SystemMessage(content=qa_prompt.split("You must respond with a JSON")[0])] + state["messages"][-2:]
                response = llm.invoke(msgs)
                interruption_answer = response.content.strip() + "\n\n"
            except:
                interruption_answer = "I'm here to help you with your booking. How would you like to proceed?\n\n"
            identified_index = None

    # Guard repeats: check if we have already repeated the prompt for this step
    clarification_repeats = state.get("clarification_repeats") or {}

    _DECLINE_MARKER = "I'm sorry, I can only assist"

    def make_response(res_dict):
        if interruption_answer:
            answer_text = interruption_answer.strip()
            
            # Message 1 (main response) is the answer to greeting/question/decline
            res_dict["final_response"] = answer_text
            
            # Message 2 (followup message) is a contextual reminder of the booking step
            reminder = get_contextual_booking_reminder(step, state)
            if not reminder:
                reminder = res_dict.get("final_response") or ""
                
            res_dict["followup_message"] = reminder
            res_dict["followup_quick_replies"] = res_dict.get("quick_replies", [])
            
            # Since followup_message is present, clear main bubble's quick replies
            res_dict["quick_replies"] = []
            
            # Special case: identified option in flight/hotel selection
            if identified_index is not None and step in ["flight_selecting", "hotel_selecting"] and not answer_text.startswith(_DECLINE_MARKER):
                options_to_show = state.get("options_to_show") or []
                if 0 <= identified_index < len(options_to_show):
                    single_option = options_to_show[identified_index]
                    type_str = "flight" if (single_option.get("type") == "flight" or "pricing" in single_option) else "hotel"
                    res_dict["followup_message"] = f"Would you like to proceed with this {type_str} or do you want to select another one?"
                    res_dict["options_to_show"] = [single_option]
                    res_dict["followup_quick_replies"] = ["Proceed with this option", "Select another one"]
            elif step in ["flight_selecting", "hotel_selecting"]:
                res_dict["options_to_show"] = res_dict.get("options_to_show") or options
                
        res_dict["interruption_question"] = None
        res_dict["clarification_repeats"] = clarification_repeats
        return res_dict

    # If the user goes off-topic or says something conversational/harsh, handle it dynamically
    if step == "general_qa":
        if llm:
            qa_prompt = f"""You are a specialized travel assistant chatbot designed to handle travel-related queries.
You should assist the user with any question related to travel, destinations, weather, sightseeing, culture, local food, hotels, flights, and itineraries.

Guidelines:
1. Destination Information: If the user asks about a city/place (e.g., "How is Mumbai?", "how is the weather in mumbai", "best time to visit", "what to eat"), this is fully in-scope.
2. Conciseness: Keep your response extremely brief, short, and focused. Limit your response strictly to a maximum of 2 sentences (or 2 lines). Do not write essays, bulleted lists, or excessive details.
3. Out-of-Scope: Only decline questions that are completely unrelated to travel or destinations (e.g., coding, math, general science, personal advice). If and only if the question is completely unrelated to travel, respond exactly with: "I'm sorry, but I can only assist with travel-related queries such as flight bookings, hotel reservations, and itinerary planning. Please ask a travel-related question."
"""
            msgs = [SystemMessage(content=qa_prompt)] + state["messages"][-2:]
            try:
                response = llm.invoke(msgs)
                msg = response.content
            except Exception as e:
                print(f"Error calling general_qa LLM: {e}")
                msg = "I can assist you with flights, hotels, or custom itineraries. What would you like to plan?"
        else:
            msg = "I can assist you with flights, hotels, or custom itineraries. What would you like to plan?"
        
        replies = ["Book a Flight", "Book a Hotel", "Plan an Itinerary"]
        res_data = {"final_response": msg, "quick_replies": replies, "options_to_show": []}
    elif step in ["awaiting_origin_dest", "invalid_departure_date", "awaiting_departure_date", "awaiting_journey_type", "flight_selecting", "awaiting_passenger_count", "verify_passenger_count", "awaiting_passenger_details", "awaiting_payment", "booking_confirmed"] and not (step == "awaiting_payment" and state.get("selected_hotel", {}).get("name")):
        res_data = handle_flight_clarification(step, state)
    elif step and (step.startswith("hotel_") or step == "hotel_booking_confirmed" or (step == "awaiting_payment" and state.get("selected_hotel", {}).get("name"))):
        res_data = handle_hotel_clarification(step, state)
    elif step and step.startswith("itinerary_"):
        res_data = handle_itinerary_clarification(step, state)
    else:
        res_data = {"final_response": msg, "quick_replies": replies, "options_to_show": options}

    return make_response(res_data)

# Build Graph
builder = StateGraph(ConversationState)

builder.add_node("parse_intent", parse_intent)
builder.add_node("ask_clarification", ask_clarification)
builder.add_node("flight_node", flight_node)
builder.add_node("hotel_node", hotel_node)

builder.add_edge(START, "parse_intent")
builder.add_conditional_edges("parse_intent", route_next)
builder.add_edge("ask_clarification", END)
builder.add_edge("flight_node", END)
builder.add_edge("hotel_node", END)

graph = builder.compile()
