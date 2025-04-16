
import telebot
from flask import Flask, request

API_TOKEN = '8080384318:AAE4Sa5-FWCKxqp7ZiMOUfjmkw6pZ5RlQXg'
bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# Replace with your personal chat ID after you start the bot
MY_CHAT_ID = '1046918142'

@app.route('/lead', methods=['POST'])
def handle_lead():
    data = request.form
    website = data.get('website', 'N/A')
    traffic = data.get('traffic', 'N/A')
    country = data.get('country', 'N/A')
    email = data.get('email', 'N/A')

    message = f"""📥 New Lead Received:

🌐 Website: {website}
📊 Monthly Traffic: {traffic}
🌍 Top Country: {country}
📧 Email: {email}
"""

    bot.send_message(MY_CHAT_ID, message)
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
