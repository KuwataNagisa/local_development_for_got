### GOT用開発コード

- ftp_img_view.py <br>
→FTPにてGOTへ画像ファイルを送付する, 送付中の画像の表示も行う
- ftp_img_noview.py <br>
→FTPにてGOTへ画像ファイルを送付する, 送付中の画像の表示は行わない
- slmp_got_client.py <br>
→SLMPにてクライアントであるGOTに対してサーバーである実行側を起動, レスポンスを返す
- slmp_plc_server.py <br>
→SLMPにてサーバーであるPLCへクライアントである実行側から問い合わせを行う