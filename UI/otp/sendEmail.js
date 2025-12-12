const SibApiV3Sdk = require('sib-api-v3-sdk');

const client = SibApiV3Sdk.ApiClient.instance;
client.authentications['api-key'].apiKey = process.env.BREVO_API_KEY;

async function sendOTPEmail(toEmail, otp) {
  const apiInstance = new SibApiV3Sdk.TransactionalEmailsApi();
  const email = {
    sender: { email: process.env.SENDER_EMAIL },
    to: [{ email: toEmail }],
    subject: "Your OTP Code",
    htmlContent: `
      <div style="font-family: Arial, sans-serif; padding: 12px;">
        <h2>Your OTP Code</h2>
        <p>Your one-time password is:</p>
        <h1 style="letter-spacing:6px;">${otp}</h1>
        <p>This OTP is valid for 5 minutes.</p>
      </div>
    `
  };

  return apiInstance.sendTransacEmail(email);
}

module.exports = sendOTPEmail;
