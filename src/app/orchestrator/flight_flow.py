import time
import random
import string
from datetime import datetime
from typing import Dict, Any, List
from app.schemas.chat import TaskRequest
from app.agents.flight_agent import call_flight_agent

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

def get_flight_contextual_reminder(step: str, state: Dict[str, Any]) -> str | None:
    flight_params = state.get("flight_params") or {}
    selected_flight = state.get("selected_flight") or {}
    passenger_count = state.get("passenger_count") or {}
    current_passenger_index = state.get("current_passenger_index") or 0

    if step == "awaiting_origin_dest":
        return "Could you please tell me where you are flying from and to so we can search for flights?"
    elif step == "awaiting_departure_date":
        return "Could you please provide your departure date (e.g. 'tomorrow' or 'next Monday')?"
    elif step == "invalid_departure_date":
        return "Please enter a valid present or future date to proceed with your booking."
    elif step == "awaiting_journey_type":
        return "To proceed, are you planning a one-way or round trip journey?"
    elif step == "flight_selecting":
        return "Please select one of the suggested flight options above to proceed, or let me know if you would like to see more options."
    elif step == "awaiting_passenger_count":
        return "To continue, could you please specify how many passengers will be traveling?"
    elif step == "verify_passenger_count":
        return "Please verify the passenger count details above. If correct, click 'Yes' or reply 'Yes' to proceed."
    elif step == "awaiting_passenger_details":
        total_pax = passenger_count.get("total") or 1
        pax_num = current_passenger_index + 1
        return f"Please provide the passenger details (Name, Email, Phone, Passport) for Passenger {pax_num} of {total_pax} to proceed."
    elif step == "awaiting_payment":
        return "Please click the 'Proceed With Booking' button above to book your flight, or reply 'Payment done' once you've completed the payment."
    return None

def handle_flight_clarification(step: str, state: Dict[str, Any]) -> Dict[str, Any]:
    msg = ""
    replies = []
    options = []
    ticket = None
    
    flight_params = state.get("flight_params") or {}
    selected_flight = state.get("selected_flight") or {}
    passenger_count = state.get("passenger_count") or {}
    passengers_details = state.get("passengers_details") or []
    current_passenger_index = state.get("current_passenger_index") or 0

    if step == "awaiting_origin_dest":
        msg = "Hi! I'm Sara, your AI travel companion. Let's find you the best flight. Where are you flying from and to?"
    elif step == "invalid_departure_date":
        msg = "Oops! It looks like the date you entered is in the past. Could you please provide a valid departure date? For example, you could say \"tomorrow\", \"next Monday\", or any upcoming date."
        replies = ["Today", "Tomorrow"]
    elif step == "awaiting_departure_date":
        msg = "Sure! I'll assist you in finding the best flights.\n\nWhen are you departing? For instance, you could say \"tomorrow,\" \"next Monday,\" or \"7th December.\""
        replies = ["Today", "Tomorrow"]
    elif step == "awaiting_journey_type":
        msg = "Are you planning a one-way or return journey?"
        replies = ["One Way", "Round Trip"]
    elif step == "flight_selecting":
        options_to_show = state.get("options_to_show") or []
        if len(options_to_show) == 1:
            msg = "Here's the flight I found for you based on your request. Would you like to proceed with this one, or see all available options?"
            replies = ["Proceed with this option", "See all options"]
        else:
            msg = "Here are the flight options. Click to choose your preferred one."
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
        origin = state.get("flight_params", {}).get("origin", "")
        destination = state.get("flight_params", {}).get("destination", "")
        
        base_link = selected_flight.get("booking_link") or "https://flights.google.com"
        if "?" in base_link:
            link = f"{base_link}&origin={origin}&destination={destination}"
        else:
            link = f"{base_link}?origin={origin}&destination={destination}"
            
        msg = "Perfect! Let's proceed with your booking."
        replies = ["Payment done"]
        options = [{"type": "action_button", "label": "Proceed With Booking", "url": link}]
        
    elif step == "booking_confirmed":
        pax_list = state.get("passengers_details") or []
        if not pax_list:
            pax_list = [state.get("passenger_details", {})]
            
        pnr = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        origin = state.get("flight_params", {}).get("origin", "Origin")
        destination = state.get("flight_params", {}).get("destination", "Destination")
        today_date = datetime.now().strftime("%A, %Y-%m-%d")
        date = state.get("flight_params", {}).get("departure_date", today_date)
        
        ticket = {
            "pnr": pnr,
            "airline": selected_flight.get('airline_name', selected_flight.get('airline', 'N/A')),
            "flight_numbers": selected_flight.get('flight_numbers', 'N/A'),
            "flight_class": selected_flight.get('class', 'Economy'),
            "price": selected_flight.get('price', 'N/A'),
            "date": date,
            "origin": origin.upper(),
            "destination": destination.upper(),
            "origin_full": selected_flight.get("origin_airport", origin.upper()),
            "destination_full": selected_flight.get("destination_airport", destination.upper()),
            "departure_time": selected_flight.get('departure_time', '00:00'),
            "arrival_time": selected_flight.get('arrival_time', '00:00'),
            "airline_logo": selected_flight.get('airline_logo', ''),
            "gate": f"C{random.randint(10, 99)}",
            "seat": f"{random.randint(1, 30)}{random.choice(['A', 'B', 'C', 'D', 'E', 'F'])}",
            "group": random.choice(['A', 'B', 'C', 'D', 'E']),
            "passengers": pax_list
        }
        msg = f"🎉 Payment Successful! Booking Confirmed. 🎉\n\nI have generated your flight ticket below. Have a great trip!"
        replies = ["Book a Hotel", "Plan an Itinerary"]

    return {"final_response": msg, "quick_replies": replies, "options_to_show": options, "ticket": ticket}

def flight_node(state: Dict[str, Any]) -> Dict[str, Any]:
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
    
    serpapi_calls = state.get("serpapi_calls") or []
    if response.metadata.get("serpapi_request"):
        serpapi_calls.append({
            "engine": "google_flights",
            "request": response.metadata.get("serpapi_request"),
            "response": response.metadata.get("serpapi_response")
        })
        
    return {
        "final_response": final_text, 
        "options_to_show": options, 
        "quick_replies": [], 
        "flight_result": response.model_dump(), 
        "current_step": "flight_selecting",
        "serpapi_calls": serpapi_calls
    }
