import ftplib
import json
import os
import re
import socket
import sys
import time
from getpass import getpass
import cv2
import types
from picamera2 import Picamera2
from io import BytesIO
import threading
from datetime import datetime

CONFIG_FILE = "config.json"
DEFAULT_FTP_HOST = "192.168.3.18"
DEFAULT_FTP_PORT = 21
FTP_USERNAME = "Admin"
# WARNING 入力すべき
FTP_PASSWORD = "Admin"
REMOTE_FILENAME = "IMG1.png"
MAX_IMAGE_SIZE_BYTES = 1 * 1024 * 1024;
WAIT_SECONDS = 0.5

frame = None

try:
	import SSLSocket
except ImportError:
	_SSLSocket = None
else:
	_SSLSocket = ssl.SSLSocket

# fix storbinary

def new_storbinary(self, cmd, fp, blocksize=8192, callback=None, rest=None):
	self.voidcmd('TYPE I')
	with self.transfercmd(cmd, rest) as conn:
		while True:
			buf = fp.read(blocksize)
			if not buf:
				break
			conn.sendall(buf)
			if callback:
				callback(buf)
		if _SSLSocket is not None and isinstance(conn, _SSLSocket):
			pass
	return self.voidresp()

def is_valid_ipv4(ip: str) -> bool:
	if not isinstance(ip, str):
		return False
	pattern = r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$"
	return re.match(pattern, ip) is not None

def is_valid_port(port) -> bool:
	try:
		port = int(port)
		return 1 <= port <= 65535
	except Exception:
		return False

def load_config():
	config = {
		"ftp_host": DEFAULT_FTP_HOST,
		"ftp_port": DEFAULT_FTP_PORT,
	}
	if not os.path.exists(CONFIG_FILE):
		print(f"[WARN] {CONFIG_FILE}が見つかりません. デフォルト設定を使用します.")
		return config
	try:
		with open(CONFIG_FILE, "r", encoding="utf-8") as f:
			user_config = json.load(f)
		host = user_config.get("ftp_host", DEFAULT_FTP_HOST)
		port = user_config.get("ftp_port", DEFAULT_FTP_PORT)
		if is_valid_ipv4(host):
			config["ftp_host"] = host
			print(f"[INFO] 設定ファイルよりftp_hostを読み出しました")
		else:
			print(f"[WARN] ftp_hostが不正です: {host} -> デフォルト  {DEFAULT_FTP_HOST} を使用")
		if is_valid_port(port):
			config["ftp_port"] = port
			print(f"[INFO] 設定ファイルよりftp_portを読み出しました")
		else:
			print(f"[WARN] ftp_portが不正です: {port} -> デフォルト  {DEFAULT_FTP_PORT} を使用")
	except Exception as e:
		print(f"[ERROR] 設定ファイルの読み込みに失敗: {e}")
		print(f"[WARN]) デフォルト設定を使用します.")
	return config

def get_ftp_connection(host, port, username, password):
	ftp = None
	state_local = False
	print(f"[INFO] FTP接続を試行: {host}:{port}")
	try:
		sock = socket.create_connection((host, port))
		sock.close()
		print(f"[INFO] TCP接続確認OK")
	except Exception as e:
		raise ConnectionError(f"[WARN] TCP接続確認に失敗しました: {e}")
	try:
		ftp = ftplib.FTP(timeout=10)
		ftp.set_pasv(False)
		ftp.connect(host=host, port=port)
		ftp.login(username, passwd=password)
		ftp.storbinary = types.MethodType(new_storbinary, ftp)
		print(f"[INFO] FTPログインOK")
		state_local = True
	except Exception as e:
		raise ConnectionError(f"[WARN] FTPログインに失敗しました: {e}")
		state_local = False
	return ftp

def ensure_remote_dir(ftp):
	remote_image_dir = "Package1"
	try:
		ftp.cwd(remote_image_dir)
	except ftplib.error_perm:
		ftp.mkd(remote_image_dir)
		ftp.cwd(remote_image_dir)
		print(f"[INFO] ディレクトリ作成: {remote_image_dir}")
	return remote_image_dir

def upload_image(ftp, remote_dir, image_data):
	state_local = False
	if len(image_data) > MAX_IMAGE_SIZE_BYTES:
		print(f"[WARN] 画像サイズが1MBを超えたため送信しません: {len(image_data)} bytes")
		return state_local
	remote_path = f"{remote_dir.rstrip('/')}/{REMOTE_FILENAME}"
	success, buffer = cv2.imencode(".png", image_data)
	if not success:
		print(f"[INFO] エンコード失敗, 再試行します")
		return state_local
	try:
		bio = BytesIO(buffer.tobytes())
		ftp.storbinary("STOR IMG1.png", bio)
		print(f"[INFO] {datetime.now()} 転送完了: {remote_path}")
		state_local = True
		return state_local
	except Exception as e:
		print(f"[ERROR] 転送エラー: {e}")
		print(f"[INFO] 転送を再開します...")
		try:
			ftp.close()
		except Exception:
			pass
		return state_local

def image_thread():
	global frame
	picam2 = Picamera2()
	cam_config = picam2.create_preview_configuration(main={"format": "RGB888", "size": (640, 480)})
	picam2.configure(cam_config)
	picam2.start()
	time.sleep(2)
	while True:
		frame = picam2.capture_array()
		if frame is None:
			print(f"[INFO] 画像が存在しないため描画をスキップしました")
		else:
			cv2.imshow("Camera", frame)
			cv2.waitKey(1)

def main():
	global frame
	config = load_config()
	state = False
	ftp = None
	t1 = threading.Thread(target=image_thread, daemon=True)
	t1.start()

	while True:
		try:
			if state == False:
				ftp = get_ftp_connection(
					config["ftp_host"],
					config["ftp_port"],
					FTP_USERNAME,
					FTP_PASSWORD
				)
				remote_dir = ensure_remote_dir(ftp)
			if ftp is not None:
				state = True
			if frame is None:
				print(f"[INFO] 画像が存在しないため転送をスキップしました")
			else:
				state = upload_image(ftp, remote_dir, frame)
			time.sleep(WAIT_SECONDS)
		except KeyboardInterrupt:
			print(f"\n[INFO] ユーザーにより終了しました")
			ftp.close()
			break
		except Exception as e:
			print(f"[ERROR] {e}")
			print(f"[INFO] 処理を継続します")
			state = False

if __name__ == "__main__":
	main()
