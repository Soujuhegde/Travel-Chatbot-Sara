import os
import re
from datetime import datetime, timedelta
from typing import TypedDict, Annotated, Literal, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_groq import ChatGroq
from app.schemas.chat import TaskRequest, TaskResponse
from app.agents.flight_agent import call_flight_agent
from app.agents.hotel_agent import call_hotel_agent
from pydantic import BaseModel, Field
import time
import random
import string

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

class ExtractedInfo(BaseModel):
    intent: Literal["book_flight", "book_hotel", "general_qa", "select_flight", "select_hotel", "provide_details", "payment_done", "provide_passenger_count", "confirm", "reject"] = "general_qa"
    origin: str | None = None
    destination: str | None = None
    departure_date: str | None = None
    limit: int | None = Field(description="The number of flights the user wants to see, if they explicitly mention a number (e.g. 'show me 5 flights').", default=None)
    journey_type: Literal["One Way", "Round Trip"] | None = None
    selected_class: str | None = None
    selected_airline: str | None = None
    selected_price: Optional[str] = Field(description="The price of the flight", default=None)
    booking_link: Optional[str] = Field(description="The booking URL link if provided in the message", default=None)
    passenger_name: Optional[str] = Field(description="Name of the passenger", default=None)
    passenger_email: str | None = None
    passenger_contact: str | None = None
    passenger_passport: str | None = None
    adults_count: int | None = None
    children_count: int | None = None
    infants_count: int | None = None
    hotel_city: str | None = None
    check_in_date: str | None = None
    check_out_date: str | None = None
    selected_option_index: int | None = Field(description="The index (0-based) of the flight or hotel option the user wants to select from the options presented, or null if they are not selecting an option.", default=None)

try:
    llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0)
except Exception as e:
    print(f"Warning: Failed to initialize ChatGroq. {e}")
    llm = None

def is_question(text: str) -> bool:
    text_clean = text.strip().lower()
    if "?" in text_clean:
        return True
    question_words = ["what", "which", "who", "where", "why", "how", "is", "are", "can", "could", "would", "should", "do", "does", "did", "tell", "show", "describe", "explain", "suggest", "recommend", "weather"]
    words = re.findall(r"\b\w+\b", text_clean)
    if words and any(w in question_words for w in words):
        return True
    return False

def get_next_flight_step(flight_params: Dict[str, Any], invalid_date: bool = False) -> str:
    if not flight_params.get("origin") or not flight_params.get("destination"):
        return "awaiting_origin_dest"
    elif invalid_date:
        return "invalid_departure_date"
    elif not flight_params.get("departure_date"):
        return "awaiting_departure_date"
    elif not flight_params.get("journey_type"):
        return "awaiting_journey_type"
    else:
        return "ready_to_search"

def parse_intent(state: ConversationState):
    if not llm:
        return {"current_step": "general_qa", "final_response": "LLM not configured."}
    
    recent_messages = state["messages"][-5:]
    flight_params = state.get("flight_params") or {}
    passenger_details = state.get("passenger_details") or {}
    selected_flight = state.get("selected_flight") or {}
    
    hotel_params = state.get("hotel_params") or {}
    hotel_result = state.get("hotel_result") or {}
    selected_hotel = state.get("selected_hotel") or {}
    
    passenger_count = state.get("passenger_count") or {}
    passengers_details = state.get("passengers_details") or []
    current_passenger_index = state.get("current_passenger_index") or 0
    pending_clarification = state.get("pending_clarification")
    
    user_msg_text = state["messages"][-1].content.strip()
    msg_text_lower = user_msg_text.lower()
    
    print("\n=== DEBUG parse_intent ===")
    print(f"User Message: {state['messages'][-1].content}")
    print(f"Current Step: {state.get('current_step')}")
    print(f"flight_params: {flight_params}")
    print(f"selected_flight: {selected_flight}")
    print("===========================\n")
    
    today = datetime.now()
    today_date = today.strftime("%A, %Y-%m-%d")
    tomorrow_date = (today + timedelta(days=1)).strftime("%A, %Y-%m-%d")
    
    upcoming_days = []
    for i in range(7):
        day = today + timedelta(days=i)
        upcoming_days.append(f"{day.strftime('%A')} ({day.strftime('%Y-%m-%d')})")
    upcoming_str = ", ".join(upcoming_days)
    
    options_to_show = state.get("options_to_show") or []
    options_str = ""
    if options_to_show:
        options_str = "\n    Suggested Options currently visible to the user:\n"
        for idx, opt in enumerate(options_to_show):
            if opt.get("type") == "flight" or "pricing" in opt:
                pricing_str = ", ".join(f"{p['class']}: {p['price']}" for p in opt.get("pricing", []))
                options_str += f"    - [Option {idx}] Airline: {opt.get('airline_name')}, Flight No: {opt.get('flight_numbers')}, Dep: {opt.get('departure_time')}, Arr: {opt.get('arrival_time')}, Base Price: {opt.get('price')} ({pricing_str})\n"
            else:
                options_str += f"    - [Option {idx}] Hotel: {opt.get('name')}, Rating: {opt.get('star_rating')}, Price per night: {opt.get('price_per_night')}, Amenities: {', '.join(opt.get('amenities', []))}\n"

    prompt = f"""You are a helpful travel assistant. Analyze the user's latest message and extract their intent and any travel details.
    
    Current known flight params: {flight_params}
    Current known passenger count: {passenger_count}
    Current passenger index being filled: {current_passenger_index + 1}
    Current Date: {today_date}
    Tomorrow's Date: {tomorrow_date}
    Upcoming 7 days reference: {upcoming_str}
    {options_str}
    
    Intents:
    - book_flight: user wants to search for flights.
    - book_hotel: user wants to search for hotels.
    - select_flight: user selects a specific flight and class. You can also match conversational selection (e.g. 'the expensive one', 'indigo', 'the second option') if flights are visible.
    - select_hotel: user selects a specific hotel. You can also match conversational selection (e.g. 'the cheapest one', 'Royal Hometel', 'the first hotel') if hotels are visible.
    - provide_passenger_count: user tells you how many adults/children/infants. Extract this into adults_count, children_count, infants_count.
    - provide_details: user provides their passenger info (name, email, contact, passport).
    - payment_done: user says payment is done.
    - confirm: user explicitly says yes/correct.
    - reject: user explicitly says no/wrong.
    - general_qa: anything else.
    
    Rules for Option Selection:
    - ONLY classify as 'select_flight' or 'select_hotel' if the user explicitly wants to book, select, choose, or proceed with a specific option (e.g. 'choose the expensive one', 'book the cheapest flight', 'select option 1', 'let's go with Indigo').
    - If the user is just asking a question about the options to compare them or seek information (e.g., 'which is the expensive one in this?', 'which is the cheapest?', 'what is the Indigo flight's duration?', 'which is the highest rated hotel?'), classify the intent as 'general_qa' (not select_flight or select_hotel), so we can answer their question without proceeding to selection.
    - If the user is selecting an option, populate 'selected_option_index' with the 0-based index of the selected option, and if they specify a class like 'economy' or 'business', extract it into 'selected_class'.

    Rules for Date Extraction:
    - ALWAYS convert departure_date, check_in_date, and check_out_date strictly to YYYY-MM-DD format.
    - If the user says "next [day]" (e.g., "next monday"), use the exact date for that day from the "Upcoming 7 days reference". Do NOT add an extra week.
    - Convert all origin and destination cities/countries/airports strictly to their most prominent 3-letter IATA airport code.
    - If a country is provided (e.g., 'India', 'France'), output its major international airport code (e.g., 'DEL' for India, 'CDG' for France).
    - If a city has multiple airports, output the primary airport code (e.g., 'LHR' for London, 'JFK' for New York) or the city code.
    - Be extremely careful with spelling and similar-sounding names (e.g., 'Mangalore' is 'IXE' and must not be confused with 'Bangalore' 'BLR'; 'Goa' is 'GOI' and not 'Genoa'; 'Manali' is 'KUU' (Kullu) and MUST NOT be confused with 'Belagavi' 'IXG').
    - Use your comprehensive knowledge to map ANY global city or country correctly."""
    
    messages = [SystemMessage(content=prompt)] + recent_messages
    
    try:
        structured_llm = llm.with_structured_output(ExtractedInfo)
        result = structured_llm.invoke(messages)
    except Exception as e:
        print(f"Structured LLM failed: {e}. Falling back to JSON prompt parsing.")
        try:
            fallback_prompt = f"""You are a travel assistant. We need to extract the travel intent from the user message.
            User Message: {user_msg_text}
            
            Respond STRICTLY with a JSON object matching this schema:
            {{
                "intent": "book_flight", "book_hotel", "general_qa", "select_flight", "select_hotel", "provide_details", "payment_done", "provide_passenger_count", "confirm" or "reject",
                "origin": string or null,
                "destination": string or null,
                "departure_date": string (YYYY-MM-DD) or null,
                "passenger_name": string or null,
                "passenger_email": string or null,
                "passenger_contact": string or null,
                "passenger_passport": string or null,
                "hotel_city": string or null,
                "check_in_date": string or null,
                "check_out_date": string or null
            }}
            Do not include any other text or explanation."""
            
            response = llm.invoke([SystemMessage(content=fallback_prompt)])
            import json
            cleaned_content = response.content.strip().replace("```json", "").replace("```", "")
            # Basic cleanup in case of extra words
            if "{" in cleaned_content and "}" in cleaned_content:
                cleaned_content = cleaned_content[cleaned_content.find("{"):cleaned_content.rfind("}")+1]
            data = json.loads(cleaned_content)
            data = {k: v for k, v in data.items() if v is not None}
            if "intent" not in data or data["intent"] not in ["book_flight", "book_hotel", "general_qa", "select_flight", "select_hotel", "provide_details", "payment_done", "provide_passenger_count", "confirm", "reject"]:
                data["intent"] = "general_qa"
            result = ExtractedInfo(**data)
        except Exception as ex:
            print(f"JSON parsing fallback also failed: {ex}. Using empty ExtractedInfo.")
            result = ExtractedInfo(intent="general_qa")
    
    step = state.get("current_step", "start")
    
    if result.origin and (not flight_params.get("origin") or step == "awaiting_origin_dest"): 
        flight_params["origin"] = result.origin
    if result.destination and (not flight_params.get("destination") or step == "awaiting_origin_dest"): 
        flight_params["destination"] = result.destination
    if result.limit: 
        flight_params["limit"] = result.limit
    
    if result.hotel_city and (not hotel_params.get("city") or step == "hotel_awaiting_city"): 
        hotel_params["city"] = result.hotel_city
    if result.check_in_date and (not hotel_params.get("check_in_date") or step == "hotel_awaiting_check_in"): 
        hotel_params["check_in_date"] = result.check_in_date
    if result.check_out_date and (not hotel_params.get("check_out_date") or step == "hotel_awaiting_check_out"): 
        hotel_params["check_out_date"] = result.check_out_date
    
    invalid_date = False
    if result.departure_date and (not flight_params.get("departure_date") or step == "awaiting_departure_date"):
        try:
            date_obj = datetime.strptime(result.departure_date, "%Y-%m-%d").date()
            if date_obj < datetime.now().date():
                flight_params["departure_date"] = None
                invalid_date = True
            else:
                flight_params["departure_date"] = result.departure_date
        except ValueError:
            flight_params["departure_date"] = result.departure_date

    if result.journey_type and (not flight_params.get("journey_type") or step == "awaiting_journey_type"): 
        flight_params["journey_type"] = result.journey_type
    
    step = state.get("current_step", "start")
    incoming_step = step
    
    # Manual override for flight/hotel selection from UI clicks to guarantee accuracy
    if any(w in msg_text_lower for w in ["plan an itinerary", "plan itinerary", "itinerary plan", "itinerary"]):
        pending_clarification = None
        days_match = re.search(r"\b(\d+)\s*day", msg_text_lower)
        if days_match:
            hotel_params["itinerary_days"] = int(days_match.group(1))
            step = "plan_itinerary"
        else:
            step = "itinerary_awaiting_days"
    elif user_msg_text.startswith("I would like to select hotel "):
        result.intent = "select_hotel"
        try:
            parts = user_msg_text.replace("I would like to select hotel ", "").split(" for ")
            hotel_name = parts[0]
            price = parts[1]
            selected_hotel["name"] = hotel_name
            selected_hotel["price"] = price
            
            hr = state.get("hotel_result") or {}
            for h in hr.get("results", []):
                if hotel_name in h.get("name", ""):
                    selected_hotel["booking_link"] = h.get("booking_url") or "https://booking.com"
                    selected_hotel["star_rating"] = h.get("star_rating", "3-star")
                    selected_hotel["amenities"] = h.get("amenities", [])
                    break
        except Exception as e:
            print(f"Error parsing manual hotel selection: {e}")
            
    elif user_msg_text.startswith("I would like to select "):
        result.intent = "select_flight"
        try:
            parts = user_msg_text.replace("I would like to select ", "").split(" class on ")
            cls = parts[0]
            rest = parts[1].split(" for ")
            airline_flight = rest[0]
            price = rest[1]
            selected_flight["class"] = cls
            selected_flight["airline"] = airline_flight
            selected_flight["price"] = price
            
            fr = state.get("flight_result") or {}
            for f in fr.get("results", []):
                if airline_flight in f.get("airline_name", "") or airline_flight in f.get("flight_numbers", "") or f.get("flight_numbers") in airline_flight:
                    selected_flight["booking_link"] = f.get("booking_link") or "https://flights.google.com"
                    selected_flight["flight_numbers"] = f.get("flight_numbers", "N/A")
                    selected_flight["departure_time"] = f.get("departure_time", "00:00")
                    selected_flight["arrival_time"] = f.get("arrival_time", "00:00")
                    selected_flight["origin_airport"] = f.get("origin_airport", "Origin")
                    selected_flight["destination_airport"] = f.get("destination_airport", "Destination")
                    selected_flight["airline_logo"] = f.get("airline_logo", "")
                    selected_flight["airline_name"] = f.get("airline_name", airline_flight)
                    break
        except Exception as e:
            print(f"Error parsing manual flight selection: {e}")
            
    elif result.intent in ["select_flight", "select_hotel"] and result.selected_option_index is not None and 0 <= result.selected_option_index < len(options_to_show):
        opt = options_to_show[result.selected_option_index]
        if opt.get("type") == "flight" or "pricing" in opt:
            result.intent = "select_flight"
            pricing = opt.get("pricing", [])
            selected_cls = "Economy"
            selected_pr = opt.get("price")
            for p in pricing:
                if result.selected_class and result.selected_class.lower() in p["class"].lower():
                    selected_cls = p["class"]
                    selected_pr = p["price"]
                    break
            if not selected_pr and pricing:
                selected_cls = pricing[0]["class"]
                selected_pr = pricing[0]["price"]
            
            selected_flight["class"] = selected_cls
            selected_flight["airline"] = opt.get("airline_name")
            selected_flight["price"] = selected_pr
            selected_flight["booking_link"] = opt.get("booking_link") or "https://flights.google.com"
            selected_flight["flight_numbers"] = opt.get("flight_numbers", "N/A")
            selected_flight["departure_time"] = opt.get("departure_time", "00:00")
            selected_flight["arrival_time"] = opt.get("arrival_time", "00:00")
            selected_flight["origin_airport"] = opt.get("origin_airport", "Origin")
            selected_flight["destination_airport"] = opt.get("destination_airport", "Destination")
            selected_flight["airline_logo"] = opt.get("airline_logo", "")
            selected_flight["airline_name"] = opt.get("airline_name")
        else:
            result.intent = "select_hotel"
            selected_hotel["name"] = opt.get("name")
            selected_hotel["price"] = opt.get("price_per_night")
            selected_hotel["booking_link"] = opt.get("booking_url") or "https://booking.com"
            selected_hotel["star_rating"] = opt.get("star_rating", "3-star")
            selected_hotel["amenities"] = opt.get("amenities", [])
            
    if step == "awaiting_passenger_count" and not user_msg_text.startswith("I would like to select "):
        if result.intent in ["general_qa", "select_flight", "select_hotel"] and is_question(user_msg_text):
            pass
        else:
            result.intent = "provide_passenger_count"
            
    is_confirmation = result.intent == "confirm" or msg_text_lower in ["yes", "y", "yeah", "correct", "right", "ok", "okay", "sure", "proceed"] or "yes" in msg_text_lower
    is_rejection = result.intent == "reject" or msg_text_lower in ["no", "n", "nope", "wrong", "wait"] or "no" in msg_text_lower

    # If we are verifying passenger count, strict intercept of confirmation/rejection to prevent LLM hallucinations
    if step == "verify_passenger_count":
        if is_confirmation:
            step = "awaiting_passenger_details"
            result.intent = "confirm"
        elif is_rejection:
            step = "awaiting_passenger_count"
            result.intent = "reject"
        elif result.intent == "provide_details":
            step = "awaiting_passenger_details"
        elif result.intent == "select_flight" and not user_msg_text.startswith("I would like to select "):
            # Prevent hallucinated flight selection
            step = "verify_passenger_count"
            
    if step == "plan_itinerary" or step == "itinerary_awaiting_days":
        if step == "itinerary_awaiting_days" and incoming_step == "itinerary_awaiting_days":
            days_match = re.search(r"\b(\d+)\b", user_msg_text)
            if days_match:
                hotel_params["itinerary_days"] = int(days_match.group(1))
                step = "plan_itinerary"
                pending_clarification = None
            else:
                pending_clarification = "⚠️ Validation Error:\n- Please enter a valid number of days (e.g. 3 or '5 days')."
        else:
            pass
    elif step in ["awaiting_origin_dest", "awaiting_departure_date", "invalid_departure_date", "awaiting_journey_type"]:
        step = get_next_flight_step(flight_params, invalid_date)
    elif step != "verify_passenger_count" and result.intent == "select_flight":
        if result.selected_airline and not user_msg_text.startswith("I would like to select "): selected_flight["airline"] = result.selected_airline
        if result.selected_class and not user_msg_text.startswith("I would like to select "): selected_flight["class"] = result.selected_class
        if result.selected_price and not user_msg_text.startswith("I would like to select "): selected_flight["price"] = result.selected_price
        if hasattr(result, "booking_link") and result.booking_link and not user_msg_text.startswith("I would like to select "): selected_flight["booking_link"] = result.booking_link
        
        step = "awaiting_passenger_count"
        
    elif step != "verify_passenger_count" and result.intent == "select_hotel" and not step.startswith("hotel_awaiting_") and step != "hotel_summary":
        pax = passengers_details[0] if passengers_details else (passenger_details or {})
        if pax.get("name") and not selected_hotel.get("guest_name"):
            selected_hotel["guest_name"] = pax.get("name")
        if pax.get("email") and not selected_hotel.get("guest_email"):
            selected_hotel["guest_email"] = pax.get("email")
        if pax.get("contact") and not selected_hotel.get("guest_phone"):
            selected_hotel["guest_phone"] = pax.get("contact")
            
        if not selected_hotel.get("guest_name"): step = "hotel_awaiting_guest_name"
        elif not selected_hotel.get("guest_email"): step = "hotel_awaiting_guest_email"
        elif not selected_hotel.get("guest_phone"): step = "hotel_awaiting_guest_phone"
        elif "special_requests" not in selected_hotel: step = "hotel_awaiting_special_requests"
        elif "arrival_time" not in selected_hotel: step = "hotel_awaiting_arrival_time"
        else: step = "hotel_summary"
            
    elif (result.intent == "provide_passenger_count" and step in ["awaiting_passenger_count", "start", "verify_passenger_count"]) or (step == "awaiting_passenger_count" and result.intent != "general_qa"):
        adults = result.adults_count or 1
        children = result.children_count or 0
        infants = result.infants_count or 0
        total = adults + children + infants
        if total == 0:
            total = 1
            adults = 1
        
        passenger_count = {"adults": adults, "children": children, "infants": infants, "total": total}
        passengers_details = []
        current_passenger_index = 0
        step = "verify_passenger_count"
            
    elif not step.startswith("hotel_") and step != "hotel_booking_confirmed" and (result.intent == "provide_details" or (step == "awaiting_passenger_details" and result.intent != "general_qa")):
        total_pax = passenger_count.get("total") or 1
        
        if current_passenger_index >= len(passengers_details):
            passengers_details.append({})
            
        pax = passengers_details[current_passenger_index]
        errors = []
        
        # Name validation (must be at least 2 chars)
        if result.passenger_name:
            name_clean = result.passenger_name.strip()
            if len(name_clean) >= 2:
                pax["name"] = name_clean
            else:
                errors.append("Name must be at least 2 characters long.")
                
        # Email validation
        if result.passenger_email:
            email_clean = result.passenger_email.strip()
            if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email_clean):
                pax["email"] = email_clean
            else:
                errors.append("Email address is invalid.")
                
        # Phone validation (with country code followed strictly by 10 digits)
        if result.passenger_contact:
            contact_clean = re.sub(r"[^\d+]", "", result.passenger_contact.strip())
            if re.match(r"^\+?\d{1,4}\d{10}$", contact_clean):
                pax["contact"] = contact_clean
            else:
                errors.append("Contact number must include a country code followed strictly by 10 digits (e.g. +919876543210).")
                
        # Passport validation (6 to 15 alphanumeric characters)
        if result.passenger_passport:
            passport_clean = re.sub(r"\s+", "", result.passenger_passport.strip())
            if len(passport_clean) >= 6 and len(passport_clean) <= 15 and passport_clean.isalnum():
                pax["passport"] = passport_clean.upper()
            else:
                errors.append("Passport number must be 6-15 alphanumeric characters.")
        
        if errors:
            pending_clarification = "⚠️ Validation Error:\n" + "\n".join([f"- {err}" for err in errors])
        else:
            pending_clarification = None
        
        if not pax.get("name") or not pax.get("email") or not pax.get("contact") or not pax.get("passport"):
            step = "awaiting_passenger_details"
        else:
            current_passenger_index += 1
            if current_passenger_index >= total_pax:
                step = "awaiting_payment"
            else:
                step = "awaiting_passenger_details"
                
    elif result.intent == "payment_done" or user_msg_text.strip().lower() == "payment done":
        if step in ["hotel_awaiting_payment", "hotel_summary"] or (step == "awaiting_payment" and selected_hotel.get("name")):
            step = "hotel_booking_confirmed"
        else:
            step = "booking_confirmed"
            
    elif step.startswith("hotel_"):
        # Budget refinement
        if "budget" in msg_text_lower or any(b in user_msg_text for b in ["₹", "Rs", "budget"]):
            matched = False
            for b_range in ["₹2,000–₹5,000", "₹5,000–₹8,000", "₹8,000–₹12,000", "₹12,000+", "I'll decide later"]:
                if b_range in user_msg_text or (b_range.replace("₹", "") in user_msg_text):
                    hotel_params["budget"] = b_range
                    step = "hotel_ready_to_search"
                    matched = True
                    break
            if not matched:
                prices = re.findall(r"[\d,]+", user_msg_text)
                if prices:
                    hotel_params["budget"] = user_msg_text.strip()
                    step = "hotel_ready_to_search"
                    matched = True
                    
        # Details gathering steps
        elif step == "hotel_confirm_city":
            if is_confirmation or user_msg_text.strip() == "✅ Yes" or "yes" in msg_text_lower:
                dest = flight_params.get("destination", "Pune")
                city_map = {"BOM": "Mumbai", "DEL": "Delhi", "BLR": "Bangalore", "SIN": "Singapore", "PNQ": "Pune"}
                hotel_params["city"] = city_map.get(dest.upper(), dest)
                
                if flight_params.get("departure_date"):
                    step = "hotel_confirm_dates"
                else:
                    step = "hotel_awaiting_check_in"
            else:
                step = "hotel_awaiting_city"
                
        elif step == "hotel_confirm_dates":
            if is_confirmation or user_msg_text.strip() == "✅ Yes" or "yes" in msg_text_lower:
                hotel_params["check_in_date"] = flight_params.get("departure_date")
                try:
                    dt = datetime.strptime(hotel_params["check_in_date"], "%Y-%m-%d")
                    hotel_params["check_out_date"] = (dt + timedelta(days=3)).strftime("%Y-%m-%d")
                except:
                    hotel_params["check_out_date"] = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
                step = "hotel_awaiting_guests"
            else:
                step = "hotel_awaiting_check_in"
                
        elif step == "hotel_awaiting_city":
            hotel_params["city"] = user_msg_text.strip()
            step = "hotel_awaiting_check_in"
            
        elif step == "hotel_awaiting_check_in":
            c_in = result.check_in_date or user_msg_text.strip()
            try:
                datetime.strptime(c_in, "%Y-%m-%d")
                hotel_params["check_in_date"] = c_in
                pending_clarification = None
                step = "hotel_awaiting_check_out"
            except:
                pending_clarification = "⚠️ Validation Error:\n- Please enter a valid date in YYYY-MM-DD format."
            
        elif step == "hotel_awaiting_check_out":
            c_out = result.check_out_date or user_msg_text.strip()
            valid = True
            try:
                dt_in = datetime.strptime(hotel_params.get("check_in_date"), "%Y-%m-%d")
                dt_out = datetime.strptime(c_out, "%Y-%m-%d")
                if dt_out <= dt_in:
                    valid = False
            except:
                valid = False
                
            if valid:
                hotel_params["check_out_date"] = c_out
                pending_clarification = None
                step = "hotel_awaiting_guests"
            else:
                pending_clarification = "⚠️ Validation Error:\n- Check-out date must be a valid date after the check-in date."
            
        elif step == "hotel_awaiting_guests":
            val = user_msg_text.replace("👤 ", "").replace("👥 ", "").replace("👨👩👧 ", "").replace("➕ ", "").strip()
            hotel_params["guests"] = val
            step = "hotel_awaiting_rooms"
            
        elif step == "hotel_awaiting_rooms":
            hotel_params["rooms"] = user_msg_text.strip()
            step = "hotel_awaiting_budget"
            
        elif step == "hotel_awaiting_budget":
            val = user_msg_text.strip()
            if "custom" in val.lower() or "✏️" in val:
                step = "hotel_awaiting_custom_budget"
            else:
                hotel_params["budget"] = val
                step = "hotel_awaiting_area"
                
        elif step == "hotel_awaiting_custom_budget":
            hotel_params["budget"] = user_msg_text.strip()
            step = "hotel_awaiting_area"
            
        elif step == "hotel_awaiting_area":
            hotel_params["area"] = user_msg_text.strip()
            step = "hotel_awaiting_category"
            
        elif step == "hotel_awaiting_category":
            hotel_params["category"] = user_msg_text.strip()
            step = "hotel_ready_to_search"
            
        elif step == "hotel_awaiting_guest_name":
            name_clean = user_msg_text.strip()
            if len(name_clean) >= 2:
                selected_hotel["guest_name"] = name_clean
                pending_clarification = None
            else:
                pending_clarification = "⚠️ Validation Error:\n- Name must be at least 2 characters long."
                
        elif step == "hotel_awaiting_guest_email":
            email_clean = user_msg_text.strip()
            if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email_clean):
                selected_hotel["guest_email"] = email_clean
                pending_clarification = None
            else:
                pending_clarification = "⚠️ Validation Error:\n- Email address is invalid."
                
        elif step == "hotel_awaiting_guest_phone":
            contact_clean = re.sub(r"[^\d+]", "", user_msg_text.strip())
            if re.match(r"^\+?\d{1,4}\d{10}$", contact_clean):
                selected_hotel["guest_phone"] = contact_clean
                pending_clarification = None
            else:
                pending_clarification = "⚠️ Validation Error:\n- Contact number must include a country code followed strictly by 10 digits."
                
        elif step == "hotel_awaiting_special_requests":
            val = user_msg_text.strip()
            selected_hotel["special_requests"] = "None" if val.lower() in ["skip", "none", "no special request", "no"] else val
            
        elif step == "hotel_awaiting_arrival_time":
            val = user_msg_text.strip()
            selected_hotel["arrival_time"] = "None" if val.lower() in ["skip", "none", "no"] else val
            
        # Re-check next detail gathering step
        if step.startswith("hotel_awaiting_guest_") or step in ["hotel_awaiting_special_requests", "hotel_awaiting_arrival_time", "hotel_summary"]:
            if not selected_hotel.get("guest_name"): step = "hotel_awaiting_guest_name"
            elif not selected_hotel.get("guest_email"): step = "hotel_awaiting_guest_email"
            elif not selected_hotel.get("guest_phone"): step = "hotel_awaiting_guest_phone"
            elif "special_requests" not in selected_hotel: step = "hotel_awaiting_special_requests"
            elif "arrival_time" not in selected_hotel: step = "hotel_awaiting_arrival_time"
            else: step = "hotel_summary"
            
    # Check if we are in an active booking details-gathering step
    is_gathering_details = step in [
        "awaiting_origin_dest", "awaiting_departure_date", "invalid_departure_date", "awaiting_journey_type",
        "awaiting_passenger_count", "awaiting_passenger_details", "verify_passenger_count",
        "awaiting_payment", "hotel_confirm_city", "hotel_confirm_dates"
    ] or (step is not None and step.startswith("hotel_awaiting_"))

    is_active_flow = is_gathering_details or step in [
        "ready_to_search", "flight_selecting", "booking_confirmed", "hotel_ready_to_search", "hotel_selecting", 
        "hotel_summary", "hotel_awaiting_payment", "hotel_booking_confirmed",
        "itinerary_awaiting_days", "plan_itinerary"
    ]

    interruption_question = None
    if result.intent == "general_qa" and not is_active_flow:
        step = "general_qa"
    elif result.intent == "general_qa" and is_active_flow:
        if is_question(user_msg_text):
            interruption_question = user_msg_text
        
    elif (result.intent == "book_hotel" or user_msg_text.strip().lower() == "book a hotel" or "hotel" in msg_text_lower) and not is_gathering_details:
        if flight_params.get("destination") or selected_flight.get("airline_name"):
            step = "hotel_confirm_city"
        else:
            step = "hotel_awaiting_city"
            
    elif result.intent == "book_flight" and not is_gathering_details:
        step = get_next_flight_step(flight_params, invalid_date)
        
    return {
        "current_step": step,
        "latest_intent": result.intent,
        "flight_params": flight_params,
        "passenger_details": passenger_details,
        "selected_flight": selected_flight,
        "passenger_count": passenger_count,
        "passengers_details": passengers_details,
        "current_passenger_index": current_passenger_index,
        "hotel_params": hotel_params,
        "selected_hotel": selected_hotel,
        "pending_clarification": pending_clarification,
        "interruption_question": interruption_question,
        "clarification_repeats": state.get("clarification_repeats") or {}
    }

def route_next(state: ConversationState):
    step = state.get("current_step")
    if step == "ready_to_search":
        return "flight_node"
    if step == "hotel_ready_to_search":
        return "hotel_node"
    return "ask_clarification"

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

        qa_prompt = f"""You are a specialized travel assistant chatbot.
The user is in the middle of a booking flow, and asked a travel-related question: "{interruption_question}"
Please answer their question directly, accurately, and concisely. Keep your answer strictly under 2 sentences. 
Do not decline the question if it is travel-related (destination, sightseeing, weather, culture, etc.).
{options_context}
"""
        try:
            msgs = [SystemMessage(content=qa_prompt)] + state["messages"][-2:]
            response = llm.invoke(msgs)
            interruption_answer = response.content.strip() + "\n\n"
        except Exception as e:
            print(f"Error generating interruption answer: {e}")

    # Guard repeats: check if we have already repeated the prompt for this step
    clarification_repeats = state.get("clarification_repeats") or {}
    repeats = clarification_repeats.get(step or "start", 0)

    def make_response(res_dict):
        if interruption_answer:
            prompt_msg = res_dict.get("final_response", "")
            
            if step in ["flight_selecting", "hotel_selecting"]:
                reminder_prefix = "Please select one of the suggested options above to proceed with your booking:\n"
                options_to_keep = res_dict.get("options_to_show") or options
                res_dict["options_to_show"] = options_to_keep
            else:
                reminder_prefix = "Could you please answer this to proceed with your booking?\n"
                
            res_dict["final_response"] = f"{interruption_answer.strip()}\n\n{reminder_prefix}{prompt_msg}"
        
        res_dict["interruption_question"] = None
        res_dict["clarification_repeats"] = clarification_repeats
        return res_dict
    
    # If the user goes off-topic or says something conversational/harsh, handle it dynamically
    if step == "general_qa":
        if llm:
            qa_prompt = f"""You are a specialized travel assistant chatbot designed to handle travel-related queries.
You should assist the user with any question related to travel, destinations, weather, sightseeing, culture, local food, transportation, hotels, flights, and itineraries.

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
                print(f"LLM Error in general_qa fallback: {e}")
                msg = "I'm here to help you with your travel bookings! Could we get back to that?"
        else:
            msg = "I'm here to help you with your travel bookings! Could we get back to that?"
            
        return make_response({"final_response": msg, "quick_replies": [], "options_to_show": []})
        
    if step == "awaiting_origin_dest":
        msg = "I can help with that! Where are you flying from and to?"
    elif step == "invalid_departure_date":
        msg = "Wrong data. Please enter a present or future date."
        replies = ["Today", "Tomorrow"]
    elif step == "awaiting_departure_date":
        msg = "Sure! I'll assist you in finding the best flights.\n\nWhen are you departing? For instance, you could say \"tomorrow,\" \"next Monday,\" or \"7th December.\""
        replies = ["Today", "Tomorrow"]
    elif step == "awaiting_journey_type":
        msg = "Are you planning a one-way or return journey?"
        replies = ["One Way", "Round Trip"]
    elif step == "flight_selecting":
        msg = "Here are the flight options. Click to choose your preferred one."
        options = state.get("options_to_show") or []
        
    elif step == "hotel_confirm_city":
        dest = flight_params.get("destination", "Pune")
        city_map = {"BOM": "Mumbai", "DEL": "Delhi", "BLR": "Bangalore", "SIN": "Singapore", "PNQ": "Pune"}
        dest_name = city_map.get(dest.upper(), dest)
        msg = f"I see you've booked a flight to {dest_name}. Are you planning to book a hotel in {dest_name}?"
        replies = ["✅ Yes", "❌ No, different city"]
        
    elif step == "hotel_confirm_dates":
        check_in = flight_params.get("departure_date", datetime.now().strftime("%Y-%m-%d"))
        msg = f"Your flight arrival is on {check_in}. Would you like to check in on the same day ({check_in})?"
        replies = ["✅ Yes", "✏️ Edit Dates"]
        
    elif step == "hotel_awaiting_city":
        msg = "Where would you like to stay? Which city?"
        
    elif step == "hotel_awaiting_check_in":
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}When will you be checking in? (Format: YYYY-MM-DD)"
        replies = ["Today", "Tomorrow"]
        
    elif step == "hotel_awaiting_check_out":
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}And when is your check-out date? (Format: YYYY-MM-DD)"
        replies = ["Tomorrow", "In 2 days", "In 3 days"]
        
    elif step == "hotel_awaiting_guests":
        msg = "How many guests will be staying?"
        replies = ["👤 1 Adult", "👥 2 Adults", "👨👩👧 Family", "➕ Custom"]
        
    elif step == "hotel_awaiting_rooms":
        msg = "How many rooms would you like to book?"
        replies = ["1 Room", "2 Rooms", "Custom"]
        
    elif step == "hotel_awaiting_budget":
        msg = "What's your preferred budget per night?"
        replies = ["₹2,000–₹5,000", "₹5,000–₹8,000", "₹8,000–₹12,000", "₹12,000+", "✏️ Custom Budget", "I'll decide later"]
        
    elif step == "hotel_awaiting_custom_budget":
        msg = "Please enter your preferred budget per night (e.g. ₹3,000–₹6,000 or ₹4,500+):"
        
    elif step == "hotel_awaiting_area":
        msg = "Where would you like to stay?"
        replies = ["Near Airport", "Near City Centre", "Near Business District", "Near Tourist Attractions", "No Preference"]
        
    elif step == "hotel_awaiting_category":
        msg = "What type of hotel are you looking for?"
        replies = ["⭐ 3-Star", "⭐⭐⭐⭐ 4-Star", "⭐⭐⭐⭐⭐ 5-Star", "Boutique Hotel", "No Preference"]
        
    elif step == "hotel_awaiting_guest_name":
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}Please enter the Guest's Full Name (as per government ID/passport):"
        
    elif step == "hotel_awaiting_guest_email":
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}Please enter the Guest's Email Address:"
        
    elif step == "hotel_awaiting_guest_phone":
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}Please enter the Guest's Mobile Number (with country code, e.g. +919876543210):"
        
    elif step == "hotel_awaiting_special_requests":
        msg = "Do you have any Special Requests? (Optional)"
        replies = ["Skip", "No special request"]
        
    elif step == "hotel_awaiting_arrival_time":
        msg = "What is your Estimated Arrival Time? (Optional)"
        replies = ["Skip", "No preference"]
        
    elif step == "hotel_summary":
        price_str = selected_hotel.get("price", "₹3,200")
        try:
            p_clean = int("".join(filter(str.isdigit, price_str)))
            total_p = p_clean * 3
            total_price = f"₹{total_p:,}"
        except:
            total_price = f"{price_str} x 3 nights"
            
        msg = f"📋 Booking Summary\n\n🏨 Hotel: {selected_hotel.get('name')}\n🌆 City: {hotel_params.get('city', 'Mumbai')}\n📅 Check-in: {hotel_params.get('check_in_date')}\n📅 Check-out: {hotel_params.get('check_out_date')}\n👥 Guests: {hotel_params.get('guests', '1 Adult')}\n🛏️ Rooms: {hotel_params.get('rooms', '1')}\n💰 Total Price: {total_price}\n👤 Guest Name: {selected_hotel.get('guest_name')}"
        replies = ["Payment Done"]
        options = [{"type": "action_button", "label": "Proceed to Booking", "url": selected_hotel.get("booking_link") or "https://booking.com"}]
        
    elif step == "hotel_awaiting_payment":
        link = selected_hotel.get("booking_link") or "https://booking.com"
        msg = f"Perfect! Let's proceed with booking your stay at {selected_hotel.get('name')}."
        replies = ["Payment Done"]
        options = [{"type": "action_button", "label": "Proceed to Booking", "url": link}]
        
    elif step == "hotel_booking_confirmed":
        pnr = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        # Calculate total price
        price_str = selected_hotel.get("price", "₹2,250")
        try:
            p_clean = int("".join(filter(str.isdigit, price_str)))
            try:
                d1 = datetime.strptime(hotel_params.get("check_in_date"), "%Y-%m-%d")
                d2 = datetime.strptime(hotel_params.get("check_out_date"), "%Y-%m-%d")
                nights = (d2 - d1).days
                if nights <= 0: nights = 1
            except:
                nights = 1
                
            rooms_str = hotel_params.get("rooms", "1")
            try:
                rooms_clean = int("".join(filter(str.isdigit, rooms_str)))
                if rooms_clean <= 0: rooms_clean = 1
            except:
                rooms_clean = 1
                
            total_p = p_clean * nights * rooms_clean
            total_price = f"₹{total_p:,}.00"
        except:
            nights = 1
            total_price = price_str
            
        formatted_price = price_str
        if not formatted_price.startswith("₹") and not formatted_price.startswith("$"):
            formatted_price = f"₹{formatted_price}"
        if not formatted_price.endswith(".00") and "." not in formatted_price:
            formatted_price = f"{formatted_price}.00"
            
        room_type = "Executive Rooms"
        if selected_hotel.get("star_rating", 3) >= 5:
            room_type = "Executive Rooms"
        else:
            room_type = "Standard Rooms"
            
        hotel_ticket = {
            "hotel_name": selected_hotel.get("name", "The Hotel Prime"),
            "room_type": room_type,
            "city": hotel_params.get("city", "Mumbai"),
            "check_in_date": hotel_params.get("check_in_date", "12 PM"),
            "check_out_date": hotel_params.get("check_out_date", "11 AM"),
            "guests": hotel_params.get("guests", "01 Adult"),
            "rooms": hotel_params.get("rooms", "01 Room"),
            "price_per_night": formatted_price,
            "total_price": total_price,
            "nights": nights,
            "image": selected_hotel.get("images", [""])[0] if selected_hotel.get("images") else "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=200&q=80"
        }
        
        msg = f"🎉 Payment Successful! Booking Confirmed. 🎉\n\nYour stay at {selected_hotel.get('name')} is confirmed with reservation number {pnr}."
        return make_response({"final_response": msg, "quick_replies": ["Book a Flight", "Plan an Itinerary"], "options_to_show": [], "ticket": hotel_ticket})
        
    elif step == "awaiting_passenger_count":
        msg = "How many adults, children, and infants will be traveling? For instance, you could say '2 adults, 2 children, 1 infant'."
        replies = ["1 adult", "2 adults", "2 adults, 1 child"]
        
    elif step == "verify_passenger_count":
        count = state.get("passenger_count", {})
        msg = f"Wonderful! Please verify the number of passengers.\n- Adults: {count.get('adults', 0)}\n- Children: {count.get('children', 0)}\n- Infants: {count.get('infants', 0)}"
        replies = ["Yes", "No"]
        
    elif step == "awaiting_passenger_details":
        pax_idx = state.get("current_passenger_index") or 0
        pax_list = state.get("passengers_details") or []
        pax = {}
        if pax_idx < len(pax_list):
            pax = pax_list[pax_idx]
            
        missing = []
        if not pax.get("name"): missing.append("Name")
        if not pax.get("email"): missing.append("Email")
        if not pax.get("contact"): missing.append("Contact No")
        if not pax.get("passport"): missing.append("Passport No")
        
        total_pax = (state.get("passenger_count") or {}).get("total") or 1
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}Please provide the {', '.join(missing)} for Passenger {pax_idx + 1} of {total_pax} to proceed."
        
    elif step == "awaiting_payment":
        flight = state.get("selected_flight", {})
        hotel = state.get("selected_hotel", {})
        
        if hotel.get("name"):
            link = hotel.get("booking_link") or "https://booking.com"
            msg = f"Perfect! Let's proceed with booking your stay at {hotel.get('name')}."
            replies = ["Payment done"]
            options = [{"type": "action_button", "label": "Proceed With Booking", "url": link}]
        else:
            origin = state.get("flight_params", {}).get("origin", "")
            destination = state.get("flight_params", {}).get("destination", "")
            
            base_link = flight.get("booking_link") or "https://flights.google.com"
            # Append origin and destination to the specific airline link
            if "?" in base_link:
                link = f"{base_link}&origin={origin}&destination={destination}"
            else:
                link = f"{base_link}?origin={origin}&destination={destination}"
                
            msg = "Perfect! Let's proceed with your booking."
            replies = ["Payment done"]
            options = [{"type": "action_button", "label": "Proceed With Booking", "url": link}]
    elif step == "itinerary_awaiting_days":
        flight = state.get("selected_flight") or {}
        hotel = state.get("selected_hotel") or {}
        fp = state.get("flight_params") or {}
        hp = state.get("hotel_params") or {}
        check_in = hp.get("check_in_date") or fp.get("departure_date")
        check_out = hp.get("check_out_date")
        days = 0
        if check_in and check_out:
            try:
                d1 = datetime.strptime(check_in, "%Y-%m-%d")
                d2 = datetime.strptime(check_out, "%Y-%m-%d")
                days = (d2 - d1).days
            except:
                pass
                
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        
        msg = f"{prefix}Great! I can plan a customized travel itinerary for you. How many days would you like me to plan the itinerary for?"
        
        replies = ["3 Days", "5 Days", "7 Days"]
        if days > 0 and str(days) not in ["3", "5", "7"]:
            replies.append(f"{days} Days")
            
        return make_response({"final_response": msg, "quick_replies": replies, "options_to_show": []})

    elif step == "plan_itinerary":
        flight = state.get("selected_flight") or {}
        hotel = state.get("selected_hotel") or {}
        fp = state.get("flight_params") or {}
        hp = state.get("hotel_params") or {}
        
        city = hp.get("city") or fp.get("destination") or "your destination"
        itinerary_days = hp.get("itinerary_days", 3)
        check_in = hp.get("check_in_date") or fp.get("departure_date") or "today"
        
        itinerary_prompt = f"""You are an expert travel planner. Create a highly customized, beautiful, and engaging travel itinerary for a trip to {city}.
        
        Trip Details:
        - Destination City: {city}
        - Duration: {itinerary_days} Days (starting {check_in})
        - Hotel Stay: {hotel.get('name', 'N/A')}
        - Flight details: {flight.get('airline_name', 'N/A')} flight {flight.get('flight_numbers', 'N/A')}
        - Guests / Occupancy: {hp.get('guests', '1 Adult')}
        
        Create a detailed, beautiful day-by-day travel itinerary strictly for {itinerary_days} days. 
        Structure your response beautifully using markdown:
        - Use clean headings (e.g. ### Day 1: [Theme])
        - Bullet points for activities
        - Highlight popular sights, dining recommendations, and travel tips
        - Use emojis to make it lively and modern.
        Keep the response engaging but concise enough to fit comfortably in a chat message."""
        
        response = llm.invoke([SystemMessage(content=itinerary_prompt)])
        msg = response.content
        
        replies = ["Book a Flight", "Book a Hotel"]
        return make_response({"final_response": msg, "quick_replies": replies, "options_to_show": []})
        
    elif step == "booking_confirmed":
        flight = state.get("selected_flight", {})
        hotel = state.get("selected_hotel", {})
        pax_list = state.get("passengers_details") or []
        if not pax_list:
            pax_list = [state.get("passenger_details", {})]
            
        pnr = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        if hotel.get("name"):
            msg = f"🎉 Payment Successful! Booking Confirmed. 🎉\n\nYour stay at {hotel.get('name')} is confirmed with reservation number {pnr}."
            return make_response({"final_response": msg, "quick_replies": ["Book a Flight", "Plan an Itinerary"], "options_to_show": []})
            
        # Determine the origin and destination based on the flight result if possible
        origin = state.get("flight_params", {}).get("origin", "Origin")
        destination = state.get("flight_params", {}).get("destination", "Destination")
        today_date = datetime.now().strftime("%A, %Y-%m-%d")
        date = state.get("flight_params", {}).get("departure_date", today_date)
        
        # Build the ticket dictionary
        ticket = {
            "pnr": pnr,
            "airline": flight.get('airline_name', flight.get('airline', 'N/A')),
            "flight_numbers": flight.get('flight_numbers', 'N/A'),
            "flight_class": flight.get('class', 'Economy'),
            "price": flight.get('price', 'N/A'),
            "date": date,
            "origin": origin.upper(),
            "destination": destination.upper(),
            "origin_full": flight.get("origin_airport", origin.upper()),
            "destination_full": flight.get("destination_airport", destination.upper()),
            "departure_time": flight.get('departure_time', '00:00'),
            "arrival_time": flight.get('arrival_time', '00:00'),
            "airline_logo": flight.get('airline_logo', ''),
            "gate": f"C{random.randint(10, 99)}",
            "seat": f"{random.randint(1, 30)}{random.choice(['A', 'B', 'C', 'D', 'E', 'F'])}",
            "group": random.choice(['A', 'B', 'C', 'D', 'E']),
            "passengers": pax_list
        }
            
        msg = f"🎉 Payment Successful! Booking Confirmed. 🎉\n\nI have generated your flight ticket below. Have a great trip!"
        return make_response({"final_response": msg, "quick_replies": ["Book a Hotel", "Plan an Itinerary"], "options_to_show": [], "ticket": ticket})

    return make_response({"final_response": msg, "quick_replies": replies, "options_to_show": options, "pending_clarification": None})

def flight_node(state: ConversationState):
    request = TaskRequest(
        task_id=f"flight_{int(time.time())}",
        task_type="flight_search",
        session_id=state.get("session_id", "default"),
        parameters=state.get("flight_params", {})
    )
    response = call_flight_agent(request)
    
    options = []
    if response.status == "success":
        for r in response.results:
            r["type"] = "flight"
            options.append(r)
            
    final_text = "Here are the flight options. Click to choose your preferred one." if options else "Sorry, we do not have any flights available on the searched date."
    return {"final_response": final_text, "options_to_show": options, "quick_replies": [], "flight_result": response.model_dump(), "current_step": "flight_selecting"}

def hotel_node(state: ConversationState):
    request = TaskRequest(
        task_id=f"hotel_{int(time.time())}",
        task_type="hotel_search",
        session_id=state.get("session_id", "default"),
        parameters=state.get("hotel_params", {})
    )
    response = call_hotel_agent(request)
    
    options = []
    if response.status == "success":
        for r in response.results:
            r["type"] = "hotel"
            options.append(r)
            
    final_text = "Here are some great hotels for your stay. Click to choose your preferred one." if options else "Sorry, we could not find any hotels for those dates."
    return {"final_response": final_text, "options_to_show": options[:3], "quick_replies": [], "hotel_result": response.model_dump(), "current_step": "hotel_selecting"}

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
