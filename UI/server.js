require("dotenv").config();
const express = require("express");
const cors = require("cors");
const { MongoClient } = require("mongodb");

const generateOTP = require("./otp/otpGenerator");
const sendOTPEmail = require("./otp/sendEmail");

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static("public"));

const PORT = process.env.PORT || 3000;
const MONGO_URI = process.env.MONGO_URI;
const client = new MongoClient(MONGO_URI);

async function connectToDb() {
  try {
    await client.connect();
    console.log("Connected to MongoDB!");
  } catch (err) {
    console.error("Failed to connect to MongoDB", err);
    process.exit(1);
  }
}

connectToDb();

// -------------------------------
// OTP STORE (Temporary)
// -------------------------------
const OTP_STORE = {};


// -------------------------------
// SEND OTP
// -------------------------------
app.post("/send-otp", async (req, res) => {
  try {
    const { role, name, email, phone, password } = req.body;

    if (!role || !name || !email || !phone || !password) {
      return res.json({ success: false, message: "All fields are required." });
    }

    if (!["user", "shopkeeper"].includes(role)) {
      return res.json({ success: false, message: "Invalid role." });
    }

    // Generate OTP
    const otp = generateOTP();

    OTP_STORE[email] = {
      otp,
      expiresAt: Date.now() + 5 * 60 * 1000,
      data: { role, name, email, phone, password }
    };

    await sendOTPEmail(email, otp);
    console.log(`OTP ${otp} sent to ${email}`);

    return res.json({ success: true, message: "OTP sent successfully!" });

  } catch (err) {
    console.error("SEND OTP ERROR:", err);
    return res.json({ success: false, message: "Failed to send OTP." });
  }
});

// -------------------------------
// VERIFY OTP & REGISTER USER
// -------------------------------
app.post("/verify-otp", async (req, res) => {
  try {
    const { email, otp } = req.body;

    if (!email || !otp) {
      return res.json({ success: false, message: "Email & OTP are required." });
    }

    const record = OTP_STORE[email];

    if (!record) {
      return res.json({ success: false, message: "OTP not found. Please request again." });
    }

    if (Date.now() > record.expiresAt) {
      delete OTP_STORE[email];
      return res.json({ success: false, message: "OTP expired." });
    }

    if (record.otp !== otp) {
      return res.json({ success: false, message: "Incorrect OTP." });
    }

    const { role, name, phone, password } = record.data;

    const db = client.db("kirana_system");
    const collection = role === "shopkeeper" ? "shopkeepers" : "users";

    const insertResult = await db.collection(collection).insertOne({
      name,
      email,
      phone,
      password,
      createdAt: new Date()
    });

    console.log("REGISTERED USER:", insertResult.insertedId);

    delete OTP_STORE[email];

    return res.json({
      success: true,
      message: "OTP Verified! Account created.",
      accountId: insertResult.insertedId,
      role
    });

  } catch (err) {
    console.error("VERIFY OTP ERROR:", err);
    return res.json({ success: false, message: "Server error." });
  }
});

// -------------------------------
// LOGIN
// -------------------------------
app.post("/login", async (req, res) => {
  try {
    const { role, email, password } = req.body;

    console.log("LOGIN REQUEST:", req.body);

    if (!role || !email || !password) {
      return res.json({ success: false, message: "All fields are required." });
    }

    const db = client.db("kirana_system");
    const collection = role === "shopkeeper" ? "shopkeepers" : "users";

    console.log("Checking in collection:", collection);

    const user = await db.collection(collection).findOne({ email, password });

    console.log("FOUND USER:", user);

    if (!user) {
      return res.json({ success: false, message: "Invalid email or password." });
    }

    return res.json({
      success: true,
      message: "Login successful",
      user: {
        id: user._id.toString(),
        name: user.name,
        email: user.email,
        phone: user.phone,
        role
      }
    });

  } catch (err) {
    console.error("LOGIN ERROR:", err);
    return res.json({ success: false, message: "Server error." });
  }
});


// -------------------------------
// START SERVER
// -------------------------------
app.listen(PORT, () => {
  console.log(`🚀 Server running on http://localhost:${PORT}`);
});
