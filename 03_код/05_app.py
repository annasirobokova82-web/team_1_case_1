#!/usr/bin/env python3
import csv
import json
import os
import sys
import re
from datetime import datetime

# --- НАСТРОЙКА ПУТЕЙ ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(CURRENT_DIR) == "03_код":
    PROJECT_ROOT = os.path.dirname(CURRENT_DIR) 
else:
    PROJECT_ROOT = CURRENT_DIR 

DATA_DIR = os.path.join(PROJECT_ROOT, "01_данные")
if not os.path.exists(DATA_DIR):
    DATA_DIR = CURRENT_DIR

RECIPIENTS_CSV = os.path.join(DATA_DIR, "recipients.csv")
# Читаем исходные платежи из payments.csv
PAYMENTS_CSV = os.path.join(DATA_DIR, "payments.csv") 
# А результаты тестов пишем в payments_out.csv (чтобы не трогать исходники)
OUT_CSV = os.path.join(DATA_DIR, "payments_out.csv")

def load_active_recipients():
    active = set()
    try:
        with open(RECIPIENTS_CSV, encoding="utf-8", errors="ignore") as f:            
            for row in csv.DictReader(f):
                if row.get("status") == "ACTIVE":
                    active.add(row["recipient_id"])
    except FileNotFoundError:
        pass
    return active

def validate(payload, active_recipients):
    errors = []
    for field in ["order_id", "recipient", "purpose", "amount", "currency"]:
        if not payload.get(field):
            errors.append((field, "VALIDATION_ERROR"))
    if payload.get("order_id"):
        if not re.match(r"^[A-Za-z0-9_\-]{1,64}$", str(payload["order_id"])):
            errors.append(("order_id", "INVALID_FORMAT"))
    if payload.get("amount") is not None:
        try:
            amt = float(payload["amount"])
            if amt <= 0 or amt > 1_000_000:
                errors.append(("amount", "AMOUNT_OUT_OF_RANGE"))
        except ValueError:
            errors.append(("amount", "VALIDATION_ERROR"))
    if payload.get("currency") and payload["currency"] != "RUB":
        errors.append(("currency", "UNSUPPORTED_CURRENCY"))
    if payload.get("recipient") and payload["recipient"] not in active_recipients:
        errors.append(("recipient", "RECIPIENT_NOT_FOUND"))
    return errors

def emulate_gateway(order_id):
    """4 сценария для демонстрации"""
    # Новые тестовые номера, которых точно нет в исходном файле
    if order_id == "ord_5001": 
        return "SUCCESS", None
    elif order_id == "ord_5002": 
        return "DECLINED", "INSUFFICIENT_FUNDS"
    elif order_id == "ord_5003": 
        return "DECLINED", "CARD_DECLINED"
    elif order_id == "ord_5009": 
        return "TIMEOUT", "GATEWAY_TIMEOUT"
    else: 
        return "SUCCESS", None

def find_existing_payment(order_id):
    """Ищет дубликаты в payments_out.csv (только наши тестовые записи)"""
    if not os.path.exists(OUT_CSV):
        return None
    try:
        with open(OUT_CSV, mode='r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) > 1 and row[1] == order_id:
                    return row[0]
    except Exception:
        pass
    return None

def main():
    if len(sys.argv) < 2:
        sys.exit(1)
    
    try:
        with open(sys.argv[1], encoding="utf-8", errors="ignore") as f:
            payload = json.load(f)
    except Exception as e:
        print(json.dumps({"status": "ERROR", "error_code": "BAD_JSON", "errors": [{"field": "file", "code": str(e)}]}))
        sys.exit(2)

    # 1. Проверка на дубликат (в файле out, чтобы не мешать исходникам)
    existing_payment_id = find_existing_payment(payload.get("order_id"))
    if existing_payment_id:
        print(json.dumps({
            "status": "ERROR",
            "error_code": "DUPLICATE_ORDER",
            "message": "Этот заказ уже был оплачен ранее. Повторное списание запрещено."
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    # 2. Валидация
    active = load_active_recipients()
    errors = validate(payload, active)
    if errors:
        print(json.dumps({
            "status": "ERROR",
            "error_code": "VALIDATION_ERROR",
            "errors": [{"field": f, "code": c} for f, c in errors],
        }, ensure_ascii=False, indent=2))
        sys.exit(2)

    # 3. Эмулятор шлюза
    status, error_code = emulate_gateway(payload["order_id"])
    result = {
        "payment_id": "pay_demo_" + str(payload["order_id"])[-4:],
        "status": status,
        "error_code": error_code,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 4. Запись в payments_out.csv (только для тестовых)
    if not existing_payment_id:
        try:
            now_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
            # Проверяем, существует ли файл, чтобы записать заголовок
            file_exists = os.path.exists(OUT_CSV)
            
            with open(OUT_CSV, mode='a', newline='', encoding='utf-8', errors='ignore') as f:
                writer = csv.writer(f)
                if not file_exists:
                    # Пишем заголовок, как в исходном файле
                    writer.writerow(["payment_id","order_id","recipient","purpose","amount","currency","status","error_code","idempotency_key","created_at","confirmed_at","correlation_id"])
                writer.writerow([
                    result["payment_id"], 
                    payload["order_id"], 
                    payload["recipient"], 
                    payload["purpose"], 
                    payload["amount"], 
                    payload["currency"], 
                    result["status"], 
                    result["error_code"], 
                    "idem_auto_" + str(payload["order_id"])[-4:], 
                    now_time, 
                    now_time if result["status"] == "SUCCESS" else "", 
                    "corr_auto_" + str(payload["order_id"])[-4:]
                ])
        except Exception as e:
            print(f"Ошибка записи в CSV: {e}", file=sys.stderr)

    if status == "TIMEOUT": sys.exit(3)
    sys.exit(0 if status == "SUCCESS" else 1)

if __name__ == "__main__":
    main()