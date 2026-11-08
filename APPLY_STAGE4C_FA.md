# LLNet v0.2 — Stage 4C: راهنمای نصب و تست Auto-Healing

## هدف

از نسخه Stage 4B فعلی که روی سیستم با Ryu و Mininet آزمایش شده شروع می‌کنیم. **Stage 5 هنوز آغاز نشده است.** Stage 4C فقط یک Auto-Trigger کوچک به `policy-reconciler` اضافه می‌کند تا بعد از تأیید MISSING از همان Repair Engine ایمن Stage 4B استفاده کند.

**محافظت مهم:** به‌صورت پیش‌فرض غیرفعال است (`LLNET_AUTO_HEAL=false`). پس از تست‌ها آن را خودت فعال می‌کنی.

## 1. اعمال فایل‌ها

در ریشه پروژه:

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git status --short
# اگر شاخه مناسب نداری و تغییرات قبلی را Commit کرده‌ای:
git switch -c feature/llnet-v02-stage4c-auto-heal
unzip -o LLNet_v0.2_Stage4C_Auto_Healing_Overlay.zip -d .
docker compose config --quiet
```

ZIP فقط فایل‌های مشخص‌شده در `STAGE4C_MANIFEST.md` را به‌روزرسانی می‌کند؛ `.env`، دیتابیس PostgreSQL، Airflow و Topology پاک یا Reset نمی‌شوند. اگر دستور ایجاد Branch خطای `already exists` داد، در شاخه کاری مناسب ادامه بده.

## 2. Build و آزمایش

```bash
docker compose build policy-reconciler
docker compose run --rm --no-deps policy-reconciler \
  python -m unittest discover -s tests -p 'test_v04_auto_heal.py' -v
```

مورد انتظار: `Ran 13 tests ... OK`.

اجرای کل Regression Suite:

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m unittest discover -s tests -p 'test_v0*.py' -q
```

مورد انتظار: `Ran 86 tests ... OK`.

## 3. Smoke Test در حالت غیرفعال

در `.env` یک خط قرار بده (فایل را به Git نده):

```dotenv
LLNET_AUTO_HEAL=false
```

**دقت:** اگر این کلید از قبل وجود دارد، همان خط را تغییر بده؛ دو خط هم‌نام نگذار.

```bash
docker compose up -d --no-deps --force-recreate policy-reconciler
docker compose logs --tail=15 policy-reconciler
```

در ابتدای لاگ باید `Automatic repair DISABLED` دیده شود. چنانچه خواستی فقط یک مشاهده انجام دهی، دستور زیر حتی با مقدار `true` هم **هیچ Repairای اجرا نمی‌کند**:

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m app.cli.observe_flows --once
```

## 4. فعال‌سازی کنترل‌شده Auto-Healing

قبل از تست واقعی، از `mininet> dpctl dump-flows -O OpenFlow13` مطمئن شو Policy آزمایشی در حالت سالم دو Rule Drop دارد. مقدار `LLNET_AUTO_HEAL` را در `.env` از `false` به `true` تغییر بده و سپس:

```bash
docker compose up -d --no-deps --force-recreate policy-reconciler
docker compose exec policy-reconciler printenv LLNET_AUTO_HEAL
docker compose logs --tail=15 policy-reconciler
```

مورد انتظار: خروجی متغیر `true` و پیام `Automatic repair ENABLED`.

## 5. آزمایش واقعی (فقط آزمایشگاه Mininet)

مانند Stage 4A، **یک** Flow مشخص از Policy فعال را با Cookie و Match فعلی در OVS به‌صورت هدفمند `--strict` حذف کن. از دستور حذف عمومی، پاک‌کردن همه Flowها، یا حدس‌زدن Cookie خودداری کن. قبل از حذف، حتماً خروجی فعلی `dpctl dump-flows -O OpenFlow13` را چک کن.

این بار **فرمان `repair_missing --apply` را اجرا نکن**. `policy-reconciler` باید خودش این توالی را ایجاد کند:

```text
healthy: 1, suspected: 1
healthy: 1, confirmed: 1
Automatic repair {'status': 'succeeded', ...}
healthy: 2, suspected: 0, confirmed: 0
```

این مقادیر نمونه هستند، نه تضمین زمان. معمولاً با فاصله Polling برابر ۱۵ ثانیه مشاهده می‌شوند.

برای مشاهده:

```bash
docker compose logs -f --tail=50 policy-reconciler
```

در Mininet دوباره Flowها و ارتباط‌ها را بررسی کن:

```text
mininet> dpctl dump-flows -O OpenFlow13
mininet> pingall
```

با Firewall دوطرفه h2/h3، `pingall` باید **33% dropped** را نشان دهد؛ چون فقط ارتباط h2 با h3 مسدود است.

## 6. تأیید ثبت عملیات و عدم وابستگی به Airflow

```bash
docker compose exec -T postgres sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT id, policy_id, operation_type, requester_id, status, airflow_run_id
FROM policy_operations
WHERE requester_id = 'system:reconciler:auto'
ORDER BY created_at DESC LIMIT 5;

SELECT id, kind, confirmed_at, resolved_at, evidence->>'repair_operation_id' AS repair_operation_id
FROM reconciliation_findings
WHERE kind='missing'
ORDER BY first_seen_at DESC LIMIT 5;

SELECT network_id, dpid, operation_id FROM scope_reservations;
SQL
```

مورد انتظار: یک Operation جدید با `operation_type='reconcile'`, `requester_id='system:reconciler:auto'`, `status='succeeded'` و `airflow_run_id=NULL`؛ Finding قبلی `resolved_at` دارد. در حالت موفق، Reservation جدید باقی نمی‌ماند (مگر اینکه عملیات دیگری واقعاً در حال اجرا باشد).

## 7. خاموش‌کردن Auto-Healing

برای بازگشت به Observe Only، مقدار `.env` را به `LLNET_AUTO_HEAL=false` تغییر بده و:

```bash
docker compose up -d --no-deps --force-recreate policy-reconciler
```

**ایمنی:** اگر نتیجه `unresolved` شد، هیچ Repair دستی دیگری و هیچ حذف Reservation با SQL انجام نده؛ ابتدا نتیجه واقعی OVS/Ryu و Operation مربوطه باید بررسی شود. `docker compose down -v` نیز ممنوع است چون داده‌های PostgreSQL را حذف می‌کند.

## Gate نهایی Stage 4C

- همه Unit Tests و Regression Tests موفق
- دو مشاهده و سپس Repair خودکار بدون دخالت Operator
- نصب دوباره فقط همان Flow مفقود
- ثبت Operation و Finding، بدون Airflow یا افزایش Policy Revision
- عدم تکرار خودکار در وضعیت `unresolved` و حفظ Reservation
- تست عملی تداخل Update/Delete و خرابی Ryu قبل از Production

تا پیش از تأیید روی سیستم تو، مرحله Stage 4C صرفاً «پیاده‌سازی‌شده و Unit-Tested» است؛ نه «پایان‌یافته در محیط واقعی».
