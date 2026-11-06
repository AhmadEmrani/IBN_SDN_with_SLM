# LLNet v0.2 — Stage 2 | راهنمای نصب روی Stage 1

## 0. پیش‌نیاز

- Stage 1 موفق: `0001_v02_foundation (head)` و اسکریپت Verification موفق بوده است.
- فایل‌های ZIP مرحله دوم باید در **ریشه همان پروژه** استخراج شوند؛ پوشه `app` نباید حذف شود.
- `controller.py`، `topology.py`، `docker-compose.yml` و Volume فعلی PostgreSQL تغییر نمی‌کنند.
- تا قبل از اجرای Worker، درخواست جدید هیچ تغییری در OVS ایجاد نمی‌کند.

## 1. اعمال Overlay و بازبینی Git

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git status --short
# اگر تغییرات قبلی داری ابتدا commit یا backup بگیر.
git switch -c feature/llnet-v02-stage2
unzip -l LLNet_v0.2_Stage2_Overlay.zip
unzip -o LLNet_v0.2_Stage2_Overlay.zip -d .
git status --short
```

در صورت وجود branch جاری با همین نام، نام دیگری بگذار. اگر فایل ZIP در پوشه Downloads است، مسیر کامل فایل را به `unzip` بده.

## 2. Build و Migration مرحله دوم

```bash
docker compose build policy-api
docker compose stop policy-api
docker compose run --rm --no-deps policy-api alembic upgrade head
docker compose run --rm --no-deps policy-api alembic current
```

خروجی Migration باید `0002_v02_lifecycle (head)` باشد. اگر Alembic خطا داد ادامه نده. **هرگز** برای نصب این Overlay از `docker compose down -v` استفاده نکن.

## 3. Database Verification و تست‌ها

```bash
docker compose run --rm --no-deps policy-api python scripts/verify_migration.py
docker compose run --rm --no-deps policy-api python -m unittest discover -s tests -p 'test_v02_*.py' -v
```

در بسته تأییدشده این مرحله، تست‌ها ۲۷ مورد هستند. تمام آن‌ها باید `OK` شوند؛ این تعداد بر اساس فایل‌های موجود در بسته است و اگر تست جدیدی افزوده شود تغییر خواهد کرد.

## 4. اجرای FastAPI

```bash
docker compose up -d --no-deps policy-api
curl -i http://localhost:8000/health
```

Swagger: `http://localhost:8000/docs`

## 5. اولین تست مرحله دوم

در Swagger یا با `curl` یک Policy جدید ایجاد کن. **در نسخه جدید** POST به `/api/v1/policies` هدر اجباری `Idempotency-Key` دارد. در Swagger آن را از قسمت Headers وارد کن.

برای پرهیز از تعارض با Policy قدیمی h1↔h3 از فایل جدید `contracts/examples/firewall-deny-h2-h3-stage2.json` استفاده کن. این نمونه h2↔h3 را مسدود می‌کند. اگر Policy دیگری روی همین محدوده فعال است، ابتدا وضعیت آن را بررسی کن.

نمونه درخواست از ریشه پروژه:

```bash
curl -sS -X POST 'http://localhost:8000/api/v1/policies' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: lab-create-001' \
  --data-binary @contracts/examples/firewall-deny-h2-h3-stage2.json
```

پاسخ `202` شامل `policy_id`، `operation_id` و `status=pending` است. در این لحظه **هیچ Flow جدیدی نصب نشده است**.

حالا مقدار واقعی `operation_id` را به‌جای `<OPERATION_ID>` قرار بده:

```bash
docker compose exec policy-api python -m app.cli.run_operation '<OPERATION_ID>'
```

سپس:

```bash
curl -sS 'http://localhost:8000/api/v1/operations/<OPERATION_ID>'
curl -sS 'http://localhost:8000/api/v1/operations/<OPERATION_ID>/events'
```

برای اثبات Data Plane داخل Mininet CLI (در صورت اجرای توپولوژی):

```text
h2 ping -c 3 h3
h1 ping -c 3 h2
dpctl dump-flows -O OpenFlow13
```

`h2→h3` باید مسدود و `h1→h2` برقرار باشد؛ ۲ Flow با `priority=1100` و `actions=drop` باید شمارنده داشته باشند.

## 6. تست Disable / Enable / Delete

در Swagger، روی Endpointهای مربوط از `Idempotency-Key` **جدید و منحصربه‌فرد** استفاده کن. سپس برای هر Operation تازه، همان فرمان Worker را با ID جدید اجرا کن.

- `POST /api/v1/policies/{policy_id}/disable` → اجرا → رفع محدودیت.
- `POST /api/v1/policies/{policy_id}/enable` → اجرا → بازگشت Drop Rule.
- `DELETE /api/v1/policies/{policy_id}` → اجرا → حذف Rule و Tombstone در PostgreSQL.

Update با `PATCH /api/v1/policies/{policy_id}`، Body کامل Policy و هدر `If-Match: 1` انجام می‌شود. شماره Revision را از `GET /api/v1/policies/{id}` بخوان؛ بعد از هر Update موفق افزایش پیدا می‌کند.

## 7. عیب‌یابی

- `202 pending` یعنی درخواست فقط ثبت شده؛ Worker اجرا نشده یا Airflow هنوز نصب نیست.
- `409` یعنی Duplicate/Overlap واقعی یا Scope Reservation فعال؛ DB را برای دورزدن Lock دست‌کاری نکن.
- `412` یعنی مقدار `If-Match` قدیمی است.
- `HTTP 422` برای نبود `If-Match` یا نبود `Idempotency-Key`؛ `412` برای نسخه ناهماهنگ.
- `failed` یعنی تغییر ناموفق ولی Compensation یا عدم تغییر شبکه تأیید شده.
- `unresolved` یعنی وضعیت نامعلوم، Scope حفظ می‌شود؛ نباید کورکورانه Retry یا عملیات متعارض ارسال کنی.
- `HTTP 422` می‌تواند نشانه عدم وجود `Idempotency-Key` باشد.
- لاگ‌ها: `docker compose logs --tail 100 policy-api` و `docker compose logs --tail 100 ryu-controller`.

## 8. محدودیت‌های این Stage

- Airflow، Dispatcher خودکار و Reconciler هنوز در Stage 3/4 پیاده‌سازی می‌شوند.
- ثبت موفق POST، اثبات نصب Flow نیست؛ `status=succeeded` پس از اجرای Worker و Verification باید مشاهده شود.
- اجرای ماژولار آماده شده، اما در این مرحله محرک اجرای آن CLI است.
- تست محلی SQLite و Fake Ryu جای تست واقعی PostgreSQL و OVS را نمی‌گیرد.
- هویت `X-Client-Id` در این Lab احراز نمی‌شود؛ API فعلاً فقط روی localhost بماند.
