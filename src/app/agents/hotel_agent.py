from app.schemas.chat import TaskRequest, TaskResponse
import os
import re
import httpx
import time
from typing import Dict, Any

def call_hotel_agent(request: TaskRequest) -> TaskResponse:
    params = request.parameters
    if not params.get("city") or not params.get("check_in_date") or not params.get("check_out_date"):
        return TaskResponse(
            task_id=request.task_id,
            status="needs_clarification",
            clarification_needed="I need the city, check-in date, and check-out date to search for hotels.",
            metadata={"agent_id": "hotel_agent", "timestamp": time.time()}
        )
        
    api_key = os.getenv("SERPAPI_API_KEY")
    results = []
    serpapi_request_info = None
    serpapi_response_data = None
    
    if api_key:
        try:
            url = "https://serpapi.com/search.json"
            req_params = {
                "engine": "google_hotels",
                "q": f"hotels in {params.get('city')}",
                "check_in_date": params.get("check_in_date"),
                "check_out_date": params.get("check_out_date"),
                "currency": "INR",
                "hl": "en",
                "api_key": api_key
            }
            
            # Map budget if specified
            budget = params.get("budget", "")
            if budget and budget != "I'll decide later":
                prices = re.findall(r"[\d,]+", budget)
                if len(prices) == 2:
                    min_p = int(prices[0].replace(",", ""))
                    max_p = int(prices[1].replace(",", ""))
                    req_params["min_price"] = min_p
                    req_params["max_price"] = max_p
                elif len(prices) == 1 and "+" in budget:
                    min_p = int(prices[0].replace(",", ""))
                    req_params["min_price"] = min_p
            
            serpapi_request_info = {
                "url": url,
                "params": {k: v for k, v in req_params.items() if k != "api_key"}
            }

            response = httpx.get(url, params=req_params, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            serpapi_response_data = data
            
            properties = data.get("properties", [])
            for p in properties:
                lowest_rate = p.get("rate_per_night", {}).get("lowest", "")
                if not lowest_rate:
                    lowest_rate = p.get("total_rate", {}).get("lowest", "")
                    
                p_images = []
                for img in p.get("images", []):
                    img_url = img.get("url") or img.get("thumbnail")
                    if img_url:
                        p_images.append(img_url)
                        
                if len(p_images) < 2:
                    p_images = [
                        "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=600&q=80",
                        "https://images.unsplash.com/photo-1582719508461-905c673771fd?auto=format&fit=crop&w=600&q=80"
                    ]
                
                star_rating = p.get("rating", 4.0)
                guest_rating = str(p.get("rating", "4.5"))
                
                distance = p.get("distance", "Convenient location")
                if not distance and p.get("address"):
                    distance = p.get("address")
                
                amenities = p.get("amenities", p.get("highlights", ["Free WiFi", "AC", "Room Service"]))
                if not amenities:
                    amenities = ["Free WiFi", "AC", "Room Service"]
                
                card = {
                    "name": p.get("name", "Luxury Hotel"),
                    "star_rating": int(float(star_rating)) if star_rating else 4,
                    "price_per_night": lowest_rate or "₹4,500",
                    "distance": distance,
                    "amenities": amenities[:4],
                    "guest_rating": guest_rating,
                    "images": p_images[:3],
                    "booking_url": p.get("link") or "https://booking.com"
                }
                results.append(card)
                
        except Exception as e:
            print(f"SerpAPI Google Hotels Error: {e}")
            
    # Fallback to mock data if SerpApi fails or returns nothing
    if not results:
        from app.utils.mock_data import mock_search_hotels
        fallback = mock_search_hotels(params)
        if fallback.get("status") == "success":
            results = fallback.get("results", [])
            
    metadata = {
        "agent_id": "hotel_agent",
        "timestamp": time.time(),
        "source": "serpapi" if api_key and results else "mock"
    }
    if serpapi_request_info:
        metadata["serpapi_request"] = serpapi_request_info
    if serpapi_response_data:
        metadata["serpapi_response"] = serpapi_response_data

    return TaskResponse(
        task_id=request.task_id,
        status="success" if results else "failed",
        results=results,
        metadata=metadata
    )
