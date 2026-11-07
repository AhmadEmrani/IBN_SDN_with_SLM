# راهنمای نصب و آزمایش LLNet Stage 4A — Observer (Read-Only)

این بسته برای **آخرین `main`** مخزن `AhmadEmrani/IBN_SDN_with_SLM` طراحی شده است و فقط یک فایل `docker-compose.yml` استفاده می‌کند. Airflow بدون تغییر می‌ماند. Read-Only یعنی مشاهده‌گر **هیچ Flowای را ایجاد، اصلاح یا حذف نمی‌کند**؛ اما آخرین مشاهده و Findingها در PostgreSQL ذخیره می‌شوند.

> **ایمنی:** به هیچ وجه `docker compose down -v`، `docker volume prune` یا `alembic downgrade` اجرا نکن. فایل `.env` را داخل Git یا ZIP قرار نده. رمزهایی که قبلاً در چت نمایش داده شده‌اند باید به روش درست تغییر کنند.

## ۱. آماده‌سازی Branch و اعمال بسته

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git status --short
# ابتدا مطمئن شو که تغییرات محلی مهم Commit شده‌اند.
git switch main
git pull --ff-only origin main
git switch -c feature/llnet-v02-stage4a-observer
cp docker-compose.yml docker-compose.stage3.backup.yml
unzip -o LLNet_v0.2_Stage4A_ReadOnly_Overlay.zip -d .
```

*اگر Branch هم‌نام از قبل وجود داشت، آن را دوباره ایجاد نکن؛ به همان Branch سوئیچ کن.* فایل backup داخل ریشه فقط برای بازیابی احتمالی است و قبل از Commit آن را خارج از مخزن منتقل کن یا در Git ثبت نکن.

## ۲. بررسی و Build

```bash
docker compose config --quiet
docker compose config --services
docker compose build policy-api policy-reconciler
```

سرویس جدید `policy-reconciler` باید در خروجی فهرست باشد. هیچ سرویس Stage 3 حذف نشده است.

## ۳. تست‌های واحد (بدون اتصال Ryu)

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m unittest discover -s tests -p 'test_v04_*.py' -v
```

انتظار: **۱۹ تست** و `OK`. سپس Regression:

```bash
docker compose run --rm --no-deps policy-reconciler \
  python -m unittest discover -s tests -p 'test_v0*.py' -q
```

در محیط بازسازی‌شده، مجموعه تست‌ها ۵۸ تست داشت و پاس شد. پیام شبیه‌سازی خرابی Dispatcher در برخی تست‌ها مورد انتظار است.

## ۴. Migration دیتابیس اصلی LLNet

Migration جدید فقط جدول `reconciliation_findings` و دو Index ایجاد می‌کند. هیچ جدول Policy، Revision، Operation یا داده قبلی حذف نمی‌شود. این Migration فقط روی دیتابیس اصلی LLNet است، **نه دیتابیس Airflow**.

```bash
docker compose run --rm policy-reconciler \
  alembic upgrade head

docker compose run --rm policy-reconciler \
  alembic current
```

انتظار: `0003_v02_observation (head)`.

## ۵. اجرای یک بار مشاهده (اولین Gate عملیاتی)

قبل از فعال‌کردن سرویس دائمی، مطمئن شو حداقل یک Policy قبلی `enabled` و `active` است و Flowهای آن روی Ryu/Mininet وجود دارند. سپس:

```bash
docker compose run --rm policy-reconciler \
  python -m app.cli.observe_flows --once
```

برای نمونه، در وضعیت سالم با دو Flow انتظار خروجی‌ای شبیه این داریم (اعداد واقعی ممکن است بیشتر باشند):

```json
{"switches":1,"healthy":2,"suspected":0,"confirmed":0,"unknown":0,"extra":0,"skipped":0}
```

اگر `skipped` مشاهده شد، وضعیت Operationها و Reservationهای معلق یا Policyهای `unknown` بررسی شوند. اگر `unknown` آمد، Ryu/Switch یا ساختار پاسخ Flow Stats باید بررسی شود. Observer هیچ اقدام ترمیمی انجام نمی‌دهد.

## ۶. بررسی داده‌های ذخیره‌شده

آخرین وضعیت Revision اعمال‌شده:

```bash
docker compose exec -T postgres sh -c \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT d.policy_id, d.dpid, d.flow_index, d.deployment_status,
       d.last_observed_at,
       d.observed_snapshot->>'classification' AS observation
FROM flow_deployments d
JOIN policies p ON p.id = d.policy_id AND p.applied_revision_id = d.revision_id
ORDER BY d.policy_id, d.dpid, d.flow_index;
SQL
```

اگر Quoteهای Shell در ترمینال مشکل داشتند، می‌توانی ساده‌تر وارد `psql` شوی:

```bash
docker compose exec postgres sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

و در محیط `psql` این SQL را اجرا کن:

```sql
SELECT policy_id, dpid, flow_index, deployment_status,
       last_observed_at, observed_snapshot->>'classification' AS actual
FROM flow_deployments
WHERE last_observed_at IS NOT NULL
ORDER BY last_observed_at DESC LIMIT 20;
```

جدول Findingها:

```sql
SELECT kind, dpid, policy_id, consecutive_count,
       first_seen_at, confirmed_at, resolved_at
FROM reconciliation_findings
ORDER BY first_seen_at DESC LIMIT 20;
```

با `\q` از `psql` خارج شو. در وضعیت کاملاً سالم ممکن است جدول Findingها خالی باشد و این **طبیعی** است.

همچنین آخرین وضعیت Flowها از Endpoint موجود در Swagger قابل مشاهده است:

`GET /api/v1/policies/{policy_id}/deployments`

این Endpoint فقط بعد از Restart کردن `policy-api` با Image جدید، فیلدهای جدید را از DB نشان می‌دهد (خود Endpoint جدید نیست).

## ۷. فعال‌کردن Polling دائمی (۱۵ ثانیه)

بعد از اینکه `--once` نتیجه صحیح داد:

```bash
docker compose up -d --no-deps --force-recreate policy-api
docker compose up -d policy-reconciler
docker compose ps policy-reconciler
docker compose logs --tail=60 -f policy-reconciler
```

هر چرخه فقط یک `/stats/switches` و حداکثر یک `/stats/flow/{dpid}` برای هر Switch مرتبط می‌خواند. پس از تأیید، برای قطع نمایش لاگ‌ها `Ctrl+C` بزن؛ این کار سرویس را خاموش نمی‌کند.

## ۸. تست کنترل‌شده Drift (اختیاری؛ فقط بعد از Gateهای بالا)

یک Flow متعلق به Policy آزمایشی را در Mininet **به‌صورت هدفمند و با تطبیق دقیق Cookie/Match** حذف کن. در مرحله فعلی بهتر است دستور حذف را بعد از مشاهده خروجی واقعی OVS و مشخص‌شدن Flow انتخاب کنیم. Observer پس از دو Poll معتبر باید `missing` را ثبت کند؛ اما **حق ندارد Flow را ترمیم کند**. در این آزمایش ممکن است Ping بین دو Host موقتاً آزاد شود. بازگرداندن Policy از طریق Lifecycle موجود (مثلاً Disable/Enable) باید جداگانه و با رعایت Operationهای فعال انجام شود.

## ۹. Commit محلی

```bash
git diff --check
git status --short
```

وقتی تست Docker/Ryu موفق شد، تغییرات این Branch را Commit و Push کن. این بسته به‌صورت مستقیم روی GitHub اعمال نشده است.
