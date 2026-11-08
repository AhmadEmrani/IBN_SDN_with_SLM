# نصب Stage 5A — فقط قراردادها و ۲۰ نمونه مرجع

مبنای بسته: `main` در commit `5736be03b16b0ad84fd2acf56005f4303837f5c3`.
این بسته فقط فایل جدید اضافه می‌کند؛ هیچ فایل اجرایی پروژه را جایگزین نمی‌کند.

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git status --short
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
git switch -c feature/llnet-stage5a-contract-v1
cp ~/Downloads/LLNet_Stage5A_Contract_v1_Overlay.zip .
unzip -l LLNet_Stage5A_Contract_v1_Overlay.zip
unzip -n LLNet_Stage5A_Contract_v1_Overlay.zip -d .
python3 scripts/stage5a_validate.py
git status --short
git diff --stat
```

اگر در شاخه main تغییرات محلی داری، قبل از `git switch` آن‌ها را نگه‌داری کن.
`-n` یعنی فایل هم‌نام جایگزین نشود. بدون بررسی، هیچ `git reset --hard`
یا `git clean -fd` اجرا نکن. برای Stage 5A نیازی به Docker rebuild یا restart نیست.
`python3 scripts/stage5a_validate.py` فقط فایل‌های مرجع را می‌خواند؛ شبکه را تغییر نمی‌دهد.
برای Commit، بعد از بررسی خروجی، فقط فایل‌های Stage 5A را `git add` کن.
