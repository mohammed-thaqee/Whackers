
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client['kirana_system']

print("\n=== ORDERS ===")
orders = db['voice_orders'].find()
for order in orders:
    print(f"\n📋 Order: {order['_id']}")
    print(f"   From: {order['phone_number']}")
    print(f"   Text: {order['transcribed_text']}")
    print(f"   Items: {len(order['classified_items'])}")
    for item in order['classified_items']:
        print(f"      • {item['name']} ({item['quantity']}) - {item['category_name']}")

print("\n\n=== USERS ===")
users = db['whatsapp_users'].find()
for user in users:
    print(f"\n👤 User: {user['phone_number']}")
    print(f"   Created: {user['created_at']}")

