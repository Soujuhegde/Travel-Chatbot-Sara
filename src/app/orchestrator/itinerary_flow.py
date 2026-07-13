from datetime import datetime
from typing import Dict, Any
from langchain_core.messages import SystemMessage
from app.orchestrator.nlu_parser import llm
from app.config import settings

def get_itinerary_contextual_reminder(step: str, state: Dict[str, Any]) -> str | None:
    hotel_params = state.get("hotel_params") or {}
    flight_params = state.get("flight_params") or {}

    if step == "itinerary_awaiting_city":
        return "Which city or destination would you like me to plan the itinerary for?"
    elif step == "itinerary_awaiting_start_date":
        city = hotel_params.get("city") or flight_params.get("destination") or "your destination"
        return f"When are you planning to start your trip to {city}?"
    elif step == "itinerary_awaiting_days":
        return "For how many days would you like me to plan the itinerary?"
    return None

def handle_itinerary_clarification(step: str, state: Dict[str, Any]) -> Dict[str, Any]:
    msg = ""
    replies = []
    options = []
    
    hotel_params = state.get("hotel_params") or {}
    flight_params = state.get("flight_params") or {}
    selected_flight = state.get("selected_flight") or {}
    selected_hotel = state.get("selected_hotel") or {}

    if step == "itinerary_awaiting_city":
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}Hi! I'm Sara, your AI travel companion. I'd love to plan a custom itinerary for you! Which city or destination are you planning to visit?"
        
    elif step == "itinerary_awaiting_start_date":
        city = hotel_params.get("city", "your destination")
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        msg = f"{prefix}Great choice! 🌍 When are you planning to start your trip to **{city}**? (e.g. 2025-08-15 or 'next Monday')"
        replies = ["Today", "Tomorrow"]
        
    elif step == "itinerary_awaiting_days":
        days = 0
        check_in = hotel_params.get("check_in_date") or flight_params.get("departure_date")
        check_out = hotel_params.get("check_out_date")
        if check_in and check_out:
            try:
                d1 = datetime.strptime(check_in, "%Y-%m-%d")
                d2 = datetime.strptime(check_out, "%Y-%m-%d")
                days = (d2 - d1).days
            except:
                pass
                
        clarification = state.get("pending_clarification")
        prefix = f"{clarification}\n\n" if clarification else ""
        city = hotel_params.get("city") or flight_params.get("destination", "your destination")
        msg = f"{prefix}Perfect! 🗓️ How many days would you like me to plan the itinerary for **{city}**?"
        
        replies = ["3 Days", "5 Days", "7 Days"]
        if days > 0 and str(days) not in ["3", "5", "7"]:
            replies.append(f"{days} Days")
            
    elif step == "plan_itinerary":
        city = hotel_params.get("city") or flight_params.get("destination") or "your destination"
        itinerary_days = hotel_params.get("itinerary_days", 3)
        check_in = hotel_params.get("check_in_date") or flight_params.get("departure_date") or "today"
        hotel_name = selected_hotel.get("name", "")
        airline_name = selected_flight.get("airline_name", "")
        guests = hotel_params.get("guests", "1 Adult")

        itinerary_prompt = f"""You are a world-class luxury travel planner with deep expertise in {city}. 
Create an EXTREMELY DETAILED, immersive, and practical day-by-day travel itinerary.

Trip Details:
- 🌍 Destination: {city}
- 📅 Duration: {itinerary_days} days (starting {check_in})
- 🏨 Accommodation: {hotel_name if hotel_name else "To be decided"}
- ✈️ Flight: {airline_name if airline_name else "To be arranged"}
- 👥 Travellers: {guests}

STRICT OUTPUT FORMAT — Follow this EXACTLY for EVERY SINGLE DAY:

### 🌟 Day [N]: [Catchy Theme Title]
**📅 Date:** [Starting date + N-1 days]

**🌅 Morning (8:00 AM – 12:00 PM)**
- 🍳 **Breakfast:** [Specific local restaurant + must-try dish + estimated cost]
- 🗺️ [Activity 1]: [Specific location name, what to see/do, how long, entry fees if any]
- 🗺️ [Activity 2]: [Specific location name, insider tip, best time to visit]
- 🚌 **Transport:** [Specific transport mode, cost, travel time from hotel/previous spot]

**☀️ Afternoon (12:00 PM – 6:00 PM)**
- 🍽️ **Lunch:** [Specific restaurant, signature dish, price range]
- 🗺️ [Activity 3]: [Location, what makes it special, photography tips]
- 🛍️ **Shopping/Leisure:** [Market or area name, what to buy, bargaining tips]
- 🚌 **Transport:** [How to get to evening location]

**🌙 Evening (6:00 PM – 10:00 PM)**
- 🌆 [Evening activity/viewpoint/show]: [Full details, booking tips]
- 🍷 **Dinner:** [Restaurant name, cuisine type, ambiance, must-order dishes, reservation needed?]
- 🎵 **After Dinner:** [Night market/bar/cultural show suggestion if applicable]

**💡 Local Tips for Day [N]:**
- [Practical tip 1 — dress code, safety, language phrase, etc.]
- [Practical tip 2 — best photo spots, avoid tourist traps, local custom]

**💰 Estimated Daily Budget:** ₹[X,XXX] – ₹[X,XXX] per person (excluding hotel)

---

RULES YOU MUST FOLLOW:
1. Generate ALL {itinerary_days} days with FULL detail — NO shortcuts, NO "similar to previous day"
2. Name REAL, specific places, restaurants, and attractions in {city}
3. Include REALISTIC travel times and costs in local currency
4. Each day must be DISTINCT with different attractions and neighborhoods  
5. Use rich emojis throughout to make it visually engaging
6. At the very end, add a **🎒 Packing Tips** section and a **📋 Essential Info** section (visa, currency, emergency numbers, best apps to use)

Start the itinerary now with Day 1 and go all the way through Day {itinerary_days} without stopping."""

        try:
            from langchain_groq import ChatGroq
            # Use the configured model
            itinerary_llm = ChatGroq(model=settings.LLM_MODEL, temperature=0.4, max_tokens=4096)
            response = itinerary_llm.invoke([SystemMessage(content=itinerary_prompt)])
            msg = response.content
        except Exception:
            # Fallback to default llm
            if llm:
                response = llm.invoke([SystemMessage(content=itinerary_prompt)])
                msg = response.content
            else:
                msg = "LLM not configured."
        replies = ["Book a Flight", "Book a Hotel", "Plan an Itinerary"]

    return {"final_response": msg, "quick_replies": replies, "options_to_show": options}

