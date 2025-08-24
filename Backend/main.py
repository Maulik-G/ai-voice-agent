# main.py - The final backend code for PythonAnywhere

import os
import json
import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import firebase_admin
from firebase_admin import credentials, auth, firestore

# --- INITIALIZATION ---

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---

# Gemini API Key (set as environment variable on PythonAnywhere)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

# Firebase Admin SDK Setup (set as environment variable on PythonAnywhere)
# The content of the JSON key file you downloaded from Firebase.
FIREBASE_CREDS_JSON = os.environ.get('FIREBASE_CREDS')
db = None # Initialize db as None
if FIREBASE_CREDS_JSON:
    try:
        creds_dict = json.loads(FIREBASE_CREDS_JSON)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error initializing Firebase Admin SDK: {e}")
else:
    print("FIREBASE_CREDS environment variable not found.")

# Daily request limit for free users
DAILY_LIMIT = 25

# --- API ENDPOINT ---

@app.route('/ask', methods=['POST'])
def ask_ai():
    # 1. VALIDATE REQUEST AND AUTHENTICATION
    if not db or not GEMINI_API_KEY:
        return jsonify({"error": "Server is not configured correctly."}), 500

    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "Unauthorized: Missing or invalid token."}), 401

    id_token = auth_header.split('Bearer ')[1]
    
    try:
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']
    except Exception as e:
        return jsonify({"error": f"Unauthorized: Invalid token. {e}"}), 401

    data = request.get_json()
    if 'history' not in data:
        return jsonify({"error": "Invalid request: 'history' is required."}), 400
    
    conversation_history = data['history']

    # 2. CHECK USER'S USAGE LIMIT IN FIRESTORE
    today_str = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    user_ref = db.collection('users').document(uid)
    
    try:
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            last_request_date = user_data.get('lastRequestDate', '')
            request_count = user_data.get('requestCount', 0)

            if last_request_date == today_str:
                if request_count >= DAILY_LIMIT:
                    return jsonify({"error": "You have reached your daily limit of questions."}), 429 # Too Many Requests
                user_ref.update({'requestCount': firestore.Increment(1)})
            else:
                # It's a new day, reset the counter
                user_ref.set({'lastRequestDate': today_str, 'requestCount': 1})
        else:
            # First time user, create their document
            user_ref.set({'lastRequestDate': today_str, 'requestCount': 1})
    except Exception as e:
        return jsonify({"error": f"Database error: {e}"}), 500

    # 3. CALL GEMINI API (if limit not reached)
    payload = {"contents": conversation_history}
    try:
        response = requests.post(GEMINI_API_URL, json=payload)
        response.raise_for_status()
        result = response.json()
        ai_response_text = result['candidates'][0]['content']['parts'][0]['text']
        return jsonify({"text": ai_response_text})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"AI service connection error: {e}"}), 502
    except (KeyError, IndexError):
        return jsonify({"error": "Invalid response from AI service."}), 500

# Health check endpoint
@app.route('/')
def index():
    return "AI Voice Agent Backend is running."

