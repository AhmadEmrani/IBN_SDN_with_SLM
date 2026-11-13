# راهنمای اجرای پاک‌سازی Stage 5F.4

مبنا: Branch `refactor/stages`، Commit `bad0cbec02d13e911dda4f9ba2f0e7b620ba1306`.

## اعمال

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git branch --show-current
git status --short
unzip -o ~/Downloads/LLNet_5F4_Final_Cleanup_Overlay.zip -d .
python3 scripts/apply_repository_cleanup.py
```

اگر `README_5F3_FA.md` از مراحل قبل باقی مانده، این فایل در Git ثبت نشده؛ با `rm README_5F3_FA.md` فقط در صورت اطمینان حذفش کن. **هیچ `docker compose down -v` اجرا نکن.**

## تست

```bash
docker compose config --quiet
python3 scripts/infra_check.py
docker compose build intent-retriever
bash scripts/check_merge_readiness.sh
```

برای اجرای Smoke به سرویس‌های BGE، Phi و Orchestrator روشن نیاز است. اگر آن‌ها خاموش‌اند:

```bash
docker compose up -d --no-deps intent-retriever phi-inference intent-orchestrator
```

**مهم:** تست Merge Readiness هیچ Policy جدیدی ثبت نمی‌کند و FlowMod ارسال نمی‌کند. تست واقعی Firewall Apply/Verify/Disable/Restore باید در آزمایشگاه ایزوله مطابق سناریوهای تست موجود به‌صورت جداگانه اجرا و ثبت شود. `alembic current` صرفاً وضعیت Migration را نمایش می‌دهد، ولی `alembic upgrade` را به طور خودکار اجرا نمی‌کنیم.

## بررسی تغییرات و Commit

```bash
git status --short
git diff --check
git diff --stat
git add -A
git diff --cached --check
git commit -m "refactor(repo): retire stage-specific runtime files and document stable deployment"
git push origin refactor/stages
```

در صورت شکست تست‌ها **Commit/PR/Merge انجام نده**. فایل‌های قدیمی در `docs/archive` صرفاً سوابق توسعه هستند و نباید اجرا شوند. Manifestها و راهنماهای قدیمی برای بازتولید پژوهشی باقی می‌مانند.
