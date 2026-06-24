import socket
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple
from datetime import datetime

# --- 定数定義 ---
class SlmpFrameType(IntEnum):
    BIN_REQ_ST = 0x5000  # 3Eフレーム
    BIN_RES_ST = 0xD000
    BIN_REQ_MT = 0x5400  # 4Eフレーム
    BIN_RES_MT = 0xD400

class SlmpCommand(IntEnum):
    DEVICE_READ = 0x0401
    READ_TYPE_NAME = 0x0101

class DeviceType(IntEnum):
    BIT = 1
    WORD = 2

# --- 構造体定義 (DataClasses) ---
@dataclass
class DeviceAddr:
    devidx: int
    addr: int
    length: int
    devcode: int = 0

@dataclass
class LoggingRecord:
    buf: bytearray
    timestamp: float = field(default_factory=time.time)

# --- プロトコル処理クラス ---
class SlmpClient:
    def __init__(self, host: str, port: int, protocol_type: SlmpFrameType):
        self.host = host
        self.port = port
        self.protocol_type = protocol_type
        self.serial = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)

    def _create_header_4e(self, data_len: int, cmd: int, subcmd: int) -> bytes:
        """4Eフレームヘッダ作成 (Binary)"""
        # 自局号などは固定値(0)やデフォルト(0xFF, 0x03FF)を使用
        serial = self.serial
        self.serial = (self.serial + 1) & 0xFFFF
        
        # ヘッダ構造: 
        # 副ヘッダ(2), シリアル(2), 予約(2), 局番(1), ネットワーク(1), 
        # 要求先ユニット(2), マルチドロップ(1), データ長(2), タイマー(2), コマンド(2), サブコマンド(2)
        # ※SLMPバイナリは基本リトルエンディアンだが、副ヘッダはビッグエンディアン
        header_fixed = struct.pack(">H", SlmpFrameType.BIN_REQ_MT) # 副ヘッダ
        header_remain = struct.pack("<HHBBHBH HHH", 
            serial,      # usSerial
            0,           # usSub2
            1,           # uchNetwork
            0x01,        # uchUnitNum
            0x03FF,      # usIONum
            0,           # ucResv
            data_len + 6,# usLength (Timer+Cmd+SubCmd = 6 bytes)
            0,           # usTimer
            cmd,         # usCmd
            subcmd       # usSubCmd
        )
        return header_fixed + header_remain

    def _create_header_3e(self, data_len: int, cmd: int, subcmd: int) -> bytes:
        """3Eフレームヘッダ作成 (Binary)"""
        header_fixed = struct.pack(">H", SlmpFrameType.BIN_REQ_ST)
        header_remain = struct.pack("<BBHBH HHH",
            0,
            0x00,
            0x03FF,
            0,
            data_len + 6,
            0,
            cmd,
            subcmd
        )
        return header_fixed + header_remain

    def device_read_request(self, device: DeviceAddr) -> Optional[List[int]]:
        """deviceRead相当の処理 (SLMP)"""
        # 要求データ作成: 先頭デバイス(3), デバイスコード(1), デバイス点数(2)
        # ※Cコードのcreate_deviceread_dataに相当
        request_data = struct.pack("<I", device.addr)[:3] # 24bit addr
        request_data += struct.pack("<BH", device.devcode, device.length)

        if self.protocol_type == SlmpFrameType.BIN_REQ_MT:
            packet = self._create_header_4e(len(request_data), SlmpCommand.DEVICE_READ, 0x0000) + request_data
        else:
            packet = self._create_header_3e(len(request_data), SlmpCommand.DEVICE_READ, 0x0000) + request_data

        try:
            print(f"[INFO] Request Hex: {packet.hex(' ').upper()}")
            self.sock.sendto(packet, (self.host, self.port))
            # recv_data, _ = self.sock.recvfrom(4096)
            recv_data, _ = self.sock.recvfrom(9192)
            print(f"[INFO] Response Hex: {recv_data.hex(' ').upper()}")
            # 3Eフレーム応答の解析
            # 副ヘッダ(2) + ネットワーク(1) + PC(1) + I/O(2) + 局番(1) + データ長(2) + 終了コード(2)
            # = 11バイト
            header_len = 11

            end_code = struct.unpack("<H", recv_data[9:11])[0]
            if end_code != 0:
                print(f"[ERROR] {datetime.now()} SLMP Error End Code: {hex(end_code)}")
                return None

            payload = recv_data[11:]
            if len(payload) % 2 != 0:
                print(f"[ERROR] {datetime.now()} Invalid payload length: {len(payload)}")
                return None

            word_count = len(payload) // 2
            words = list(struct.unpack(f"<{word_count}H", payload))
            return words

        except socket.timeout:
            print(f"[ERROR] {datetime.now()} Timeout: No response from PLC")
            return None
        except Exception as e:
            print(f"[ERROR] {datetime.now()} Error: {e}")
            return None

# --- メイン処理相当 ---
def store_bits_in_array(words: List[int], length: int, buffer: bytearray, offset: int):
    """DLOG_StoreBitsInArray相当: ワードデータをビット展開して格納"""
    for i in range(length):
        word_idx = i // 16
        bit_idx = i % 16
        bit_val = (words[word_idx] >> bit_idx) & 0x01
        # 1バイトに1ビット値を格納（Cコードの挙動に合わせる）
        buffer[offset + i] = bit_val

def device_read_loop(client: SlmpClient, devices: List[DeviceAddr], record: LoggingRecord):
    """main.c の deviceRead() 関数を再現"""
    addr_offset = 0
    
    for dev in devices:
        # デバイス読み出し実行
        res_words = client.device_read_request(dev)
        
        if res_words is None:
            print(f"[ERROR] Failed to read device {dev.addr}")
            continue

        # デバイス種別に応じた格納
        # 本来は DEV_GetDeviceType(dev.devidx) で判定
        is_bit_device = (dev.devidx % 2 == 0) # 仮の判定

        if is_bit_device:
            # ビットデバイス展開
            store_bits_in_array(res_words, dev.length, record.buf, addr_offset)
            addr_offset += dev.length * 16 # 1ビット16バイト（Cの挙動参照）
        else:
            # ワードデバイスコピー
            data_bytes = struct.pack(f"<{len(res_words)}H", *res_words)
            record.buf[addr_offset : addr_offset + len(data_bytes)] = data_bytes
            addr_offset += len(data_bytes)

        # トリガチェック (DLOG_CheckTrigger) はここで実装
        # if check_trigger(dev, res_words): ...

def print_device_values(base_device: str, words: List[int], start_addr: int = 0):
    print(f"[INFO] {datetime.now()} ", end="")
    for i, val in enumerate(words):
        print(f"{base_device}{start_addr + i} = {val}, ", end="")
    print("")

def main():
    # 設定
    PLC_IP = "192.168.3.39"
    PLC_PORT = 5010
    INTERVAL = 2
    
    # 読み出し対象デバイスリスト
    read_targets = [
        DeviceAddr(devidx=1, addr=0x0000, length=5, devcode=0xA8), # D0-D4
    ]
    
    # クライアント初期化 (4Eフレーム)
    slmp = SlmpClient(PLC_IP, PLC_PORT, SlmpFrameType.BIN_REQ_ST)
    
    print(f"[INFO] Starting SLMP Polling for {PLC_IP}:{PLC_PORT} every {INTERVAL}s")
    print(f"[INFO] Press Ctrl+C to stop")

    # 記録用バッファ
    log_record = LoggingRecord(buf=bytearray(2048))
    
    try:
        while True:
            for dev in read_targets:
                res_words = slmp.device_read_request(dev)
                if res_words is None:
                    print(f"[ERROR] Failed to read device {dev.addr}")
                    continue
                # D0, D1, D2... を表示
                print_device_values("D", res_words, dev.addr)
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print(f"\n[INFO] ユーザーにより終了しました")
    
if __name__ == "__main__":
    main()