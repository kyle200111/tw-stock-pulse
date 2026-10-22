# TAIWAN / PULSE — 台股中期波段研究儀表板

以 V1 Excel 規則為參考建立、行動版適用的靜態 Web App。無需另行輸入行情資料。**未部署前無公開網址，未執行同步前無即時選股結果。**

## 上線方式（GitHub Pages）
1. 建立新的 **GitHub 公開 repository**，將本資料夾內的檔案完整上傳到 repository 根目錄（包含 `.github/workflows/update.yml`）。
2. 到 Settings → Pages → Build and deployment，Source 選 **GitHub Actions**。
3. 到 Actions → Update Taiwan Stock Screen → Run workflow，首次補齊歷史價格可能需要數分鐘並受證交所流量限制。執行成功後網址通常為 `https://你的帳號.github.io/你的repo名稱/`。
4. 之後 Actions 在台北時間每週一 08:00 及週一至週五 18:00 自動嘗試同步；GitHub Actions 的定時觸發**不保證準點**，亦可能受平台排程與官方 API 限流影響。
5. 若要手機加到主畫面，開啟網站後用 Safari 分享 → 加入主畫面。

## 重要限制
- 僅研究 **證交所上市股票中最新成交金額前60檔**，不包含上櫃／興櫃，亦非全市場排名。
- TWSE `STOCK_DAY_ALL` 只提供最新交易日。本系統使用 TWSE `STOCK_DAY` 逐檔補抓約六個月歷史資料，以計算 MA20、MA60、ATR14。
- 月營收以及本益比使用官方 API。財務資料必須使用當時已揭露資訊，若無法取得 EPS、法人完整5日或20日歷史，**不產生完整100分總分**。顯示的是「可得資料項目的百分比評分」及資料覆蓋程度，不能與原始 Excel 100 分直接比較。
- 目標價＝最後有效收盤價+3×ATR14，停損價＝最後有效收盤價−2×ATR14；**是交易規劃參考值，不是預測價位**，亦不考慮隔日跳空滑價。持有週期是依動能設計的情境區間，而不是模型預測。
- GitHub Pages 公開資料包括選股名單。如需私密帳戶、實際持倉、付費行情、Email/LINE 主動推播，需另加具認證的後端和授權，不能將密鑰放進網站前端。
- API 如果無回應、格式改變或資料過舊，頁面揭露資料不足，並不捏造行情。此專案不提供自動下單。

## 本機查看
`python -m http.server 8000 -d site`，打開 `http://localhost:8000`。首次若 `data.json` 無資料，顯示待同步狀態。執行 `python build.py` 後生成官方資料快照（需要可連網環境）。

## 資料源
- https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL
- https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY
- https://openapi.twse.com.tw/v1/opendata/t187ap05_L
- https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL

## 下一版待辦
上櫃支援、EPS 四季合計、法人大額買賣超歷史、指數強弱、全市場批次更新、除權息還原價調整、真實回測與樣本外驗證、持股管理、OAuth 私密登入、主動通知。

## V1.1 更新與驗證狀態（2026-10-22）
- 新增上市股票官方 T86 最近五個有效交易日外資與投信買賣超擷取、快取和條件式15分籌碼分數。只有成功抓到五個交易日才計分，否則保持缺值。
- 本專案通過 Python 語法編譯檢查，但由於目前執行環境沒有完成官方資料網路請求、GitHub 倉庫部署與線上工作流程測試，**不能宣稱同步成功或網站已上線**。
- 尚缺：上櫃歷史日價、各業別近四季EPS可靠串接、全市場批次掃描、除權息還原、樣本外回測及已確認的公開網站。請勿將部分評分作為完整100分推薦。
