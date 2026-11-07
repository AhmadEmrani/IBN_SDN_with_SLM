# راهنمای نصب LLNet Stage 3 — Docker Compose واحد

مبنا: مخزن GitHub `AhmadEmrani/IBN_SDN_with_SLM` در انتهای Stage 2؛ این ZIP یک Overlay است و به‌تنهایی یک مخزن کامل نیست.

## تصمیم معماری

**فقط `docker-compose.yml`** برای تمام سرویس‌های Mininet، Ryu، LLNet API، PostgreSQL، Airflow 3.2.2 و Dispatcher.
اسکریپت `stage3.sh` یا فایل `docker-compose.stage3.yml` برای اجرای پروژه لازم نیست.
`docker-compose.override.yml` یک قابلیت رسمی Docker است؛ اما برای آزمایشگاه فعلی ترجیح داده‌ایم همه سرویس‌ها در یک فایل تعریف شوند.

### 0 — وضعیت Git و تهیه نسخه پشتیبان از Compose

از ریشه پروژه:

```bash
cd ~/Documents/digital-twin/LAB/sdn-mininet-ryu
git status --short
cp docker-compose.yml docker-compose.stage2.backup.yml
```

اگر تغییرات Commit نشده داری آن‌ها را حفظ کن. ساخت Branch جدید اختیاری است:

```bash
git switch -c feature/llnet-v02-stage3-single-compose
```

### 1 — اعمال Overlay جدید

فایل ZIP را در ریشه پروژه قرار بده و اجرا کن:

```bash
unzip -o LLNet_v0.2_Stage3_Single_Compose_Overlay.zip -d .
```

دقت: این ZIP **فایل `docker-compose.yml` را جایگزین می‌کند**، اما کد Stage 2 را پاک نمی‌کند. فایل Stage 2 backup را بیرون از مسیرهای Compose نگه داشته‌ایم.

اگر قبلاً `docker-compose.override.yml` یا `compose.override.yml` ساخته‌ای، برای جلوگیری از ادغام ناخواسته موقتاً غیرفعالش کن:

```bash
[ ! -f docker-compose.override.yml ] || mv docker-compose.override.yml docker-compose.override.yml.disabled
[ ! -f compose.override.yml ] || mv compose.override.yml compose.override.yml.disabled
```

اگر از بسته Stage 3 قدیمی `docker-compose.stage3.yml` داری، بدون نیاز به حذف می‌توانی آن را نگه داری: Docker Compose معمولی آن را خودکار نمی‌خواند. برای تمیزی پروژه در صورت وجود:

```bash
[ ! -f docker-compose.stage3.yml ] || mv docker-compose.stage3.yml docker-compose.stage3.yml.disabled
```

اگر متغیر محیطی `COMPOSE_FILE` در Shell یا `.env` تنظیم است، باید آن را بررسی کنی تا به فایل اضافی اشاره نکند:

```bash
printenv COMPOSE_FILE || true
```

### 2 — ساخت رمزهای جدید بدون وابستگی به Script

فایل `.env` قبلی (شامل رمز PostgreSQL قدیمی) را حفظ کن. **مقادیر واقعی `.env` را در چت یا GitHub منتشر نکن.**

```bash
test -f .env || { echo 'ERROR: existing .env not found'; exit 1; }
command -v openssl
umask 077
for key in AIRFLOW_DB_PASSWORD AIRFLOW_LAB_PASSWORD AIRFLOW_JWT_SECRET LLNET_INTERNAL_TOKEN; do
  if ! grep -q "^${key}=" .env; then
    printf '\n%s=%s\n' "$key" "$(openssl rand -hex 24)" >> .env
    echo "Added: $key"
  else
    echo "Exists: $key"
  fi
done
chmod 600 .env
```

اگر کلیدی از قبل وجود دارد ولی مقدارش خالی است، در `.env` مقدار غیرخالی به آن بده.

### 3 — اعتبارسنجی فایل Compose و مشاهده سرویس‌ها

```bash
docker compose version
docker compose config --quiet
docker compose config --services
```

۱۱ سرویس باید ثبت شده باشند: `postgres`, `ryu-controller`, `mininet-net`, `policy-api`, `airflow-db`, `airflow-auth-init`, `airflow-init`, `airflow-api-server`, `airflow-dag-processor`, `airflow-scheduler`, `policy-dispatcher`.

`docker compose config` **بدون `--quiet`** رمزهای expandشده را چاپ می‌کند؛ آن خروجی را منتشر نکن.

### 4 — Build و Unit Test

```bash
docker compose build policy-api policy-dispatcher
docker compose run --rm --no-deps policy-api \
  python -m unittest discover -s tests -p 'test_v03_*.py' -v
```

برای بسته فعلی انتظار ۱۲ تست Stage 3 با `OK` داریم. این موفقیت به‌معنی تست واقعی Airflow/Mininet نیست.

### 5 — اجرای LLNet API

سرویس PostgreSQL موجود باید سالم باشد؛ بدون دست‌زدن به Volume:

```bash
docker compose up -d postgres ryu-controller
docker compose up -d --no-deps policy-api
curl -i http://localhost:8000/health
```

اگر Mininet قبلاً در حال اجرا بوده، به آن کاری نداشته باش. در غیر این صورت:

```bash
docker compose up -d mininet-net
```

**به هیچ وجه برای نصب Stage 3 نیازی به `docker compose down -v` نیست.**

### 6 — آماده‌سازی پایگاه داده اختصاصی Airflow

```bash
docker compose up airflow-init
```

پس از اتمام باید `airflow-init` با Exit Code صفر پایان یافته باشد. بررسی:

```bash
docker compose ps -a
docker compose logs --tail=60 airflow-init
```

### 7 — راه‌اندازی Airflow

```bash
docker compose up -d airflow-api-server airflow-dag-processor airflow-scheduler
docker compose ps
```

Airflow UI در `http://localhost:8081` است؛ Username: `llnet` و Password: مقدار `AIRFLOW_LAB_PASSWORD` در `.env`.

در UI دنبال DAG `llnet_policy_operation` بگرد. اگر DAG دیده نشد:

```bash
docker compose logs --tail=100 airflow-dag-processor airflow-scheduler airflow-api-server
```

### 8 — راه‌اندازی ارسال خودکار Outbox

**فقط پس از سالم بودن Airflow و قابل‌مشاهده بودن DAG:**

```bash
docker compose up -d policy-dispatcher
docker compose ps
docker compose logs --tail=50 policy-dispatcher
```

### 9 — تست واقعی بدون CLI Worker

در Mininet (`docker exec -it mininet-net bash` و ورود به CLI موجود) ابتدا:

```text
mininet> pingall
```

Swagger: `http://localhost:8000/docs`، مسیر **POST** `/api/v1/policies`، با Request Body فایل `contracts/examples/firewall-deny-h2-h3-stage2.json` و هدر `Idempotency-Key: lab-stage3-auto-create-001`. برای هر درخواست آزمایشی جدید، کلید جدید بده.

انتظار `HTTP 202`، و سپس `GET /api/v1/operations/{operation_id}` با نتیجه `status=succeeded` و `airflow_run_id=llnet__<operation_id>` است. در Airflow DAG باید `preflight`, `execute`, `verify` موفق باشند.

**این بار `python -m app.cli.run_operation` را اجرا نکن.**

در Mininet:

```text
mininet> h2 ping -c 5 h3
mininet> h3 ping -c 3 h2
mininet> h1 ping -c 3 h2
mininet> dpctl dump-flows -O OpenFlow13
```

انتظار دو Drop Rule `priority=1100` برای h2↔h3 و باقی‌ماندن ارتباط h1↔h2.

### 10 — مشاهده وضعیت Outbox و Airflow

```bash
docker compose exec -T postgres sh -c \
'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT o.id, o.operation_type, o.status, o.airflow_run_id,
       x.dispatch_status, x.attempts
FROM policy_operations o
JOIN outbox_events x ON x.operation_id = o.id
ORDER BY o.created_at DESC LIMIT 8;
"'
```

لاگ خطا:

```bash
docker compose logs --tail=80 policy-dispatcher
docker compose logs --tail=80 airflow-api-server airflow-dag-processor airflow-scheduler
docker compose logs --tail=80 policy-api
```

### مرز تأیید

ساختار YAML و سازگاری سرویس‌ها با Compose قدیمی به‌صورت ایستا بررسی شده است. این بسته هنوز روی Docker/Mininet واقعی سیستم کاربر تست نشده است. Stage 3 همچنان آزمایشگاهی است؛ LocalExecutor و Simple Auth Manager برای Production مناسب نیستند. Reconciler و Recovery مستقل از Airflow در Stage 4 توسعه داده می‌شود.
