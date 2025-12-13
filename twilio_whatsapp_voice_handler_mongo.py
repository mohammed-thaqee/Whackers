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

app = Flask(__name__)

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
    "Chemicals / Hazardous": "⚠️",
    "Electronics / Gadgets": "🔌"
}

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
    
    # Display each category with its emoji
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


def store_voice_order(from_number, transcribed_text, classified_items, audio_file):
    """Store voice order in MongoDB"""
    try:
        if db is None:
            print("⚠️  MongoDB not connected, skipping storage")
            return None

        orders_collection = db['voice_orders']
        
        grouped = group_items_by_category(classified_items)
        
        order_data = {
            "phone_number": from_number,
            "transcribed_text": transcribed_text,
            "classified_items": classified_items,
            "items_by_category": grouped,
            "audio_file_path": audio_file,
            "created_at": datetime.now(),
            "status": "pending",
            "category_breakdown": {},
            "total_items": len(classified_items),
            "total_categories": len(grouped)
        }

        # Count items by category
        for item in classified_items:
            category = item['category_name']
            if category not in order_data['category_breakdown']:
                order_data['category_breakdown'][category] = 0
            order_data['category_breakdown'][category] += 1

        # Insert into MongoDB
        result = orders_collection.insert_one(order_data)
        print(f"✅ Order stored in MongoDB with ID: {result.inserted_id}")
        
        return str(result.inserted_id)

    except Exception as e:
        print(f"❌ Error storing order in MongoDB: {e}")
        return None


def store_user_if_not_exists(from_number):
    """Create user if doesn't exist"""
    try:
        if db is None:
            return None

        users_collection = db['whatsapp_users']
        
        # Check if user exists
        existing_user = users_collection.find_one({"phone_number": from_number})
        
        if existing_user:
            # Update last interaction
            users_collection.update_one(
                {"phone_number": from_number},
                {"$set": {"last_interaction": datetime.now()}}
            )
            return existing_user
        else:
            # Create new user
            user_data = {
                "phone_number": from_number,
                "created_at": datetime.now(),
                "last_interaction": datetime.now(),
                "total_orders": 0,
                "status": "active"
            }
            result = users_collection.insert_one(user_data)
            print(f"👤 New user created: {from_number}")
            return user_data

    except Exception as e:
        print(f"❌ Error managing user: {e}")
        return None


def process_voice_note(media_url, from_number):
    """Download, transcribe, and classify voice note"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"voice_{from_number}_{timestamp}.ogg"
    
    print(f"\n📥 Processing voice note from {from_number}")
    
    # Create/update user
    store_user_if_not_exists(from_number)
    
    # Download audio
    auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    audio_data = download_twilio_audio(media_url, auth)
    
    if not audio_data:
        return {"error": "Failed to download audio"}
    
    # Save file
    audio_path = save_audio_file(audio_data, filename)
    print(f"💾 Saved to: {audio_path}")
    
    # Transcribe
    print("🎤 Transcribing audio...")
    try:
        result = whisper_model.transcribe(audio_path, language="en")
        text = result["text"].strip()
        print(f"📝 Transcribed: {text}")
    except Exception as e:
        print(f"❌ Transcription error: {e}")
        return {"error": f"Transcription failed: {e}"}
    
    # Classify
    print("📦 Classifying items...")
    try:
        classified = classify_from_text(text)
        print("✅ Classification complete!")
        
        # Format and print categorized output
        format_console_output(text, classified["items"])
        
        # Store in MongoDB
        order_id = store_voice_order(
            from_number,
            text,
            classified["items"],
            audio_path
        )
        
        return {
            "from": from_number,
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
    form_data = request.form.to_dict()
    from_number = form_data.get("From", "unknown")
    message_sid = form_data.get("MessageSid", "")
    
    print(f"\n{'='*50}")
    print(f"📨 New WhatsApp message from {from_number}")
    print(f"SID: {message_sid}")
    
    response = MessagingResponse()
    
    # Check if it's a media message (voice note)
    num_media = int(form_data.get("NumMedia", 0))
    
    if num_media > 0:
        media_url = form_data.get("MediaUrl0", "")
        media_type = form_data.get("MediaContentType0", "")
        
        print(f"🎵 Media detected: {media_type}")
        
        # Handle audio/voice notes
        if media_type.startswith("audio/"):
            result = process_voice_note(media_url, from_number)
            
            if "error" in result:
                response.message(f"❌ Error: {result['error']}")
            else:
                # Format response with categorized items
                msg_text = format_categorized_response(
                    result['transcribed_text'],
                    result['classified_items']
                )
                
                if result['stored']:
                    msg_text += f"\n\n✅ Order saved!"
                
                response.message(msg_text)
        else:
            response.message("⚠️ Please send an audio/voice note!")
    else:
        # Text message
        text = form_data.get("Body", "").strip()
        if text:
            print(f"💬 Text message: {text}")
            
            # Create/update user
            store_user_if_not_exists(from_number)
            
            try:
                classified = classify_from_text(text)
                
                # Format and print categorized output
                format_console_output(text, classified["items"])
                
                # Store in MongoDB
                order_id = store_voice_order(
                    from_number,
                    text,
                    classified["items"],
                    "text_input"
                )
                
                # Format response with categorized items
                msg_text = format_categorized_response(text, classified["items"])
                
                if order_id:
                    msg_text += f"\n\n✅ Order saved!"
                
                response.message(msg_text)
            except Exception as e:
                response.message(f"❌ Error: {str(e)}")
                print(f"❌ Error processing text: {e}")
        else:
            response.message("👋 Hi! Send me a voice note or text to extract groceries!")
    
    return str(response)


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
        
        # Convert ObjectId to string
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
        orders = list(orders_collection.find({"phone_number": phone_number}).sort("created_at", -1))
        
        # Convert ObjectId to string
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
    print("   POST /whatsapp           - Twilio webhook")
    print("   GET  /health             - Health check")
    print("   GET  /api/orders         - Get all orders")
    print("   GET  /api/orders/<phone> - Get user orders")
    print("="*60 + "\n")
    
    app.run(host="0.0.0.0", port=5001, debug=False)
