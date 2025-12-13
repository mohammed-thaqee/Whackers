from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
import os

# =============================
# CONFIG
# =============================
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "whatsapp_orders"

# =============================
# INIT
# =============================
app = Flask(__name__)
mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]

users_col = db["users"]
shopkeepers_col = db["shopkeepers"]
orders_col = db["orders"]

# =============================
# USER MANAGEMENT
# =============================
@app.route("/admin/users", methods=["GET"])
def list_users():
    users = list(users_col.find({}, {"_id": 0}))
    return jsonify(users)

@app.route("/admin/users/<phone>", methods=["DELETE"])
def delete_user(phone):
    users_col.delete_one({"phone": phone})
    return jsonify({"status": "deleted", "phone": phone})

# =============================
# SHOPKEEPER MANAGEMENT
# =============================
@app.route("/admin/shopkeepers", methods=["GET"])
def list_shopkeepers():
    shops = list(shopkeepers_col.find({}, {"_id": 0}))
    return jsonify(shops)

@app.route("/admin/shopkeepers", methods=["POST"])
def add_shopkeeper():
    data = request.json
    if not all(k in data for k in ("shopkeeper_id", "name", "phone")):
        return jsonify({"error": "shopkeeper_id, name, phone required"}), 400
    
    shopkeepers_col.insert_one({
        "shopkeeper_id": data["shopkeeper_id"],
        "name": data["name"],
        "phone": data["phone"],
        "status": "active",
        "created_at": datetime.now()
    })
    return jsonify({"status": "added", "shopkeeper_id": data["shopkeeper_id"]})

@app.route("/admin/shopkeepers/<shop_id>", methods=["DELETE"])
def delete_shopkeeper(shop_id):
    shopkeepers_col.delete_one({"shopkeeper_id": shop_id})
    return jsonify({"status": "deleted", "shopkeeper_id": shop_id})

# =============================
# ORDERS MANAGEMENT
# =============================
@app.route("/admin/orders", methods=["GET"])
def list_orders():
    orders = list(orders_col.find({}, {"_id": 0}))
    return jsonify(orders)

@app.route("/admin/orders/<order_id>", methods=["DELETE"])
def delete_order(order_id):
    orders_col.delete_one({"order_id": order_id})
    return jsonify({"status": "deleted", "order_id": order_id})

@app.route("/admin/orders/<order_id>/status", methods=["POST"])
def update_order_status(order_id):
    data = request.json
    new_status = data.get("status")
    if not new_status:
        return jsonify({"error": "status required"}), 400
    
    orders_col.update_one(
        {"order_id": order_id},
        {"$set": {"status": new_status, "updated_at": datetime.now()}}
    )
    return jsonify({"status": "updated", "order_id": order_id, "new_status": new_status})

# =============================
# RUN
# =============================
if __name__ == "__main__":
    print("🚀 Admin panel running on port 5002")
    app.run(host="0.0.0.0", port=5002, debug=True)

