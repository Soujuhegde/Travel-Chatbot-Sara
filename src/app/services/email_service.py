import httpx
from app.config import settings

class EmailService:
    def __init__(self):
        self.api_key = settings.BREVO_API_KEY
        self.url = "https://api.brevo.com/v3/smtp/email"

    async def send_booking_confirmation(self, email_to: str, booking_details: dict):
        is_hotel = "hotel_name" in booking_details
        subject = f"🏨 Booking Confirmation: {booking_details.get('hotel_name')}" if is_hotel else f"✈️ Boarding Pass: {booking_details.get('airline', 'Flight')} ({booking_details.get('pnr', 'PNR')})"

        html_content = self.generate_hotel_html(booking_details) if is_hotel else self.generate_flight_html(booking_details)

        if not self.api_key:
            print("\n" + "="*80)
            print(f"[MOCK EMAIL SERVICE] Triggers booking email dispatch!")
            print(f"To: {email_to}")
            print(f"Subject: {subject}")
            print(f"Details: {booking_details.get('hotel_name', booking_details.get('airline'))} booking successful.")
            print("="*80 + "\n")
            return True

        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json"
        }

        payload = {
            "sender": {"name": "Sara Travel Agent", "email": settings.BREVO_SENDER_EMAIL},
            "to": [{"email": email_to}],
            "subject": subject,
            "htmlContent": html_content
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.url, headers=headers, json=payload)
                response.raise_for_status()
                print("\n" + "="*80)
                print(f"[BREVO EMAIL SERVICE] Email sent successfully to: {email_to}")
                print(f"Message ID: {response.json().get('messageId')}")
                print("="*80 + "\n")
                return True
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    print("\n" + "!"*80)
                    print("[BREVO SERVICE ERROR] 401 Unauthorized.")
                    print("Your BREVO_API_KEY in the .env file is invalid or inactive.")
                    print("Please check your Brevo credentials at https://brevo.com")
                    print("!"*80 + "\n")
                else:
                    print(f"Error sending email (HTTP status error): {e}")
                return False
            except Exception as e:
                print(f"Error sending email: {e}")
                return False

    def generate_flight_html(self, ticket: dict) -> str:
        passengers_html = ""
        for p in ticket.get("passengers", []):
            passengers_html += f"""
            <tr style="border-bottom: 1px solid #eef2f3;">
                <td style="padding: 10px; font-weight: bold; color: #2c3e50;">{p.get('name', 'N/A')}</td>
                <td style="padding: 10px; color: #7f8c8d;">{p.get('email', 'N/A')}</td>
                <td style="padding: 10px; color: #7f8c8d;">{p.get('passport', 'N/A')}</td>
            </tr>
            """

        logo_img = f'<img src="{ticket.get("airline_logo")}" alt="{ticket.get("airline")}" style="height: 30px; object-fit: contain; margin-right: 10px;" />' if ticket.get("airline_logo") else ""

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Boarding Pass Confirmation</title>
        </head>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f7f6; padding: 30px 10px; margin: 0;">
            <div style="max-width: 650px; margin: 0 auto; background-color: #ffffff; border-radius: 20px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.05); border: 1px solid #eef2f3;">
                
                <!-- Main Header Ticket Layout -->
                <div style="background: linear-gradient(135deg, #0f2027, #203a43); color: #ffffff; padding: 25px 30px; border-bottom: 4px solid #ff7e5f;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="display: flex; align-items: center;">
                                {logo_img}
                                <span style="font-size: 20px; font-weight: 800; tracking-widest; text-transform: uppercase; vertical-align: middle;">{ticket.get('airline', 'BOARDING PASS')}</span>
                            </td>
                            <td style="text-align: right;">
                                <span style="font-size: 11px; text-transform: uppercase; color: #ff7e5f; font-weight: bold; letter-spacing: 1px; display: block; margin-bottom: 3px;">Booking Ref (PNR)</span>
                                <span style="font-size: 22px; font-weight: 800; letter-spacing: 2px;">{ticket.get('pnr', 'N/A')}</span>
                            </td>
                        </tr>
                    </table>
                </div>

                <!-- Flight Details Map -->
                <div style="padding: 30px;">
                    <table style="width: 100%; text-align: center; border-collapse: collapse; margin-bottom: 30px;">
                        <tr>
                            <td style="width: 35%; text-align: left;">
                                <span style="font-size: 12px; text-transform: uppercase; color: #7f8c8d; font-weight: bold; display: block;">From</span>
                                <span style="font-size: 40px; font-weight: 800; color: #2c3e50; line-height: 1.1;">{ticket.get('origin', 'N/A')}</span>
                                <span style="font-size: 13px; color: #95a5a6; display: block; margin-top: 3px;">{ticket.get('origin_full', 'N/A')}</span>
                            </td>
                            <td style="width: 30%; position: relative;">
                                <div style="font-size: 26px; color: #3498db; margin-bottom: 5px;">✈️</div>
                                <div style="font-size: 11px; color: #95a5a6; background-color: #ecf0f1; padding: 3px 8px; border-radius: 10px; display: inline-block; font-weight: bold;">{ticket.get('flight_class', 'Economy')}</div>
                            </td>
                            <td style="width: 35%; text-align: right;">
                                <span style="font-size: 12px; text-transform: uppercase; color: #7f8c8d; font-weight: bold; display: block;">To</span>
                                <span style="font-size: 40px; font-weight: 800; color: #2c3e50; line-height: 1.1;">{ticket.get('destination', 'N/A')}</span>
                                <span style="font-size: 13px; color: #95a5a6; display: block; margin-top: 3px;">{ticket.get('destination_full', 'N/A')}</span>
                            </td>
                        </tr>
                    </table>

                    <!-- Boarding Specifications -->
                    <div style="background-color: #f8fafc; border-radius: 15px; padding: 20px; margin-bottom: 35px; border: 1px dashed #cbd5e1;">
                        <table style="width: 100%; border-collapse: collapse; text-align: center;">
                            <tr>
                                <td style="border-right: 1px solid #e2e8f0; width: 25%; padding: 5px 0;">
                                    <span style="font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block; margin-bottom: 4px;">Flight</span>
                                    <span style="font-size: 16px; font-weight: 800; color: #0f2027;">{ticket.get('flight_numbers', 'N/A')}</span>
                                </td>
                                <td style="border-right: 1px solid #e2e8f0; width: 25%; padding: 5px 0;">
                                    <span style="font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block; margin-bottom: 4px;">Date</span>
                                    <span style="font-size: 15px; font-weight: 800; color: #0f2027;">{ticket.get('date', 'N/A')}</span>
                                </td>
                                <td style="border-right: 1px solid #e2e8f0; width: 25%; padding: 5px 0;">
                                    <span style="font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block; margin-bottom: 4px;">Gate</span>
                                    <span style="font-size: 16px; font-weight: 800; color: #0f2027; background-color: #ffefe5; color: #ff7e5f; padding: 2px 6px; border-radius: 4px;">{ticket.get('gate', 'N/A')}</span>
                                </td>
                                <td style="width: 25%; padding: 5px 0;">
                                    <span style="font-size: 10px; text-transform: uppercase; color: #64748b; font-weight: bold; display: block; margin-bottom: 4px;">Seat</span>
                                    <span style="font-size: 16px; font-weight: 800; color: #0f2027;">{ticket.get('seat', 'N/A')}</span>
                                </td>
                            </tr>
                        </table>
                    </div>

                    <!-- Passenger Tables -->
                    <h4 style="margin: 0 0 15px 0; color: #2c3e50; font-size: 16px; font-weight: 800; border-left: 4px solid #3498db; padding-left: 10px; text-transform: uppercase; letter-spacing: 0.5px;">Passenger Details</h4>
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 30px; text-align: left;">
                        <thead>
                            <tr style="background-color: #f8f9fa; border-bottom: 2px solid #eef2f3;">
                                <th style="padding: 10px; font-size: 12px; text-transform: uppercase; color: #7f8c8d; font-weight: bold;">Name</th>
                                <th style="padding: 10px; font-size: 12px; text-transform: uppercase; color: #7f8c8d; font-weight: bold;">Email</th>
                                <th style="padding: 10px; font-size: 12px; text-transform: uppercase; color: #7f8c8d; font-weight: bold;">Passport</th>
                            </tr>
                        </thead>
                        <tbody>
                            {passengers_html}
                        </tbody>
                    </table>

                    <div style="border-top: 1px solid #f1f5f9; padding-top: 25px; text-align: center;">
                        <p style="font-size: 13px; color: #94a3b8; margin: 0 0 15px 0;">Please present a printed or digital copy of this confirmation pass at the airline check-in counter.</p>
                        <a href="https://flights.google.com" style="display: inline-block; background-color: #3498db; color: #ffffff; padding: 12px 30px; font-size: 14px; font-weight: bold; border-radius: 30px; text-decoration: none; box-shadow: 0 4px 10px rgba(52,152,219,0.2);">Manage Booking</a>
                    </div>
                </div>

                <div style="background-color: #f8f9fa; text-align: center; padding: 20px; font-size: 11px; color: #95a5a6; border-top: 1px solid #eef2f3;">
                    This is an automated boarding confirmation sent by Sara Travel chatbot.
                </div>
            </div>
        </body>
        </html>
        """

    def generate_hotel_html(self, ticket: dict) -> str:
        img_html = f'<img src="{ticket.get("image")}" alt="{ticket.get("hotel_name")}" style="width: 100%; height: 200px; object-fit: cover;" />' if ticket.get("image") else ""

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Hotel Reservation Confirmation</title>
        </head>
        <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f5f5f0; padding: 30px 10px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 20px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.06); border: 1px solid #e4e4e0;">
                
                {img_html}

                <!-- Hotel Header -->
                <div style="padding: 30px 30px 20px 30px; border-bottom: 1px solid #f2f2ef;">
                    <span style="font-size: 11px; text-transform: uppercase; color: #c5a880; font-weight: 800; letter-spacing: 1.5px; display: block; margin-bottom: 5px;">Reservation Confirmed</span>
                    <h2 style="margin: 0 0 10px 0; color: #1c1c1c; font-size: 26px; font-weight: 800; line-height: 1.2;">{ticket.get('hotel_name', 'Luxury Hotel Stay')}</h2>
                    <p style="margin: 0; color: #787870; font-size: 14px;">📍 {ticket.get('city', 'N/A')}</p>
                </div>

                <!-- Reservation Details -->
                <div style="padding: 30px;">
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 30px;">
                        <tr>
                            <td style="width: 47%; vertical-align: top; background-color: #fafaf9; padding: 15px; border-radius: 12px;">
                                <span style="font-size: 11px; text-transform: uppercase; color: #a0a095; font-weight: bold; display: block; margin-bottom: 5px;">Check-In Date</span>
                                <span style="font-size: 16px; font-weight: 800; color: #1c1c1c;">{ticket.get('check_in_date', 'N/A')}</span>
                                <span style="font-size: 12px; color: #787870; display: block; margin-top: 3px;">From 12:00 PM</span>
                            </td>
                            <td style="width: 6%;"></td>
                            <td style="width: 47%; vertical-align: top; background-color: #fafaf9; padding: 15px; border-radius: 12px;">
                                <span style="font-size: 11px; text-transform: uppercase; color: #a0a095; font-weight: bold; display: block; margin-bottom: 5px;">Check-Out Date</span>
                                <span style="font-size: 16px; font-weight: 800; color: #1c1c1c;">{ticket.get('check_out_date', 'N/A')}</span>
                                <span style="font-size: 12px; color: #787870; display: block; margin-top: 3px;">Until 11:00 AM</span>
                            </td>
                        </tr>
                    </table>

                    <!-- Accommodation details table -->
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 30px; font-size: 14px;">
                        <tr style="border-bottom: 1px solid #f2f2ef;">
                            <td style="padding: 12px 0; color: #787870;">Guest Name:</td>
                            <td style="padding: 12px 0; font-weight: bold; color: #1c1c1c; text-align: right;">{ticket.get('guest_name', 'N/A')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f2f2ef;">
                            <td style="padding: 12px 0; color: #787870;">Room Type:</td>
                            <td style="padding: 12px 0; font-weight: bold; color: #1c1c1c; text-align: right;">{ticket.get('room_type', 'N/A')}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f2f2ef;">
                            <td style="padding: 12px 0; color: #787870;">Rooms / Length of Stay:</td>
                            <td style="padding: 12px 0; font-weight: bold; color: #1c1c1c; text-align: right;">{ticket.get('rooms', '1')} room(s) ({ticket.get('nights', '1')} night(s))</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f2f2ef;">
                            <td style="padding: 12px 0; color: #787870;">Guests:</td>
                            <td style="padding: 12px 0; font-weight: bold; color: #1c1c1c; text-align: right;">{ticket.get('guests', '1')} Guest(s)</td>
                        </tr>
                        <tr>
                            <td style="padding: 15px 0 0 0; color: #1c1c1c; font-weight: bold; font-size: 16px;">Total Price Paid:</td>
                            <td style="padding: 15px 0 0 0; font-weight: 800; color: #c5a880; text-align: right; font-size: 20px;">{ticket.get('total_price', 'N/A')}</td>
                        </tr>
                    </table>

                    <div style="border-top: 1px solid #f2f2ef; padding-top: 25px; text-align: center;">
                        <p style="font-size: 13px; color: #8e8e85; margin: 0 0 20px 0;">Please keep this receipt on hand when checking in at the front desk of the hotel.</p>
                        <a href="https://booking.com" style="display: inline-block; background-color: #1c1c1c; color: #ffffff; padding: 12px 35px; font-size: 14px; font-weight: bold; border-radius: 8px; text-decoration: none;">View on Booking Partner</a>
                    </div>
                </div>

                <div style="background-color: #fafaf9; text-align: center; padding: 20px; font-size: 11px; color: #a0a095; border-top: 1px solid #e4e4e0;">
                    This is an automated reservation voucher sent by Sara Travel chatbot.
                </div>
            </div>
        </body>
        </html>
        """

email_service = EmailService()
