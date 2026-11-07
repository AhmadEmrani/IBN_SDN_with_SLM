# LLNet Stage 4B — راهنمای نصب و تست Safe Repair (Manual Gate)

**پیش‌نیاز:** Stage 4A را نصب کرده‌ای و تست‌های Missing / Recovery / Unknown موفق بوده‌اند. این بسته را روی همان کد Stage 4A اعمال کن. `main` گیت‌هاب در لحظه ساخت این بسته هنوز Stage 4A را نداشت؛ پس با `git pull` یا جابه‌جایی بی‌دلیل Branch، فایل‌های Stage 4A را از دست نده.

## 1) آماده‌سازی Branch

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git status --short
# اگر تغییرات مهم محلی داری، قبل از ادامه Commit یا Stash کن.
git switch -c feature/llnet-v02-stage4b-repair
unzip -o LLNet_v0.2_Stage4B_Safe_Repair_Overlay.zip -d .
```

این Overlay فقط دو فایل Python اجرایی، یک فایل تست و مستندات را اضافه می‌کند. `docker-compose.yml`، Stage 3، Stage 4A و دیتابیس‌ها را تغییر نمی‌دهد.

## 2) Build و تست

```bash
docker compose config --quiet
docker compose build policy-reconciler
docker compose run --rm --no-deps policy-reconciler \
  python -m unittest discover -s tests -p 'test_v04_repair.py' -v
```

**خروجی مورد انتظار:** `Ran 15 tests` و `OK`.

برای اجرای تمام تست‌های Stage 2 تا 4B:

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m unittest discover -s tests -p 'test_v0*.py' -v
```

**خروجی مورد انتظار در محیط تست شبیه‌سازی‌شده:** `Ran 73 tests` و `OK`.

Observer دائمی را با همان Image جدید بالا بیاور (بدون تغییر Compose):

```bash
docker compose up -d --no-deps --force-recreate policy-reconciler
```

**Migration جدید وجود ندارد**؛ `0003_v02_observation` همچنان Head است.

## 3) ساختن یک Finding آزمایشیِ جدید

از آزمایش قبلی، Policy را Disable/Enable کردی، پس Missing قبلی باید `resolved` شده باشد. برای آزمون Repair باید یک Missing **جدید و تأییدشده** ایجاد کنیم.

1. در محیط **صرفاً آزمایشگاهی** Mininet، با `dpctl dump-flows -O OpenFlow13` Cookie و مشخصات فعلی دو Rule مربوط به Policy را بررسی کن.
2. دقیقاً یکی از دو Rule Drop را مثل آزمایش Stage 4A به‌صورت **strict** حذف کن. از دستورهای delete بدون محدودکردن Cookie و Match استفاده نکن.
3. Reconciler را روشن نگه دار. پس از دو مشاهده معتبر، انتظار داریم `healthy: 1` و `confirmed: 1` شود.

برای یافتن شناسه Finding باز:

```bash
docker compose exec -T postgres sh -c \
'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT id, policy_id, kind, consecutive_count, confirmed_at
FROM reconciliation_findings
WHERE kind = 'missing'
  AND confirmed_at IS NOT NULL
  AND resolved_at IS NULL
ORDER BY first_seen_at DESC;
SQL
```

از خروجی، `id` مربوط به همین Policy را کپی کن. در دستورات بعد، `FINDING_ID` را با UUID واقعی جایگزین کن.

## 4) Dry-Run (بدون تغییر شبکه یا دیتابیس)

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m app.cli.repair_missing --finding-id FINDING_ID
```

**خروجی مطلوب:**

```json
{"status":"eligible","reason":"missing","operation_id":null}
```

در این حالت هیچ Operation، Reservation یا دستور OpenFlow ثبت/ارسال نمی‌شود.

## 5) Repair کنترل‌شده (فقط یک Flow)

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m app.cli.repair_missing --finding-id FINDING_ID --apply
```

**خروجی مطلوب:**

```json
{"status":"succeeded","reason":"flow_restored_and_verified","operation_id":"..."}
```

در ترمینال Mininet:

```text
dpctl dump-flows -O OpenFlow13
pingall
```

باید هر دو Drop Rule حاضر باشند؛ در سناریوی Firewall قبلی `h2 ↔ h3` مسدود خواهد بود و `pingall` معمولاً `33% dropped` نشان می‌دهد.

## 6) تأیید PostgreSQL و نبودن Airflow

```bash
docker compose exec -T postgres sh -c \
'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT o.id, o.operation_type, o.status, o.airflow_run_id, o.requested_revision_id
FROM policy_operations o
WHERE o.operation_type = 'reconcile'
ORDER BY o.created_at DESC LIMIT 5;

SELECT id, kind, resolved_at, evidence->>'repair_operation_id' AS repair_operation_id
FROM reconciliation_findings
ORDER BY first_seen_at DESC LIMIT 5;

SELECT policy_id, revision, desired_state, applied_state
FROM policies
WHERE id = 'FW-3f241f267356';

SELECT operation_id FROM scope_reservations;
SQL
```

در یک Repair موفق انتظار داریم: `status = succeeded`، `airflow_run_id = NULL`، Finding با `resolved_at` و `repair_operation_id`، Revision قبلی بدون تغییر، و عدم وجود Reservation مربوط به این عملیات.

## 7) خطاها و توقف ایمن

- `refused`: Finding جدید/تأییدشده نیست، Policy پایدار نیست، یا Scope مشغول است؛ **هیچ Flowای تغییر نمی‌کند**.
- `failed`: بررسی پیش از OpenFlow ADD شکست خورده است؛ Reservation آزاد می‌شود، **هیچ Flowای تغییر نمی‌کند**.
- `unresolved`: یک OpenFlow ADD ممکن است اجرا شده باشد، ولی تأیید قطعی نیست؛ Reservation عمداً حفظ می‌شود. **تکرار کورکورانه Repair یا پاک‌کردن Reservation ممنوع است.** باید وضعیت واقعی Switch و Operation بررسی شود.
- اگر Operation از طریق CLI اجرا شد، نباید آن را مجدداً به‌صورت `run_operation` Stage 2 اجرا کنی؛ منطق این Operation از نوع `reconcile` اختصاصی است.

**این نسخه عمداً ترمیم اتوماتیک دوره‌ای ندارد.** بعد از تست واقعی این مرحله، در Stage 4C اضافه‌کردن Trigger خودکار به Reconciler را بررسی می‌کنیم.
