# 租屋雷達 🏠

每小時自動掃 **591**、**PTT 租屋板**、**FB 租屋社團（通知信）**，把板橋／萬華／三重／中和／永和、12,000–18,500 的整層住家與獨立套房整理到手機網頁，有新物件就推播到手機。可申請租金補貼的物件用 🏷️ 標示。

- 排程：GitHub Actions（每小時 17 分），不用開電腦
- 網頁：GitHub Pages（PWA，可加到手機主畫面，有列表／篩選／收藏／隱藏／地圖）
- 推播：ntfy（免費）
- 備援：`run_local.ps1` 在自己電腦跑一次並推上去

---

## 一次性設定（約 15 分鐘）

### 1. 建 GitHub repo 並推上去
```powershell
cd D:\VSCODE\租房
git init -b main
git add .
git commit -m "init"
gh repo create rent-radar --public --source . --push
```
（repo 必須是 **public**，免費方案的 Pages 和無限 Actions 分鐘數都只給 public repo。資料只是公開的租屋資訊，收藏／隱藏存在手機本地。）

### 2. 開啟 GitHub Pages
repo → **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。
（一定要選 GitHub Actions，不要選 Deploy from a branch，否則排程推的資料不會更新網頁。）

網址會是 `https://<你的帳號>.github.io/rent-radar/`

### 3. 手機推播（ntfy）
1. 手機裝 **ntfy** App（Android：Google Play / F-Droid；iOS：App Store）。
2. 想一個很難猜的主題名稱，例如 `zufang-k3x9q7wm2p`（主題名就是密碼，別用簡單字）。
3. App 內「訂閱主題」輸入那個名稱。
4. repo → **Settings → Secrets and variables → Actions → New repository secret**：
   - Name：`NTFY_TOPIC`，Value：主題名稱

測試：在電腦上執行
```powershell
curl -d "測試成功" https://ntfy.sh/你的主題名稱
```
手機應該會跳通知。

### 4. FB 社團（用小號的通知信，不碰瀏覽器自動化）
1. 用一個**不重要的 FB 小號**（建議搭配一個專用 Gmail）。
2. 小號加入想追的租屋社團（例：板橋租屋、中永和租屋、三重租屋、台北租屋…）。
3. 每個社團 → 社團頁右上「⋯」或「已加入」→ **管理通知** → 選 **所有貼文**。
4. 那個 Gmail → Google 帳戶 → 安全性 → 開啟 **兩步驟驗證** → 搜尋「**應用程式密碼**」→ 建立一組（16 碼）。
5. repo Secrets 新增：
   - `FB_MAIL_USER`：小號的 Gmail 地址
   - `FB_MAIL_PASS`：那 16 碼應用程式密碼（去掉空格）
   - `FB_MAIL_HOST`：可不設，預設 `imap.gmail.com`

程式會讀 facebookmail.com 寄來的通知信，抓貼文內容與連結，讀過的信會標為已讀。沒設這組 Secrets 時 FB 來源只會顯示「未啟用」，其他照常跑。

### 5. 第一次手動跑
repo → **Actions → scrape → Run workflow**。跑完（約 2–3 分鐘）打開 Pages 網址應該就有資料。

### 6. 加到手機主畫面
手機瀏覽器開網址 → 分享／選單 → **加入主畫面**。

---

## 日常使用
- 網頁最上面顯示資料更新時間與各來源狀態（綠點正常、紅點失敗）。
- 篩選列：🏷️ 可租補、🆕 新的（上次打開之後新增的）、區域、整層／套房、來源；「⚙︎ 更多」可設價格與排序。
- 卡片：🤍 收藏、✕ 隱藏（設定頁可還原）、📄 看 PTT／FB 原文。點卡片開原始頁面。
- 地圖：橘色＝可租補，虛線淡色＝位置約略（只有路名或區名）。
- 推播點開會直接帶「只看新的」篩選。

## 改條件
編輯 `scraper/config.yaml`：價格區間、區域（591 代碼）、物件類型、租補關鍵字、排除關鍵字。推上去後下一次排程生效。

## 591 被擋怎麼辦
GitHub 機房 IP 偶爾會被 591 擋（約兩三成的執行），workflow 會自動換一台機器重試一次；還是不行就等下一小時。若想立刻補抓，在電腦上執行：
```powershell
.\run_local.ps1
```
（可在專案目錄放 `.env`，內容 `NTFY_TOPIC=...`，推播才會發。）

## 本機測試
```powershell
pip install -r requirements.txt
$env:PYTHONIOENCODING="utf-8"
python -m scraper.run --source ptt --dry-run
python -m scraper.run --source rent591 --dry-run
python -m scraper.run            # 真的寫入 data/ 並推播（需設定環境變數）
```
看網頁：`python -m http.server 8000`，然後開 `http://localhost:8000/site/`（資料路徑是 `data/`，請把 `data` 資料夾複製或建立連結到 `site/data`）。

## 檔案
```
scraper/        爬蟲（run.py 主流程；sources/ 各來源；config.yaml 條件）
data/           listings.json（網頁讀的）、status.json、geocache.json
site/           手機網頁（index.html 單檔 PWA）
.github/workflows/scrape.yml  排程 + 部署
run_local.ps1   本機備援
```
