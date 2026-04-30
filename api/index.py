from flask import Flask, request, jsonify
from datetime import datetime

app = Flask(__name__)

@app.route('/report', methods=['POST'])
def handle_report():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data"}), 400

        ip = data.get('ip', 'unknown')
        hostname = data.get('hostname', 'unknown')
        exes = data.get('executables', [])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Log ini muncul di Vercel Dashboard > Logs
        print(f"--- LAPORAN BARU [{timestamp}] ---")
        print(f"Host: {hostname} ({ip})")
        print(f"Files: {', '.join(exes)}")
        print("---------------------------------")
        
        return jsonify({"status": "received", "server_time": timestamp}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/')
def home():
    return "Server Receiver Aktif"