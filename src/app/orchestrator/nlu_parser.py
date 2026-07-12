import re
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Literal, List
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, BaseMessage
from langchain_groq import ChatGroq
from app.orchestrator.flight_flow import get_next_flight_step

class ExtractedInfo(BaseModel):
    intent: Literal["book_flight", "book_hotel", "general_qa", "select_flight", "select_hotel", "provide_details", "payment_done", "provide_passenger_count", "confirm", "reject"] = "general_qa"
    origin: str | None = Field(description="The 3-letter IATA code of the origin city or airport (e.g. 'BLR', 'DEL', 'JFK', 'TYO'). ALWAYS convert full city or country names to their primary 3-letter IATA code.", default=None)
    destination: str | None = Field(description="The 3-letter IATA code of the destination city or airport (e.g. 'BLR', 'DEL', 'JFK', 'TYO'). ALWAYS convert full city or country names to their primary 3-letter IATA code.", default=None)
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

def parse_intent(state: Dict[str, Any]) -> Dict[str, Any]:
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
    
    is_confirmation = result.intent == "confirm" or msg_text_lower in ["yes", "y", "yeah", "correct", "right", "ok", "okay", "sure", "proceed"] or "yes" in msg_text_lower
    is_rejection = result.intent == "reject" or msg_text_lower in ["no", "n", "nope", "wrong", "wait"] or "no" in msg_text_lower
    is_show_others = is_rejection or "select another" in msg_text_lower or "other options" in msg_text_lower or "show others" in msg_text_lower or "see all options" in msg_text_lower or "see all" in msg_text_lower

    # Initialize sub-flow parameters from state to avoid unbound variables
    is_gathering_details = state.get("current_step") in [
        "awaiting_origin_dest", "awaiting_departure_date", "invalid_departure_date", "awaiting_journey_type",
        "awaiting_passenger_count", "awaiting_passenger_details", "verify_passenger_count",
        "awaiting_payment", "hotel_confirm_city", "hotel_confirm_dates"
    ] or (state.get("current_step") is not None and state.get("current_step").startswith("hotel_awaiting_"))

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
    
    # Only accept departure_date when we are at a flight detail-gathering step or at the start.
    # Prevents pre-filling from initial messages only if they are not flight intents, but we allow them now.
    _date_accepting_steps = {"awaiting_departure_date", "invalid_departure_date", "awaiting_origin_dest", "start", "general_qa", None}
    invalid_date = False
    if result.departure_date and step in _date_accepting_steps:
        try:
            date_obj = datetime.strptime(result.departure_date, "%Y-%m-%d").date()
            if date_obj < datetime.now().date():
                flight_params["departure_date"] = None
                invalid_date = True
            else:
                flight_params["departure_date"] = result.departure_date
        except ValueError:
            flight_params["departure_date"] = result.departure_date

    # Accept journey_type when inside the flight flow or from the initial message
    _journey_accepting_steps = {"awaiting_origin_dest", "awaiting_departure_date", "invalid_departure_date", "awaiting_journey_type", "start", "general_qa", None}
    if result.journey_type and step in _journey_accepting_steps:
        flight_params["journey_type"] = result.journey_type
    
    step = state.get("current_step", "start")
    incoming_step = step
    
    _itinerary_steps = {"itinerary_awaiting_city", "itinerary_awaiting_start_date", "itinerary_awaiting_days", "plan_itinerary"}
    if any(w in msg_text_lower for w in ["plan an itinerary", "plan itinerary", "itinerary plan", "itinerary"]) and step not in _itinerary_steps:
        result.intent = "plan_itinerary"
        pending_clarification = None
        days_match = re.search(r"\b(\d+)\s*day", msg_text_lower)
        if days_match:
            hotel_params["itinerary_days"] = int(days_match.group(1))

        existing_city = hotel_params.get("city") or flight_params.get("destination")
        existing_date = hotel_params.get("check_in_date") or flight_params.get("departure_date")

        if not existing_city:
            step = "itinerary_awaiting_city"
        elif not existing_date and (selected_flight.get("airline_name") or selected_hotel.get("name")):
            step = "itinerary_awaiting_start_date"
        elif not hotel_params.get("itinerary_days"):
            step = "itinerary_awaiting_days"
        else:
            step = "plan_itinerary"
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
            
    if len(options_to_show) == 1 and step in ["flight_selecting", "hotel_selecting"]:
        if is_confirmation or user_msg_text.lower() in ["proceed", "proceed with this option", "proceed with this one", "book this", "yes"]:
            result.intent = "select_flight" if step == "flight_selecting" else "select_hotel"
            result.selected_option_index = 0
        elif is_show_others:
            if step == "flight_selecting":
                fr = state.get("flight_result") or {}
                original_results = fr.get("results", [])
                for r in original_results:
                    r["type"] = "flight"
                options_to_show = original_results
            else:
                hr = state.get("hotel_result") or {}
                original_results = hr.get("results", [])
                for r in original_results:
                    r["type"] = "hotel"
                options_to_show = original_results[:3]

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
            step = "verify_passenger_count"
        elif result.intent == "provide_passenger_count" or result.adults_count or result.children_count or result.infants_count:
            adults = result.adults_count or 0
            children = result.children_count or 0
            infants = result.infants_count or 0
            if adults == 0 and children == 0 and infants == 0:
                adults = 1
            total = adults + children + infants
            passenger_count = {"adults": adults, "children": children, "infants": infants, "total": total}
            passengers_details = []
            current_passenger_index = 0
            step = "verify_passenger_count"
            result.intent = "provide_passenger_count"

    if step in ["plan_itinerary", "itinerary_awaiting_days", "itinerary_awaiting_city", "itinerary_awaiting_start_date"]:
        if step == "itinerary_awaiting_city" and incoming_step == "itinerary_awaiting_city":
            city_val = user_msg_text.strip()
            if len(city_val) >= 2:
                hotel_params["city"] = city_val
                pending_clarification = None
                existing_date = hotel_params.get("check_in_date") or flight_params.get("departure_date")
                if not existing_date and (selected_flight.get("airline_name") or selected_hotel.get("name")):
                    step = "itinerary_awaiting_start_date"
                elif not hotel_params.get("itinerary_days"):
                    step = "itinerary_awaiting_days"
                else:
                    step = "plan_itinerary"
            else:
                pending_clarification = "⚠️ Validation Error:\n- Please enter a valid city name."

        elif step == "itinerary_awaiting_start_date" and incoming_step == "itinerary_awaiting_start_date":
            date_val = result.departure_date or result.check_in_date or user_msg_text.strip()
            try:
                date_obj = datetime.strptime(date_val, "%Y-%m-%d").date()
                if date_obj < datetime.now().date():
                    pending_clarification = "⚠️ Validation Error:\n- Please enter a present or future date."
                else:
                    hotel_params["check_in_date"] = date_val
                    pending_clarification = None
                    if not hotel_params.get("itinerary_days"):
                        step = "itinerary_awaiting_days"
                    else:
                        step = "plan_itinerary"
            except ValueError:
                pending_clarification = "⚠️ Validation Error:\n- Please enter a valid date (e.g. 2025-08-15 or 'next Monday')."

        elif step == "itinerary_awaiting_days" and incoming_step == "itinerary_awaiting_days":
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
        is_button_select = user_msg_text.startswith("I would like to select ")
        if result.selected_airline and not is_button_select: selected_flight["airline"] = result.selected_airline
        if result.selected_class and not is_button_select: selected_flight["class"] = result.selected_class
        if result.selected_price and not is_button_select: selected_flight["price"] = result.selected_price
        if hasattr(result, "booking_link") and result.booking_link and not is_button_select: selected_flight["booking_link"] = result.booking_link

        if not is_button_select and result.selected_option_index is not None and len(options_to_show) > 1:
            identified_opt = options_to_show[result.selected_option_index]
            options_to_show = [identified_opt]
            step = "flight_selecting"
        else:
            step = "awaiting_passenger_count"
        
    elif step != "verify_passenger_count" and result.intent == "select_hotel" and not step.startswith("hotel_awaiting_") and step != "hotel_summary":
        is_button_select_hotel = user_msg_text.startswith("I would like to select hotel ")
        pax = passengers_details[0] if passengers_details else (passenger_details or {})
        if pax.get("name") and not selected_hotel.get("guest_name"):
            selected_hotel["guest_name"] = pax.get("name")
        if pax.get("email") and not selected_hotel.get("guest_email"):
            selected_hotel["guest_email"] = pax.get("email")
        if pax.get("contact") and not selected_hotel.get("guest_phone"):
            selected_hotel["guest_phone"] = pax.get("contact")

        if not is_button_select_hotel and result.selected_option_index is not None and len(options_to_show) > 1:
            identified_opt = options_to_show[result.selected_option_index]
            options_to_show = [identified_opt]
            step = "hotel_selecting"
        else:
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
        
        if result.passenger_name:
            name_clean = result.passenger_name.strip()
            if len(name_clean) >= 2:
                pax["name"] = name_clean
            else:
                errors.append("Name must be at least 2 characters long.")
                
        if result.passenger_email:
            email_clean = result.passenger_email.strip()
            if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email_clean):
                pax["email"] = email_clean
            else:
                errors.append("Email address is invalid.")
                
        if result.passenger_contact:
            contact_clean = re.sub(r"[^\d+]", "", result.passenger_contact.strip())
            if re.match(r"^\+?\d{1,4}\d{10}$", contact_clean):
                pax["contact"] = contact_clean
            else:
                errors.append("Contact number must include a country code followed strictly by 10 digits (e.g. +919876543210).")
                
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
        if step in ("hotel_awaiting_budget", "hotel_awaiting_custom_budget") and ("budget" in msg_text_lower or any(b in user_msg_text for b in ["₹", "Rs", "budget"])):
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
                step = "hotel_awaiting_check_out"
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
            step = "hotel_awaiting_room_type"

        elif step == "hotel_awaiting_room_type":
            hotel_params["room_type"] = user_msg_text.strip()
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
            
        if step.startswith("hotel_awaiting_guest_") or step in ["hotel_awaiting_special_requests", "hotel_awaiting_arrival_time", "hotel_summary"]:
            if not selected_hotel.get("guest_name"): step = "hotel_awaiting_guest_name"
            elif not selected_hotel.get("guest_email"): step = "hotel_awaiting_guest_email"
            elif not selected_hotel.get("guest_phone"): step = "hotel_awaiting_guest_phone"
            elif "special_requests" not in selected_hotel: step = "hotel_awaiting_special_requests"
            elif "arrival_time" not in selected_hotel: step = "hotel_awaiting_arrival_time"
            else: step = "hotel_summary"
            
    is_active_flow = is_gathering_details or step in [
        "ready_to_search", "flight_selecting", "hotel_ready_to_search", "hotel_selecting", 
        "hotel_summary", "hotel_awaiting_payment",
        "itinerary_awaiting_city", "itinerary_awaiting_start_date", "itinerary_awaiting_days",
        "plan_itinerary"  # include plan_itinerary so "7 Days" quick reply isn't overridden by general_qa
    ] or incoming_step in ["itinerary_awaiting_days", "itinerary_awaiting_city", "itinerary_awaiting_start_date"]

    interruption_question = None
    if result.intent == "general_qa" and not is_active_flow:
        step = "general_qa"
    elif result.intent == "general_qa" and is_active_flow:
        is_providing_parameter = False
        if step in ["awaiting_origin_dest", "hotel_awaiting_city", "itinerary_awaiting_city"] and (result.origin or result.destination or result.hotel_city):
            is_providing_parameter = True
        elif step in ["awaiting_departure_date", "hotel_awaiting_check_in", "hotel_awaiting_check_out"] and (result.departure_date or result.check_in_date or result.check_out_date):
            is_providing_parameter = True
        elif step in ["awaiting_passenger_count"] and (result.adults_count or result.children_count or result.infants_count):
            is_providing_parameter = True
        elif step == "itinerary_awaiting_days":
            if re.search(r"\b\d+\b", user_msg_text):
                is_providing_parameter = True

        if is_confirmation or is_providing_parameter:
            interruption_question = None
        else:
            interruption_question = user_msg_text
        
    elif (result.intent == "book_hotel" or user_msg_text.strip().lower() == "book a hotel") and not is_gathering_details:
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
        "clarification_repeats": state.get("clarification_repeats") or {},
        "options_to_show": options_to_show
    }
