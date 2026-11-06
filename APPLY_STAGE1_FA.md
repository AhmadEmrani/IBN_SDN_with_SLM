# LLNet v0.2 — مرحله ۱: مدل‌های داده، Migration و جداسازی Routeها

این بسته فقط فایل‌های جدید یا تغییرکرده را شامل می‌شود و بر اساس وضعیت `main`
مخزن در commit `4ed6c010783fe43671e825083e0ec46a6a2daa89` تهیه شده است.

**این مرحله Airflow را روشن نمی‌کند و APIهای Create/Delete همچنان نسخه همگام v0.1 هستند.**
مقصود این مرحله ایجاد ساختار پایدار دیتابیس و آزمون بی‌خطر Migration است.

## ۱. بررسی و Branch

در ریشه پروژه (همان مسیری که docker-compose.yml قرار دارد):

```bash
git status --short
git rev-parse --short HEAD
git switch -c feature/llnet-v02-foundation
```

اگر فایل‌های محلی تغییرات ذخیره‌نشده دارند، پیش از استخراج ZIP از آن‌ها backup بگیر.

## ۲. تهیه پشتیبان واقعی PostgreSQL

```bash
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/llnet-before-v02.dump
test -s backups/llnet-before-v02.dump && echo 'BACKUP OK'
```

**پوشه backups را در .gitignore بگذار؛ فایل dump ممکن است حساس باشد.**
از `docker compose down -v`، حذف Volume یا `alembic stamp` استفاده نکن.

## ۳. اعمال Overlay

فایل `LLNet_v0.2_Stage1_Overlay.zip` را در ریشه پروژه قرار بده:

```bash
unzip -l LLNet_v0.2_Stage1_Overlay.zip
unzip -o LLNet_v0.2_Stage1_Overlay.zip -d .
git diff --stat
```

## ۴. ساخت Image و اجرای Migration با کمترین اختلال

```bash
docker compose build policy-api
docker compose stop policy-api
docker compose run --rm --no-deps policy-api alembic upgrade head
docker compose run --rm --no-deps policy-api python scripts/verify_migration.py
docker compose up -d --no-deps policy-api
```

اگر Migration یا Verify شکست خورد، **دستور شروع مجدد API را اجرا نکن** و خروجی خطا را بررسی کن.
Ryu، OVS و Mininet در این فرآیند بازسازی یا Restart نمی‌شوند.

## ۵. تست‌ها و Smoke Test

```bash
docker compose run --rm --no-deps policy-api python -m unittest discover -s tests -p "test_v02_*.py" -v
docker compose run --rm --no-deps policy-api alembic current
curl -i http://localhost:8000/health
curl -i http://localhost:8000/openapi.json
```

در OpenAPI باید مسیرهای موجود `/api/v1/policies` و مسیر جدید
`/api/v1/operations/{operation_id}` را ببینی.

## ۶. تأیید حفظ داده

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id,status,desired_state,desired_revision_id,applied_revision_id FROM policies ORDER BY id;"'
```

`desired_revision_id` برای Policyهای قدیمی باید مقدار داشته باشد؛
`deployment_status` در import برابر `unknown` است چون Flowها مجدداً مشاهده نشده‌اند.

## هشدار سازگاری

تا مرحله دوم، ساختار جدید فقط برای داده‌های واردشده از v0.1 کامل است؛ اگر با API قدیمی Policy
جدید بسازی، فیلد `desired_revision_id` آن تا مرحله بعد ممکن است NULL باشد.
این مرحله هنوز Workflow جدید یا Reliability نهایی را تحویل نمی‌دهد.

برای اطلاعات بیشتر فایل `docs/llnet-v02-stage1-foundation.md` را ببین.
