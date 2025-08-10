from pyngrok import ngrok
from app import app

# Open an ngrok tunnel on port 5000
public_url = ngrok.connect(5000)
print(f"🌍 Public URL: {public_url}")

# Start Flask app
app.run(host="0.0.0.0", port=5000)