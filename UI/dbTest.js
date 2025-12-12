require("dotenv").config();
const { MongoClient } = require("mongodb");

async function test() {
  try {
    const client = new MongoClient(process.env.MONGO_URI);
    await client.connect();
    console.log("Connected to Atlas successfully!");
    await client.close();
  } catch (err) {
    console.error("Connection failed:", err);
  }
}

test();
