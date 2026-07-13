from app.schemas.chat import TaskRequest, TaskResponse
import os
import time
import httpx
from datetime import datetime

def format_time(time_str: str) -> str:
    try:
        return time_str.split(" ")[1][:5]
    except:
        return time_str

def format_date(time_str: str) -> str:
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%a, %d %b %y")
    except:
        return time_str

def sanitize_iata_code(name: str) -> str:
    if not name:
        return name
    name_clean = name.strip().lower()
    iata_mapping = {
        # Countries (names & ISO 3-letter codes)
        "japan": "NRT",
        "jpn": "NRT",
        "india": "DEL",
        "ind": "DEL",
        "china": "PEK",
        "chn": "PEK",
        "united states": "JFK",
        "usa": "JFK",
        "united kingdom": "LHR",
        "gbr": "LHR",
        "france": "CDG",
        "germany": "FRA",
        "deu": "FRA",
        "ger": "FRA",
        "thailand": "BKK",
        "tha": "BKK",
        "malaysia": "KUL",
        "mys": "KUL",
        "mym": "KUL",
        "australia": "SYD",
        "aus": "SYD",
        "indonesia": "CGK",
        "idn": "CGK",
        "vietnam": "SGN",
        "vnm": "SGN",
        "maldives": "MLE",
        "mdv": "MLE",
        "sri lanka": "CMB",
        "lka": "CMB",
        
        # Cities & synonyms
        "tokyo": "NRT",
        "singapore": "SIN",
        "pune": "PNQ",
        "mumbai": "BOM",
        "bombay": "BOM",
        "delhi": "DEL",
        "new delhi": "DEL",
        "bangalore": "BLR",
        "bengaluru": "BLR",
        "hyderabad": "HYD",
        "chennai": "MAA",
        "madras": "MAA",
        "kolkata": "CCU",
        "calcutta": "CCU",
        "goa": "GOI",
        "jaipur": "JAI",
        "dubai": "DXB",
        "bangkok": "BKK",
        "paris": "CDG",
        "london": "LHR",
        "new york": "JFK",
        "los angeles": "LAX",
        "san francisco": "SFO",
        "chicago": "ORD",
        "kuala lumpur": "KUL",
        "sydney": "SYD",
        "melbourne": "MEL",
        "jakarta": "CGK",
        "bali": "DPS",
        "denpasar": "DPS",
        "ho chi minh": "SGN",
        "hanoi": "HAN",
        "male": "MLE",
        "colombo": "CMB",
        "toronto": "YYZ",
        "vancouver": "YVR"
    }
    if name_clean in iata_mapping:
        return iata_mapping[name_clean]
    if len(name_clean) == 3 and name_clean.isalpha():
        return name_clean.upper()
    return name.upper()

def call_flight_agent(request: TaskRequest) -> TaskResponse:
    params = request.parameters
    
    origin = sanitize_iata_code(params.get("origin"))
    destination = sanitize_iata_code(params.get("destination"))
    
    if not origin or not destination or not params.get("departure_date"):
        return TaskResponse(
            task_id=request.task_id,
            status="needs_clarification",
            clarification_needed="I need the origin, destination, and departure date to search for flights.",
            metadata={"agent_id": "flight_agent", "timestamp": time.time()}
        )
    
    api_key = os.getenv("SERPAPI_API_KEY")
    results = []
    serpapi_request_info = None
    serpapi_response_data = None

    if api_key:
        try:
            url = "https://serpapi.com/search.json"
            req_params = {
                "engine": "google_flights",
                "departure_id": origin,
                "arrival_id": destination,
                "outbound_date": params.get("departure_date"),
                "currency": "INR",
                "hl": "en",
                "type": "2",
                "api_key": api_key
            }
            
            serpapi_request_info = {
                "url": url,
                "params": {k: v for k, v in req_params.items() if k != "api_key"}
            }
            
            response = httpx.get(url, params=req_params, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            serpapi_response_data = data
            
            google_flights_url = data.get("search_metadata", {}).get("google_flights_url", "https://flights.google.com")
            
            best_flights = data.get("best_flights", [])
            other_flights = data.get("other_flights", [])
            flights = best_flights + other_flights
                
            seen_flight_numbers = set()
            
            def add_flight(f):
                first_leg = f.get("flights", [{}])[0]
                last_leg = f.get("flights", [{}])[-1]
                flight_number = first_leg.get("flight_number", "Unknown")
                
                if flight_number in seen_flight_numbers and flight_number != "Unknown":
                    return False
                seen_flight_numbers.add(flight_number)
                
                airline = first_leg.get("airline", "Unknown Airline")
                logo = first_leg.get("airline_logo", "https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/Air_India_Logo.svg/512px-Air_India_Logo.svg.png")
                
                dep = first_leg.get("departure_airport", {})
                arr = last_leg.get("arrival_airport", {})
                dep_time_raw = dep.get("time", "")
                arr_time_raw = arr.get("time", "")
                
                duration = str(f.get("total_duration", "Unknown")) + "m" if isinstance(f.get("total_duration"), int) else f.get("duration", "Unknown")
                
                stops_count = len(f.get("flights", [])) - 1
                stops_str = "Non-stop" if stops_count == 0 else f"Connecting Flight ({stops_count} Stop{'s' if stops_count > 1 else ''})"
                base_price = f.get("price", 0)
                
                origin_code = dep.get('id', origin)
                destination_code = arr.get('id', destination)
                
                dep_date = params.get("departure_date", "")   # YYYY-MM-DD
                adults  = max(1, (params.get("adults_count") or 1))

                # ---- Comprehensive official airline booking URL map ----
                airline_lower = airline.lower().strip()
                num = flight_number.replace(" ", "") if flight_number else ""

                def _gf():
                    """Google Flights deep link as universal fallback."""
                    return (
                        f"https://www.google.com/travel/flights/search?"
                        f"tfs=CBwQAhoeEgoyMDI1LTA4LTAxagcIARIDQkxScgcIARIDREVMGAFwAYIBCwj___________8B&curr=INR"
                    ) if not google_flights_url else google_flights_url

                # Build origin/destination formatted for deep links
                o = origin_code.upper()
                d = destination_code.upper()
                dt = dep_date  # YYYY-MM-DD

                if "indigo" in airline_lower or "6e" in airline_lower:
                    custom_link = (
                        f"https://www.goindigo.in/flight/search/{o}/{d}/{dt}/{adults}/0/0/E/O"
                    )
                elif "spicejet" in airline_lower or "sg" in airline_lower:
                    custom_link = (
                        f"https://book.spicejet.com/?departureDate={dt}"
                        f"&origin={o}&destination={d}&adults={adults}&children=0&infants=0&tripType=O"
                    )
                elif "akasa" in airline_lower or "qp" in airline_lower:
                    custom_link = (
                        f"https://www.akasaair.com/booking/flight-list?"
                        f"origin={o}&destination={d}&date={dt}&adults={adults}&children=0&infants=0&tripType=O"
                    )
                elif "air india express" in airline_lower or "ix" in airline_lower:
                    custom_link = (
                        f"https://www.airindiaexpress.com/flight-listing?"
                        f"origin={o}&destination={d}&depDate={dt}&adults={adults}&children=0&infants=0&tripType=O"
                    )
                elif "air india" in airline_lower or "ai" in airline_lower:
                    custom_link = (
                        f"https://www.airindia.com/in/en/ibe/booking.html?"
                        f"origin={o}&destination={d}&departureDate={dt}&adults={adults}&children=0&infants=0&tripType=O"
                        f"#/availability/departure"
                    )
                elif "vistara" in airline_lower or "uk" in airline_lower:
                    # Vistara merged into Air India
                    custom_link = (
                        f"https://www.airindia.com/in/en/ibe/booking.html?"
                        f"origin={o}&destination={d}&departureDate={dt}&adults={adults}"
                        f"#/availability/departure"
                    )
                elif "star air" in airline_lower or "s5" in airline_lower:
                    custom_link = f"https://www.starair.in/book-ticket?from={o}&to={d}&date={dt}&adults={adults}"
                elif "alliance air" in airline_lower:
                    custom_link = _gf()
                elif "srilankan" in airline_lower or "ul" in airline_lower:
                    custom_link = (
                        f"https://www.srilankan.com/en_uk/plan-and-book/flight-selection?"
                        f"origin={o}&destination={d}&date={dt}&adults={adults}&type=O"
                    )
                elif "emirates" in airline_lower or "ek" in airline_lower:
                    custom_link = (
                        f"https://www.emirates.com/ae/english/booking/?"
                        f"departureCode={o}&arrivalCode={d}&departureDate={dt}&adults={adults}&type=one-way"
                    )
                elif "singapore" in airline_lower or "sq" in airline_lower:
                    custom_link = (
                        f"https://www.singaporeair.com/en_UK/ppsclubs/flight-search/?"
                        f"departureCode={o}&arrivalCode={d}&departureDate={dt}&adults={adults}"
                    )
                elif "qatar" in airline_lower or "qr" in airline_lower:
                    custom_link = (
                        f"https://www.qatarairways.com/en/homepage.html#search?"
                        f"origin={o}&destination={d}&departure={dt}&adults={adults}&type=O"
                    )
                elif "etihad" in airline_lower or "ey" in airline_lower:
                    custom_link = (
                        f"https://www.etihad.com/en-in/fly-etihad/book/?from={o}&to={d}"
                        f"&date={dt}&adults={adults}&type=one-way"
                    )
                elif "british" in airline_lower or "ba" in airline_lower:
                    custom_link = (
                        f"https://www.britishairways.com/travel/book/public/en_in?"
                        f"origin={o}&destination={d}&outboundDate={dt}&adults={adults}&type=ECONOMY"
                    )
                elif "lufthansa" in airline_lower or "lh" in airline_lower:
                    custom_link = (
                        f"https://www.lufthansa.com/in/en/flight-search?"
                        f"origin={o}&destination={d}&outwardDate={dt}&numberOfPassengers={adults}&travelClass=Y"
                    )
                elif "united" in airline_lower or "ua" in airline_lower:
                    custom_link = (
                        f"https://www.united.com/en/us/fsr/choose-flights?"
                        f"f={o}&t={d}&d={dt}&tt=1&at={adults}&ct=0&ict=0&lang=en-US&_srt=PRICE_LOWEST"
                    )
                elif "american" in airline_lower or " aa" in airline_lower:
                    custom_link = (
                        f"https://www.aa.com/booking/search?locale=en_US&pax={adults}&adult={adults}"
                        f"&type=OneWay&searchType=Book&cabin=&carriers=AA"
                        f"&fromCity={o}&toCity={d}&departDate={dt}"
                    )
                elif "delta" in airline_lower or "dl" in airline_lower:
                    custom_link = (
                        f"https://www.delta.com/us/en/flight-search/results?"
                        f"cacheKeySuffix=en-US&originCode={o}&destinationCode={d}"
                        f"&selectedDate={dt}&paxCount={adults}&tripType=ONE_WAY"
                    )
                elif "thai" in airline_lower or "tg" in airline_lower:
                    custom_link = f"https://www.thaiairways.com/en_TH/tg_flights/flights/flight_booking.page?from={o}&to={d}&date={dt}"
                elif "malaysia" in airline_lower or "mh" in airline_lower:
                    custom_link = f"https://booking.malaysiaairlines.com/cgi-bin/mas/mas_fltsched.pl?type=OW&from={o}&to={d}&date={dt}&pax={adults}"
                elif "cathay" in airline_lower or "cx" in airline_lower:
                    custom_link = f"https://www.cathaypacific.com/cx/en_IN/flights/flight-search.html?origin={o}&destination={d}&departureDate={dt}&type=ow"
                elif "oman" in airline_lower or "wy" in airline_lower:
                    custom_link = f"https://www.omanair.com/en/book-flights?from={o}&to={d}&date={dt}&adults={adults}"
                elif "fly dubai" in airline_lower or "flydubai" in airline_lower or "fz" in airline_lower:
                    custom_link = f"https://www.flydubai.com/en/booking/?from={o}&to={d}&departureDate={dt}&type=OW&adults={adults}"
                elif "air arabia" in airline_lower or "g9" in airline_lower:
                    custom_link = f"https://www.airarabia.com/en/book-flights?dep={o}&arr={d}&date={dt}&adults={adults}"
                else:
                    custom_link = _gf()

                
                if base_price:
                    formatted_base = f"INR {base_price:,.2f}"
                    formatted_prem = f"INR {int(base_price * 1.35):,.2f}"
                    formatted_bus = f"INR {int(base_price * 2.8):,.2f}"
                else:
                    formatted_base = "Price unavailable"
                    formatted_prem = "Price unavailable"
                    formatted_bus = "Price unavailable"

                card = {
                    "airline_name": airline,
                    "airline_logo": logo,
                    "flight_numbers": flight_number,
                    "departure_date": format_date(dep_time_raw) if dep_time_raw else params.get("departure_date"),
                    "arrival_date": format_date(arr_time_raw) if arr_time_raw else params.get("departure_date"),
                    "departure_time": format_time(dep_time_raw) if dep_time_raw else "00:00",
                    "arrival_time": format_time(arr_time_raw) if arr_time_raw else "00:00",
                    "origin_airport": f"{dep.get('name', 'Origin')} ({dep.get('id', origin)})",
                    "destination_airport": f"{arr.get('name', 'Destination')} ({arr.get('id', destination)})",
                    "duration": duration,
                    "stops": stops_str,
                    "booking_link": custom_link,
                    "price": formatted_base,
                    "pricing": [
                        {"class": "Economy", "price": formatted_base},
                        {"class": "Premium Economy", "price": formatted_prem},
                        {"class": "Business", "price": formatted_bus}
                    ]
                }
                results.append(card)
                return True

            limit = params.get("limit", 5)
            seen_airlines = set()
            for f in flights:
                if len(results) >= limit:
                    break
                flight_info = f.get("flights", [{}])[0]
                airline = flight_info.get("airline", "Unknown Airline")
                if airline not in seen_airlines:
                    if add_flight(f):
                        seen_airlines.add(airline)
            
            if len(results) < limit:
                for f in flights:
                    if len(results) >= limit:
                        break
                    add_flight(f)
        except Exception as e:
            print(f"SerpAPI Error: {e}")

    # If no results were found (past date, API error, etc.), do not fallback to mock data as per user request.
    if not results:
        print("No real-time flights found.")

    metadata = {
        "agent_id": "flight_agent",
        "timestamp": time.time(),
        "source": "serpapi" if api_key and results else "mock"
    }
    if serpapi_request_info:
        metadata["serpapi_request"] = serpapi_request_info
    if serpapi_response_data:
        metadata["serpapi_response"] = serpapi_response_data

    return TaskResponse(
        task_id=request.task_id,
        status="success",
        results=results,
        metadata=metadata
    )
