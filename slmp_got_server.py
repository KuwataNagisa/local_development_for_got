import socket
import struct
import sys

class SLMPProtocol:
    """SLMPプロトコルの定数とユーティリティ"""
    SUBHEADER_3E_REQ = 0x0050
    SUBHEADER_3E_RES = 0x00D0
    SUBHEADER_4E_REQ = 0x0054
    SUBHEADER_4E_RES = 0x00D4
    
    CMD_BATCH_WRITE = 0x1401  # ワード単位の一括書込み
    SUB_CMD_WORD = 0x0000     # ワード単位

class SLMPServer:
    def __init__(self, host='0.0.0.0', port=5010):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.latest_value = 0  # 受信値を格納する変数

    def start(self):
        """サーバーの起動"""
        try:
            self.sock.bind((self.host, self.port))
            print(f"[INFO] SLMP Server started on {self.host}:{self.port}")
            print(f"[INFO] Waiting for GOT2000 (UDP Binary)...")
            
            while True:
                data, addr = self.sock.recvfrom(4096)
                print(f"[INFO] Request Hex: {data.hex(' ').upper()}")
                self._handle_request(data, addr)
        except Exception as e:
            print(f"[ERROR] Server error: {e}")
        finally:
            self.sock.close()

    def _handle_request(self, data, addr):
        """受信データの解析とレスポンス送信"""
        try:
            # 最小ヘッダーサイズチェック (3Eフレームの最短は15バイト程度)
            if len(data) < 11:
                return

            # サブヘッダーの確認 (Little Endian)
            subheader = struct.unpack_from('<H', data, 0)[0]

            if subheader == SLMPProtocol.SUBHEADER_3E_REQ:
                self._process_3e_frame(data, addr)
            elif subheader == SLMPProtocol.SUBHEADER_4E_REQ:
                self._process_4e_frame(data, addr)
            else:
                print(f"[ERROR] Unknown Subheader: {hex(subheader)} from {addr}")

        except Exception as e:
            print(f"[ERROR] Failed to process request: {e}")

    def _process_3e_frame(self, data, addr):
        """3Eフレームの解析と応答"""
        # 3E Request Format (Binary):
        # Subheader(2) + NW(1) + PC(1) + IO(2) + Station(1) + Length(2) + Timer(2) + Command(2) + Sub(2) + Device...
        
        # 共通ヘッダー部分の抽出 (NW番号から局番号まで)
        header_common = data[2:7]
        
        # コマンド位置の特定 (データ長以降)
        # 3Eの場合、コマンドはオフセット11から
        command = struct.unpack_from('<H', data, 11)[0]
        
        if command == SLMPProtocol.CMD_BATCH_WRITE:
            # デバイスコード以降のデータ抽出 (1ワード書き込み想定)
            # デバイス(4) + 点数(2) + データ(2)
            # 点数はオフセット19, データはオフセット21
            points = struct.unpack_from('<H', data, 19)[0]
            if points >= 1:
                received_val = struct.unpack_from('<H', data, 21)[0]
                self.latest_value = received_val
                
                # レスポンス作成
                response = self._build_response_3e(header_common)
                self.sock.sendto(response, addr)
                
                print(f"[INFO] Received Value: {self.latest_value} (from {addr[0]})")
        else:
            print(f"[INFO] Received Command {hex(command)}, but only Batch Write is handled.")

    def _build_response_3e(self, header_common):
        """3Eレスポンスバイナリの構築"""
        subheader = struct.pack('<H', SLMPProtocol.SUBHEADER_3E_RES)
        # レスポンスデータ長 (終了コード2バイト分)
        res_len = struct.pack('<H', 2)
        end_code = struct.pack('<H', 0) # 0: 正常終了
        
        return subheader + header_common + res_len + end_code

    def _process_4e_frame(self, data, addr):
        """4Eフレームの解析 (構造のみ実装、3Eと同様のロジック)"""
        # 4Eはシリアル番号等のフィールドが増えるが、基本構造は3Eに近い
        header_common = data[2:11] # 4Eはヘッダーが長い
        print(f"[INFO] 4E Frame received. (Basic support only)")
        
        # 簡易的な正常応答
        subheader = struct.pack('<H', SLMPProtocol.SUBHEADER_4E_RES)
        res_len = struct.pack('<H', 2)
        end_code = struct.pack('<H', 0)
        self.sock.sendto(subheader + header_common + res_len + end_code, addr)

def main():
    # 設定
    LISTEN_PORT = 5010
    
    server = SLMPServer(port=LISTEN_PORT)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped by user.")
        sys.exit(0)
    
if __name__ == "__main__":
    main()
