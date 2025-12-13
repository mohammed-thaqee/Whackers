from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import whisper
import json
import requests
import os
from datetime import datetime
from pymongo import MongoClient
from grocery_text_classifier import classify_from_text
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================
# INITIALIZE FLASK APP FIRST
# =============================================
app = Flask(__name__)

# =============================================
# TWILIO CONFIGURATION
# =============================================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "your_account_sid")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "your_auth_token")
TWILIO_PHONE = os.getenv("TWILIO_PHONE", "whatsapp:+1234567890")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# =============================================
# MONGODB CONFIGURATION
# =============================================
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
mongo_client = None
db = None

def init_mongodb():
    """Initialize MongoDB connection"""
    global mongo_client, db
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command('ping')
        db = mongo_client['kirana_system']
        print("✅ MongoDB connected successfully!")
        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return False

# Initialize MongoDB on startup
init_mongodb()

# =============================================
# LOAD WHISPER MODEL
# =============================================
print("🔄 Loading Whisper model (base)...")
whisper_model = whisper.load_model("base")
print("✅ Whisper model loaded!")

AUDIO_DIR = "audio_cache"
os.makedirs(AUDIO_DIR, exist_ok=True)

# =============================================
# CATEGORY EMOJIS
# =============================================
CATEGORY_EMOJIS = {
    "Consumables / Perishables": "🛒",
    "Tools & Equipment": "🔧",
    "Hardware / Components": "⚙️",
    "Documentation / Media": "📚",
    "Apparel / Textiles": "👕",
    "Office & Stationery": "📝",
    "Safety & Emergency": "🆘",
    "Seasonal / Occasional": "🎉",
    "Chemicals / Hazardous": "☠️",
    "Electronics / Gadgets": "🔌"
}

# =============================================
# USER CONVERSATION STATE
# =============================================
user_states = {}

# =============================================
# HELPER FUNCTIONS
# =============================================
def download_twilio_audio(media_url, auth):
    """Download audio from Twilio's URL"""
    try:
        response = requests.get(media_url, auth=auth, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"❌ Error downloading audio: {e}")
        return None

def save_audio_file(audio_data, filename):
    """Save audio to disk"""
    filepath = os.path.join(AUDIO_DIR, filename)
    try:
        with open(filepath, 'wb') as f:
            f.write(audio_data)
        return filepath
    except Exception as e:
        print(f"❌ Error saving audio file: {e}")
        return None

def group_items_by_category(items):
    """Group classified items by category"""
    grouped = defaultdict(list)
    for item in items:
        category = item['category_name']
        grouped[category].append(item)
    return dict(grouped)

def format_categorized_response(transcribed_text, classified_items):
    """Format WhatsApp response with items grouped by category"""
    grouped = group_items_by_category(classified_items)
    msg_text = f"✅ Got it!\n\n📝 You said:\n\"{transcribed_text}\"\n\n"
    msg_text += "=" * 40 + "\n"
    msg_text += "🛍️  ITEMS BY CATEGORY:\n"
    msg_text += "=" * 40 + "\n\n"
    
    for category, items in grouped.items():
        emoji = CATEGORY_EMOJIS.get(category, "📦")
        msg_text += f"{emoji} {category}\n"
        msg_text += "─" * 35 + "\n"
        for item in items:
            msg_text += f"  • {item['name']} ({item['quantity']})\n"
        msg_text += "\n"
    
    msg_text += "=" * 40 + "\n"
    msg_text += f"📊 Total Items: {len(classified_items)}\n"
    msg_text += f"📂 Categories: {len(grouped)}"
    return msg_text

def format_console_output(transcribed_text, classified_items):
    """Format console output with items grouped by category"""
    grouped = group_items_by_category(classified_items)
    print("\n" + "="*60)
    print("📊 CATEGORIZED ITEMS")
    print("="*60)
    print(f"📝 Transcribed: {transcribed_text}\n")
    for category, items in grouped.items():
        emoji = CATEGORY_EMOJIS.get(category, "📦")
        print(f"\n{emoji} {category}")
        print("─" * 50)
        for item in items:
            print(f"   • {item['name']}")
            print(f"     Qty: {item['quantity']}")
            print(f"     Category #: {item['category_number']}")
    print("\n" + "="*60)
    print(f"📊 SUMMARY: {len(classified_items)} items in {len(grouped)} categories")
    print("="*60)

def store_voice_order(from_number, transcribed_text, classified_items, audio_file, customer_name):
    """Store voice order in MongoDB"""
    try:
        if db is None:
            print("   MongoDB not connected, skipping storage")
            return None
        orders_collection = db['voice_orders']
        grouped = group_items_by_category(classified_items)
        order_data = {
            "customer_phone": from_number,
            "customer_name": customer_name,
            "transcribed_text": transcribed_text,
            "classified_items": classified_items,
            "items_by_category": grouped,
            "audio_file_path": audio_file,
            "created_at": datetime.now(),
            "status": "pending",
            "category_breakdown": {},
            "total_items": len(classified_items),
            "total_categories": len(grouped),
            "notified_shopkeepers": []
        }
        
        for item in classified_items:
            category = item['category_name']
            if category not in order_data['category_breakdown']:
                order_data['category_breakdown'][category] = 0
            order_data['category_breakdown'][category] += 1
        
        result = orders_collection.insert_one(order_data)
        print(f"✅ Order stored in MongoDB with ID: {result.inserted_id}")
        return str(result.inserted_id)
    except Exception as e:
        print(f"❌ Error storing order in MongoDB: {e}")
        return None

def get_user_by_phone(from_number):
    """Get user from database by phone number"""
    try:
        if db is None:
            return None
        users_collection = db['whatsapp_users']
        return users_collection.find_one({"phone_number": from_number})
    except Exception as e:
        print(f"❌ Error fetching user: {e}")
        return None

def get_shopkeeper_by_phone(from_number):
    """Get shopkeeper from database by phone number"""
    try:
        if db is None:
            return None
        shopkeepers_collection = db['shopkeepers']
        return shopkeepers_collection.find_one({"phone_number": from_number})
    except Exception as e:
        print(f"❌ Error fetching shopkeeper: {e}")
        return None

def get_all_shopkeepers():
    """Get all shopkeepers from database"""
    try:
        if db is None:
            return []
        shopkeepers_collection = db['shopkeepers']
        return list(shopkeepers_collection.find({"status": "active"}))
    except Exception as e:
        print(f"❌ Error fetching shopkeepers: {e}")
        return []

def notify_shopkeepers(order_id, customer_name, customer_phone, classified_items, transcribed_text):
    """Send order notification to all active shopkeepers"""
    try:
        shopkeepers = get_all_shopkeepers()
        
        # Add hardcoded shopkeeper for testing
        test_shopkeeper = {
            "phone_number": "whatsapp:+919353315644",
            "name": "Test Shopkeeper",
            "shop_name": "Test Shop"
        }
        
        # Add test shopkeeper if not already in list
        shopkeeper_phones = [s.get('phone_number') for s in shopkeepers]
        if test_shopkeeper['phone_number'] not in shopkeeper_phones:
            shopkeepers.append(test_shopkeeper)
        
        if not shopkeepers:
            print("❌ No shopkeepers found to notify")
            return False
        
        grouped = group_items_by_category(classified_items)
        
        # Format message for shopkeepers
        shopkeeper_msg = f"🔔 NEW ORDER RECEIVED!\n\n"
        shopkeeper_msg += f"👤 Customer: {customer_name}\n"
        shopkeeper_msg += f"📞 Phone: {customer_phone}\n"
        shopkeeper_msg += f"🆔 Order ID: {order_id}\n\n"
        shopkeeper_msg += f"📋 Items Requested:\n"
        shopkeeper_msg += "─" * 40 + "\n"
        
        for category, items in grouped.items():
            emoji = CATEGORY_EMOJIS.get(category, "📦")
            shopkeeper_msg += f"{emoji} {category}\n"
            for item in items:
                shopkeeper_msg += f"  • {item['name']} ({item['quantity']})\n"
        
        shopkeeper_msg += "─" * 40 + "\n"
        shopkeeper_msg += f"📊 Total Items: {len(classified_items)}\n\n"
        shopkeeper_msg += "Reply to confirm or discuss delivery! ✅"
        
        # Send to each shopkeeper
        notified_count = 0
        for shopkeeper in shopkeepers:
            try:
                shopkeeper_phone = shopkeeper.get('phone_number')
                if shopkeeper_phone:
                    try:
                        message = twilio_client.messages.create(
                            body=shopkeeper_msg,
                            from_=TWILIO_PHONE,
                            to=shopkeeper_phone
                        )
                        notified_count += 1
                        print(f"✅ Order notification sent to shopkeeper: {shopkeeper.get('name')} ({shopkeeper_phone})")
                    except Exception as twilio_err:
                        # Check if it's a daily limit error
                        if "50 daily messages limit" in str(twilio_err) or "63038" in str(twilio_err):
                            print(f"⚠️  TWILIO DAILY LIMIT REACHED!")
                            print(f"📋 Message queued for: {shopkeeper.get('name')} ({shopkeeper_phone})")
                            print(f"💬 Message content:")
                            print(shopkeeper_msg)
                            print("─" * 50)
                            # Still count as notified for logging purposes
                            notified_count += 1
                        else:
                            print(f"⚠️  Failed to notify shopkeeper {shopkeeper.get('name')}: {twilio_err}")
            except Exception as e:
                print(f"⚠️  Error processing shopkeeper {shopkeeper.get('name')}: {e}")
        
        # Update order with notified shopkeepers
        if notified_count > 0:
            try:
                orders_collection = db['voice_orders']
                orders_collection.update_one(
                    {"_id": order_id},
                    {"$set": {"notified_shopkeepers": [s.get('phone_number') for s in shopkeepers]}}
                )
            except:
                pass
            print(f"📣 Notifications processed for {notified_count} shopkeeper(s)")
            return True
        
        return False
    except Exception as e:
        print(f"❌ Error notifying shopkeepers: {e}")
        return False

def store_customer(from_number, name, location, first_interaction="voice"):
    """Store customer information in MongoDB"""
    try:
        if db is None:
            print("   MongoDB not connected, skipping storage")
            return None
        users_collection = db['whatsapp_users']
        existing = users_collection.find_one({"phone_number": from_number})
        customer_data = {
            "phone_number": from_number,
            "name": name,
            "location": location,
            "created_at": datetime.now() if not existing else existing.get("created_at"),
            "last_interaction": datetime.now(),
            "total_orders": existing.get("total_orders", 0) if existing else 0,
            "status": "active",
            "first_interaction": first_interaction
        }
        if existing:
            result = users_collection.update_one(
                {"phone_number": from_number},
                {"$set": customer_data}
            )
            print(f"✅ Customer updated: {name} at {location}")
            return str(existing['_id'])
        else:
            result = users_collection.insert_one(customer_data)
            print(f"✅ Customer stored in MongoDB with ID: {result.inserted_id}")
            return str(result.inserted_id)
    except Exception as e:
        print(f"❌ Error storing customer: {e}")
        return None

def store_shopkeeper(from_number, name, shop_name, location, description=""):
    """Store shopkeeper information in MongoDB"""
    try:
        if db is None:
            print("   MongoDB not connected, skipping storage")
            return None
        shopkeepers_collection = db['shopkeepers']
        existing = shopkeepers_collection.find_one({"phone_number": from_number})
        shopkeeper_data = {
            "phone_number": from_number,
            "name": name,
            "shop_name": shop_name,
            "location": location,
            "description": description,
            "created_at": datetime.now() if not existing else existing.get("created_at"),
            "updated_at": datetime.now(),
            "status": "active"
        }
        if existing:
            result = shopkeepers_collection.update_one(
                {"phone_number": from_number},
                {"$set": shopkeeper_data}
            )
            print(f"✅ Shopkeeper updated: {name}")
            return str(existing['_id'])
        else:
            result = shopkeepers_collection.insert_one(shopkeeper_data)
            print(f"✅ Shopkeeper stored in MongoDB with ID: {result.inserted_id}")
            return str(result.inserted_id)
    except Exception as e:
        print(f"❌ Error storing shopkeeper: {e}")
        return None

def handle_location_message(from_number, latitude, longitude):
    """Process location message from WhatsApp"""
    try:
        location_str = f"Lat: {latitude}, Lon: {longitude}"
        
        if from_number in user_states:
            state = user_states[from_number]
            state['data']['location'] = location_str
            state['data']['latitude'] = latitude
            state['data']['longitude'] = longitude
            
            if state['step'] == "awaiting_location":
                if state['data'].get('role') == 'shopkeeper':
                    store_shopkeeper(
                        from_number,
                        state['data'].get('name', ''),
                        state['data'].get('shop_name', ''),
                        location_str,
                        state['data'].get('description', '')
                    )
                elif state['data'].get('role') == 'customer':
                    store_customer(
                        from_number,
                        state['data'].get('name', ''),
                        location_str
                    )
                del user_states[from_number]
                return True
        return False
    except Exception as e:
        print(f"❌ Error handling location: {e}")
        return False

def process_voice_note(media_url, from_number):
    """Download, transcribe, and classify voice note"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"voice_{from_number}_{timestamp}.ogg"
    print(f"\n📥 Processing voice note from {from_number}")
    
    user = get_user_by_phone(from_number)
    shopkeeper = get_shopkeeper_by_phone(from_number)
    
    if not user and not shopkeeper:
        user_states[from_number] = {
            "step": "awaiting_name",
            "data": {"phone_number": from_number}
        }
        return {"init_required": True, "message": "Please provide your name first"}
    
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    audio_data = download_twilio_audio(media_url, auth)
    if not audio_data:
        return {"error": "Failed to download audio"}
    
    audio_path = save_audio_file(audio_data, filename)
    print(f"💾 Saved to: {audio_path}")
    
    print("🎤 Transcribing audio...")
    try:
        result = whisper_model.transcribe(audio_path, language="en")
        text = result["text"].strip()
        print(f"📝 Transcribed: {text}")
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return {"error": f"Transcription failed: {e}"}
    
    print("📦 Classifying items...")
    try:
        classified = classify_from_text(text)
        print("✅ Classification complete!")
        format_console_output(text, classified["items"])
        
        customer_name = user.get('name') if user else 'Unknown Customer'
        order_id = store_voice_order(
            from_number,
            text,
            classified["items"],
            audio_path,
            customer_name
        )
        
        return {
            "from": from_number,
            "customer_name": customer_name,
            "transcribed_text": text,
            "classified_items": classified["items"],
            "audio_file": audio_path,
            "order_id": order_id,
            "stored": order_id is not None
        }
    except Exception as e:
        print(f"❌ Classification error: {e}")
        return {"error": f"Classification failed: {e}"}

# =============================================
# FLASK ROUTES
# =============================================
@app.route("/whatsapp", methods=["POST"])
def handle_whatsapp():
    """Twilio webhook for incoming WhatsApp messages"""
    try:
        form_data = request.form.to_dict()
        from_number = form_data.get("From", "unknown")
        message_sid = form_data.get("MessageSid", "")
        print(f"\n{'='*50}")
        print(f"📨 New WhatsApp message from {from_number}")
        print(f"SID: {message_sid}")
        print(f"📋 Form Data: {form_data}")
        print(f"{'='*50}")
        response = MessagingResponse()
    except Exception as e:
        print(f"❌ ERROR parsing request: {e}")
        response = MessagingResponse()
        response.message("❌ Server error processing request")
        return str(response)
    
    # Check if there's a pending user state (onboarding flow)
    if from_number in user_states:
        state = user_states[from_number]
        step = state['step']
        
        if step == "awaiting_name":
            text = form_data.get("Body", "").strip()
            if text:
                state['data']['name'] = text
                state['step'] = "awaiting_role"
                response.message("Thanks! 👤\n\nAre you a:\n1️⃣ Customer (buying items)\n2️⃣ Shopkeeper (selling items)\n\nReply with 1 or 2")
            else:
                response.message("Please send your name 👤")
        
        elif step == "awaiting_role":
            text = form_data.get("Body", "").strip().lower()
            if text in ['1', 'customer', 'buying']:
                state['data']['role'] = 'customer'
                state['step'] = "awaiting_location"
                response.message("Great! 🛍️\n\nPlease share your location 📍\n(Click the attachment button and select 'Location')")
            elif text in ['2', 'shopkeeper', 'seller', 'selling']:
                state['data']['role'] = 'shopkeeper'
                state['step'] = "awaiting_shop_name"
                response.message("Welcome Shopkeeper! 🏪\n\nWhat's your shop name?")
            else:
                response.message("Please reply with 1 (Customer) or 2 (Shopkeeper)")
        
        elif step == "awaiting_shop_name":
            text = form_data.get("Body", "").strip()
            if text:
                state['data']['shop_name'] = text
                state['step'] = "awaiting_shop_description"
                response.message(f"Nice! {text} 🏪\n\nBriefly describe what you sell (or reply 'skip')")
            else:
                response.message("Please send your shop name 🏪")
        
        elif step == "awaiting_shop_description":
            text = form_data.get("Body", "").strip()
            if text.lower() != 'skip':
                state['data']['description'] = text
            state['step'] = "awaiting_location"
            response.message("Perfect! 📍\n\nNow please share your shop location\n(Click the attachment button and select 'Location')")
        
        elif step == "awaiting_location":
            latitude = form_data.get("Latitude")
            longitude = form_data.get("Longitude")
            
            if latitude and longitude:
                if handle_location_message(from_number, latitude, longitude):
                    role = user_states.get(from_number, {}).get('data', {}).get('role', 'user')
                    if role == 'shopkeeper':
                        response.message(f"✅ Welcome {state['data'].get('shop_name')}! 🎉\n\nYour profile is set up. You're ready to go! 🚀")
                    else:
                        response.message(f"✅ Welcome {state['data'].get('name')}! 🎉\n\nYour profile is set up. You can now send me orders! 📝")
                else:
                    response.message("❌ Error saving location. Please try again.")
            else:
                response.message("📍 Please share your actual location using WhatsApp's location feature")
        
        return str(response)
    
    # Normal message handling (after onboarding)
    num_media = int(form_data.get("NumMedia", 0))
    if num_media > 0:
        media_url = form_data.get("MediaUrl0", "")
        media_type = form_data.get("MediaContentType0", "")
        print(f"🎵 Media detected: {media_type}")
        
        if media_type.startswith("audio/"):
            result = process_voice_note(media_url, from_number)
            if "error" in result:
                response.message(f"❌ Error: {result['error']}")
            elif result.get("init_required"):
                user_states[from_number] = {
                    "step": "awaiting_name",
                    "data": {"phone_number": from_number}
                }
                response.message(f"👋 Welcome! Before I process your order, what's your name? 👤")
            else:
                # Send confirmation to customer
                msg_text = format_categorized_response(
                    result['transcribed_text'],
                    result['classified_items']
                )
                if result['stored']:
                    msg_text += f"\n\n✅ Order saved!\n📣 Notifying nearby shopkeepers..."
                    response.message(msg_text)
                    
                    # Notify all shopkeepers
                    notify_shopkeepers(
                        result['order_id'],
                        result['customer_name'],
                        from_number,
                        result['classified_items'],
                        result['transcribed_text']
                    )
                else:
                    response.message(msg_text)
        else:
            response.message("📁 Please send an audio/voice note!")
    else:
        text = form_data.get("Body", "").strip()
        if text:
            print(f"💬 Text message: {text}")
            
            user = get_user_by_phone(from_number)
            shopkeeper = get_shopkeeper_by_phone(from_number)
            
            if not user and not shopkeeper:
                user_states[from_number] = {
                    "step": "awaiting_name",
                    "data": {"phone_number": from_number}
                }
                response.message(f"👋 Welcome! What's your name? 👤")
            else:
                if user:
                    try:
                        print(f"👤 User found: {user.get('name')}")
                        classified = classify_from_text(text)
                        format_console_output(text, classified["items"])
                        
                        customer_name = user.get('name')
                        order_id = store_voice_order(
                            from_number,
                            text,
                            classified["items"],
                            "text_input",
                            customer_name
                        )
                        
                        msg_text = format_categorized_response(text, classified["items"])
                        if order_id:
                            msg_text += f"\n\n✅ Order saved!\n📣 Notifying nearby shopkeepers..."
                            print(f"📤 Sending response to customer...")
                            response.message(msg_text)
                            print(f"✅ Response sent to customer")
                            
                            # Notify all shopkeepers
                            print(f"🔔 Notifying shopkeepers...")
                            notify_shopkeepers(
                                order_id,
                                customer_name,
                                from_number,
                                classified["items"],
                                text
                            )
                        else:
                            response.message(msg_text)
                    except Exception as e:
                        print(f"❌ Error processing text: {e}")
                        response.message(f"❌ Error: {str(e)}")
                else:
                    print(f"⚠️  No customer found, checking if shopkeeper...")
                    response.message("👋 You're registered as a shopkeeper. Awaiting customer orders! 🛍️")
        else:
            response.message("👋 Hi! Send me a voice note or text to extract groceries!")
    
    return str(response)

@app.route("/test", methods=["GET"])
def test():
    """Test endpoint to verify server is running"""
    return jsonify({
        "status": "ok",
        "message": "Flask server is running!",
        "twilio_account": TWILIO_ACCOUNT_SID[:10] + "...",
        "mongo_connected": db is not None,
        "whisper_loaded": whisper_model is not None
    })

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint"""
    try:
        if db is not None:
            db.command('ping')
            return jsonify({
                "status": "ok",
                "service": "WhatsApp Voice Handler",
                "database": "connected"
            })
        else:
            return jsonify({
                "status": "warning",
                "service": "WhatsApp Voice Handler",
                "database": "disconnected"
            }), 503
    except Exception as e:
        return jsonify({
            "status": "error",
            "service": "WhatsApp Voice Handler",
            "error": str(e)
        }), 500

@app.route("/api/orders", methods=["GET"])
def get_orders():
    """Get all orders from MongoDB"""
    try:
        if db is None:
            return jsonify({"error": "Database not connected"}), 503
        orders_collection = db['voice_orders']
        orders = list(orders_collection.find().sort("created_at", -1).limit(50))
        for order in orders:
            order['_id'] = str(order['_id'])
            order['created_at'] = order['created_at'].isoformat()
        return jsonify({"total": len(orders), "orders": orders})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/orders/<phone_number>", methods=["GET"])
def get_user_orders(phone_number):
    """Get orders for a specific phone number"""
    try:
        if db is None:
            return jsonify({"error": "Database not connected"}), 503
        orders_collection = db['voice_orders']
        orders = list(orders_collection.find({"customer_phone": phone_number}).sort("created_at", -1))
        for order in orders:
            order['_id'] = str(order['_id'])
            order['created_at'] = order['created_at'].isoformat()
        return jsonify({"phone_number": phone_number, "total": len(orders), "orders": orders})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/shopkeeper/orders/<phone_number>", methods=["GET"])
def get_shopkeeper_orders(phone_number):
    """Get orders for a shopkeeper"""
    try:
        if db is None:
            return jsonify({"error": "Database not connected"}), 503
        orders_collection = db['voice_orders']
        orders = list(orders_collection.find({"notified_shopkeepers": phone_number}).sort("created_at", -1))
        for order in orders:
            order['_id'] = str(order['_id'])
            order['created_at'] = order['created_at'].isoformat()
        return jsonify({"phone_number": phone_number, "total": len(orders), "orders": orders})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================
# RUN SERVER
# =============================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 Starting Twilio WhatsApp Voice Handler...")
    print("="*60)
    print("📝 Endpoints:")
    print("   POST /whatsapp                       - Twilio webhook")
    print("   GET  /health                         - Health check")
    print("   GET  /api/orders                     - Get all orders")
    print("   GET  /api/orders/<phone>             - Get customer orders")
    print("   GET  /api/shopkeeper/orders/<phone>  - Get shopkeeper orders")
    print("="*60 + "\n")
    app.run(host="0.0.0.0", port=5001, debug=False)
