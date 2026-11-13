import os
import json
import asyncio
import uvicorn
import gspread
import calendar
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, MenuButtonWebApp

TOKEN = os.getenv("BOT_TOKEN", "8277410883:AAGgHDgwaFMDPbrsfIdCbmngMmg6Izdld70")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://865f-185-223-171-52.ngrok-free.app") 
OLD_SPREADSHEET_ID = "1x_aiXFd3Y0Mh_eHtahz2h6HnW6vx_1GhpbpFup9ljCU"
TARGET_SPREADSHEET_ID = "1PfdAFGpRrIc_LWsmK88A-AWHs8-zpXMz_t2kxGDLpfA"
_env_sheet = os.getenv("SPREADSHEET_ID", "").strip()
if _env_sheet and _env_sheet != OLD_SPREADSHEET_ID:
    SPREADSHEET_ID = _env_sheet
else:
    SPREADSHEET_ID = TARGET_SPREADSHEET_ID

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

# Подключение к Google Таблицам: из переменной GOOGLE_CREDENTIALS или локального credentials.json
google_creds_json = os.getenv("GOOGLE_CREDENTIALS")
if google_creds_json:
    creds_dict = json.loads(google_creds_json)
    gc = gspread.service_account_from_dict(creds_dict)
elif os.path.exists("credentials.json"):
    gc = gspread.service_account(filename="credentials.json")
else:
    raise FileNotFoundError("Не найдены учетные данные Google: задайте GOOGLE_CREDENTIALS или положите credentials.json")

sh = gc.open_by_key(SPREADSHEET_ID)

CATEGORY_MAPPING = {
    "продукты": "продукты",
    "обеды": "обеды (рестораны, кафе, пекарни)",
    "транспорт": "транспорт (такси, электричка)",
    "хозтовары": "хозтовары, уют",
    "связь": "связь и интернет",
    "одежда": "одежда, обувь и аксессуары",
    "тренировки": "тренировки",
    "репетитор": "репетитор",
    "здоровье": "здоровье и личная гигиена (+линзы)",
    "уход": "уход за собой (крема, шампуни и т.д.)",
    "развлечения": "развлечения",
    "подарки": "подарки",
    "вклады": "вклады и накопительные счета",
    "учеба": "учеба (печать, канцтовары и т.д.)",
    "билеты": "билеты",
    "квартира": "квартира",
    "зоотовары": "зоотовары"
}

# ЖЕСТКО ЗАДАННЫЙ СПИСОК ДОХОДОВ
# Бот покажет только эти источники, всё лишнее из таблицы будет проигнорировано
INCOME_SOURCES = [
    "остаток Максим",
    "остаток Яся",
    "премия Яся",
    "зарплата Максим",
    "аванс Яся",
    "кэшбэк Тинькофф",
    "аванс Максим",
    "зарплата Яся",
    "стипендия Максим"
]

def find_worksheet(sh, dt_or_str):
    titles = {ws.title.lower(): ws for ws in sh.worksheets()}
    months = ["январь", "февраль", "март", "апрель", "май", "июнь", 
              "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

    if isinstance(dt_or_str, datetime):
        m_idx = dt_or_str.month
        year = dt_or_str.year
    else:
        s = str(dt_or_str).strip().lower()
        if s in titles:
            return titles[s]
        m_idx = None
        year = None
        for i, m in enumerate(months, start=1):
            if m in s:
                m_idx = i
                break
        parts = s.replace('.', ' ').replace('/', ' ').replace('-', ' ').split()
        for p in parts:
            if p.isdigit() and len(p) == 4:
                year = int(p)
            elif p.isdigit() and 1 <= int(p) <= 12 and m_idx is None:
                m_idx = int(p)

        if not m_idx:
            m_idx = datetime.now().month
        if not year:
            year = datetime.now().year

    candidates = [
        f"{m_idx:02d}.{year}".lower(),
        f"{m_idx}.{year}".lower(),
        f"{months[m_idx - 1]} {year}".lower()
    ]
    for c in candidates:
        if c in titles:
            return titles[c]

    for title, ws in titles.items():
        if f"{m_idx:02d}.{year}" in title or (str(year) in title and months[m_idx - 1] in title):
            return ws

    raise gspread.WorksheetNotFound(f"Лист для '{dt_or_str}' не найден")

def clean_val(raw_val):
    if raw_val is None:
        return ""
    clean_str = str(raw_val).replace('₽', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
    if clean_str:
        try:
            f_val = float(clean_str)
            return str(int(f_val)) if f_val.is_integer() else clean_str
        except ValueError:
            return clean_str
    return ""

def get_category_rows(all_values):
    has_levels = len(all_values) > 0 and len(all_values[0]) > 1 and 'уровень' in all_values[0][1].strip().lower()
    cat_rows = {}
    for k, sheet_cat in CATEGORY_MAPPING.items():
        target = sheet_cat.strip().lower().replace('ё', 'е')
        for i, r in enumerate(all_values[:55]):
            if not r or not r[0]: continue
            c0 = r[0].strip().lower().replace('ё', 'е')
            if c0 == target:
                if has_levels:
                    cat_rows[k] = {'total': i + 1, 'maxim': i + 2, 'yasya': i + 3}
                else:
                    cat_rows[k] = {'total': i + 1, 'maxim': i + 1, 'yasya': i + 1}
                break
    return cat_rows, has_levels

def get_sheet_name(dt: datetime):
    return f"{dt.month:02d}.{dt.year}"

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    try:
        await bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(text="Бюджет", web_app=WebAppInfo(url=WEBAPP_URL))
        )
    except Exception:
        pass
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Открыть бюджет", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer("Управление бюджетом:", reply_markup=markup)

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def get_html():
    with open("index.html", "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(
        content=content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )

# ================= РАСХОДЫ (МАССОВАЯ ЗАГРУЗКА МЕСЯЦА) =================
@app.get("/api/expenses/month")
async def get_expenses_month(month_str: str, user: str = "all"):
    try:
        try:
            worksheet = find_worksheet(sh, month_str)
        except gspread.WorksheetNotFound:
            return JSONResponse({
                "status": "sheet_not_found",
                "sheet_exists": False,
                "month_str": month_str,
                "message": f"Лист на {month_str} не найден в таблице"
            })

        all_values = worksheet.get_all_values()
        cat_rows, has_levels = get_category_rows(all_values)
        day_offset = 2 if has_levels else 1

        num_days = 0
        if all_values and len(all_values) > 0:
            for c in all_values[0][day_offset:]:
                if 'итого' in c.lower():
                    break
                num_days += 1
        if num_days < 28 or num_days > 31:
            num_days = 30

        data_maxim = {str(d): {} for d in range(1, num_days + 1)}
        data_yasya = {str(d): {} for d in range(1, num_days + 1)}
        data_total = {str(d): {} for d in range(1, num_days + 1)}

        for k, rows in cat_rows.items():
            r_tot = rows['total'] - 1
            r_max = rows['maxim'] - 1
            r_yas = rows['yasya'] - 1

            for d in range(1, num_days + 1):
                col_i = d - 1 + day_offset
                v_max = clean_val(all_values[r_max][col_i]) if r_max < len(all_values) and len(all_values[r_max]) > col_i else ""
                v_yas = clean_val(all_values[r_yas][col_i]) if r_yas < len(all_values) and len(all_values[r_yas]) > col_i else ""
                v_tot = clean_val(all_values[r_tot][col_i]) if r_tot < len(all_values) and len(all_values[r_tot]) > col_i else ""

                if not v_tot and (v_max or v_yas):
                    try:
                        tot_f = (float(v_max) if v_max else 0) + (float(v_yas) if v_yas else 0)
                        v_tot = str(int(tot_f)) if float(tot_f).is_integer() else str(round(tot_f, 2))
                    except ValueError:
                        pass

                data_maxim[str(d)][k] = v_max
                data_yasya[str(d)][k] = v_yas
                data_total[str(d)][k] = v_tot

        totals_by_day = {"maxim": {}, "yasya": {}, "total": {}}
        for d in range(1, num_days + 1):
            col_i = d - 1 + day_offset
            t_max = clean_val(all_values[52][col_i]) if len(all_values) > 52 and len(all_values[52]) > col_i else ""
            t_yas = clean_val(all_values[53][col_i]) if len(all_values) > 53 and len(all_values[53]) > col_i else ""
            t_all = clean_val(all_values[54][col_i]) if len(all_values) > 54 and len(all_values[54]) > col_i else ""

            if not t_max:
                sum_m = sum(float(data_maxim[str(d)][k]) for k in data_maxim[str(d)] if data_maxim[str(d)][k])
                t_max = str(int(sum_m)) if float(sum_m).is_integer() else str(round(sum_m, 2))
            if not t_yas:
                sum_y = sum(float(data_yasya[str(d)][k]) for k in data_yasya[str(d)] if data_yasya[str(d)][k])
                t_yas = str(int(sum_y)) if float(sum_y).is_integer() else str(round(sum_y, 2))
            if not t_all:
                try:
                    tot_s = (float(t_max) if t_max else 0) + (float(t_yas) if t_yas else 0)
                    t_all = str(int(tot_s)) if float(tot_s).is_integer() else str(round(tot_s, 2))
                except ValueError:
                    pass

            totals_by_day["maxim"][str(d)] = t_max
            totals_by_day["yasya"][str(d)] = t_yas
            totals_by_day["total"][str(d)] = t_all

        max_month = sum(float(totals_by_day["maxim"][str(d)]) for d in range(1, num_days + 1) if totals_by_day["maxim"][str(d)])
        yas_month = sum(float(totals_by_day["yasya"][str(d)]) for d in range(1, num_days + 1) if totals_by_day["yasya"][str(d)])
        all_month = max_month + yas_month

        month_summary = {
            "maxim_total": int(max_month) if float(max_month).is_integer() else round(float(max_month), 2),
            "yasya_total": int(yas_month) if float(yas_month).is_integer() else round(float(yas_month), 2),
            "all_total": int(all_month) if float(all_month).is_integer() else round(float(all_month), 2)
        }

        user_req = str(user).lower()
        if user_req == "maxim":
            selected_data = data_maxim
        elif user_req == "yasya":
            selected_data = data_yasya
        else:
            selected_data = data_total

        return JSONResponse({
            "status": "ok",
            "data": selected_data,
            "data_maxim": data_maxim,
            "data_yasya": data_yasya,
            "data_total": data_total,
            "totals_by_day": totals_by_day,
            "month_summary": month_summary,
            "num_days": num_days
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/api/day")
async def save_day(request: Request):
    try:
        payload = await request.json()
        dt = datetime.strptime(payload.get("date"), "%Y-%m-%d")
        data = payload.get("data", {})
        user = str(payload.get("user", "maxim")).lower()

        try:
            worksheet = find_worksheet(sh, dt)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист на {dt.strftime('%m.%Y')} не найден в таблице. Создайте его кнопкой '+ Создать лист'."})

        all_values = worksheet.get_all_values()
        cat_rows, has_levels = get_category_rows(all_values)
        day_offset = 2 if has_levels else 1
        col_idx = dt.day + day_offset

        cells_to_update = []
        for key, val in data.items():
            if key in cat_rows:
                if has_levels:
                    target_row = cat_rows[key]['yasya'] if user == 'yasya' else cat_rows[key]['maxim']
                else:
                    target_row = cat_rows[key]['total']
                val_to_write = float(str(val).replace(',', '.')) if str(val).strip() != "" else ""
                cells_to_update.append(gspread.Cell(row=target_row, col=col_idx, value=val_to_write))

        if cells_to_update:
            worksheet.update_cells(cells_to_update)

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/api/quick-expense")
async def quick_expense(request: Request):
    try:
        payload = await request.json()
        date_str = payload.get("date")
        if date_str:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            dt = datetime.now()

        user = str(payload.get("user", "maxim")).lower()
        key = payload.get("category")
        try:
            amount = float(str(payload.get("amount", "")).replace(',', '.'))
        except (ValueError, TypeError):
            amount = 0.0

        if amount <= 0:
            return JSONResponse({"status": "error", "message": "Введите сумму больше 0"})

        try:
            worksheet = find_worksheet(sh, dt)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист на {dt.strftime('%m.%Y')} не найден в таблице. Создайте его кнопкой '+ Создать лист'."})
        all_values = worksheet.get_all_values()
        cat_rows, has_levels = get_category_rows(all_values)

        if key not in cat_rows:
            return JSONResponse({"status": "error", "message": f"Категория '{key}' не найдена"})

        day_offset = 2 if has_levels else 1
        col_idx = dt.day + day_offset

        if has_levels:
            target_row = cat_rows[key]['yasya'] if user == 'yasya' else cat_rows[key]['maxim']
        else:
            target_row = cat_rows[key]['total']

        cell_raw = worksheet.cell(target_row, col_idx).value or ""
        clean_str = str(cell_raw).replace('₽', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
        existing_val = 0.0
        if clean_str:
            try:
                existing_val = float(clean_str)
            except ValueError:
                existing_val = 0.0

        new_val = existing_val + amount
        val_to_write = int(new_val) if new_val.is_integer() else round(new_val, 2)
        worksheet.update_cell(target_row, col_idx, val_to_write)

        return JSONResponse({
            "status": "ok",
            "user": user,
            "category": key,
            "added": amount,
            "previous": existing_val,
            "new_total": val_to_write,
            "day": dt.day
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

# ================= ДОХОДЫ =================
@app.get("/api/income")
async def get_income(month: str):
    try:
        try:
            worksheet = find_worksheet(sh, month)
        except gspread.WorksheetNotFound:
            return JSONResponse({
                "status": "sheet_not_found",
                "sheet_exists": False,
                "month_str": month,
                "message": f"Лист на {month} не найден в таблице",
                "data": []
            })

        vals = worksheet.get_all_values()
        income_data = []

        has_new_income = False
        for idx in range(min(55, len(vals)), min(75, len(vals))):
            r = vals[idx]
            if len(r) > 2 and 'доходы' in r[2].lower():
                has_new_income = True
                break

        if has_new_income:
            for idx, r in enumerate(vals):
                if len(r) > 2:
                    c2 = r[2].strip()
                    if c2 in ['Максим', 'Яся'] and idx < 62:
                        u = 'maxim' if c2 == 'Максим' else 'yasya'
                        amt = clean_val(r[3] if len(r) > 3 else '')
                        income_data.append({"row": idx + 1, "col": 4, "name": f"Остаток {c2}", "date": "остаток", "amount": amt, "user": u})
                    elif c2 and idx >= 64 and idx <= 71:
                        if 'итого' in c2.lower():
                            continue
                        u = 'maxim' if 'максим' in c2.lower() else ('yasya' if 'яся' in c2.lower() else 'all')
                        amt = clean_val(r[4] if len(r) > 4 else '')
                        income_data.append({"row": idx + 1, "col": 5, "name": c2, "date": r[3] if len(r) > 3 else '', "amount": amt, "user": u})
        else:
            col1 = worksheet.col_values(1)
            col2 = worksheet.col_values(2) if worksheet.col_count >= 2 else []
            col3 = worksheet.col_values(3) if worksheet.col_count >= 3 else []
            for source in INCOME_SOURCES:
                if source in col1:
                    row_idx = col1.index(source)
                    amt = clean_val(col3[row_idx] if row_idx < len(col3) else '')
                    u = 'maxim' if 'максим' in source.lower() else ('yasya' if 'яся' in source.lower() else 'all')
                    income_data.append({
                        "row": row_idx + 1,
                        "col": 3,
                        "name": source,
                        "date": col2[row_idx] if row_idx < len(col2) else '',
                        "amount": amt,
                        "user": u
                    })

        return JSONResponse({"status": "ok", "data": income_data})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/api/income")
async def save_income(request: Request):
    try:
        payload = await request.json()
        month_str = payload.get("month_str")
        items = payload.get("items", [])

        try:
            worksheet = find_worksheet(sh, month_str)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист на {month_str} не найден в таблице. Создайте его кнопкой '+ Создать лист'."})

        cells_to_update = []
        for item in items:
            row = int(item["row"])
            col = int(item.get("col", 5 if row >= 65 else (4 if row >= 58 else 3)))
            raw_amt = str(item.get("amount", "")).replace(',', '.').strip()
            val = float(raw_amt) if raw_amt != "" else ""
            cells_to_update.append(gspread.Cell(row=row, col=col, value=val))

        if cells_to_update:
            worksheet.update_cells(cells_to_update)

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

# ================= ОБЯЗАТЕЛЬНЫЕ ПЛАТЕЖИ =================
@app.get("/api/mandatory-payments")
async def get_mandatory_payments(month: str):
    try:
        try:
            worksheet = find_worksheet(sh, month)
        except gspread.WorksheetNotFound:
            return JSONResponse({
                "status": "sheet_not_found",
                "sheet_exists": False,
                "month_str": month,
                "message": f"Лист на {month} не найден в таблице",
                "data": []
            })

        vals = worksheet.get_all_values()

        header_row, name_col, val_col = -1, -1, -1
        for r_idx, row in enumerate(vals):
            for c_idx, cell in enumerate(row):
                if "обязательные платежи" in cell.lower():
                    header_row = r_idx
                    name_col = c_idx
                    val_col = c_idx + 1
                    break
            if header_row != -1:
                break

        items = []
        if header_row != -1:
            for r_idx in range(header_row + 1, min(len(vals), header_row + 15)):
                row = vals[r_idx]
                if len(row) > name_col and row[name_col].strip():
                    name = row[name_col].strip()
                    val = row[val_col].strip() if len(row) > val_col else ""
                    status_col_idx = val_col + 1
                    status_raw = row[status_col_idx].strip() if len(row) > status_col_idx else ""
                    is_paid = status_raw.lower() in ["оплачено", "true", "да", "1", "v", "✓"]
                    items.append({
                        "row": r_idx + 1,
                        "col": val_col + 1,
                        "status_col": status_col_idx + 1,
                        "name": name,
                        "value": val,
                        "is_paid": is_paid
                    })
                else:
                    if len(items) > 0:
                        break

        return JSONResponse({"status": "ok", "data": items})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/api/mandatory-payments")
async def save_mandatory_payments(request: Request):
    try:
        payload = await request.json()
        month_str = payload.get("month_str")
        items = payload.get("items", [])

        try:
            worksheet = find_worksheet(sh, month_str)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист на {month_str} не найден в таблице. Создайте его кнопкой '+ Создать лист'."})

        cells_to_update = []
        for item in items:
            row = int(item["row"])
            col = int(item.get("col", 8))
            status_col = int(item.get("status_col", col + 1))
            val = str(item.get("value", "")).strip()
            is_paid = bool(item.get("is_paid", False))

            try:
                num_val = float(val.replace(' ', '').replace(',', '.'))
                val_to_save = int(num_val) if num_val.is_integer() else num_val
            except ValueError:
                val_to_save = val
            cells_to_update.append(gspread.Cell(row=row, col=col, value=val_to_save))

            status_val = "Оплачено" if is_paid else ""
            cells_to_update.append(gspread.Cell(row=row, col=status_col, value=status_val))

        if cells_to_update:
            worksheet.update_cells(cells_to_update)

        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

# ================= СОЗДАНИЕ НОВОГО ЛИСТА МЕСЯЦА =================
@app.post("/api/create-month-sheet")
async def create_month_sheet(request: Request):
    try:
        payload = await request.json()
        month_str = payload.get("month_str", "")

        months_ru = ["январь", "февраль", "март", "апрель", "май", "июнь", 
                     "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
        s = str(month_str).strip().lower()
        m_idx = None
        year = None
        for i, m in enumerate(months_ru, start=1):
            if m in s:
                m_idx = i
                break
        parts = s.replace('.', ' ').replace('/', ' ').replace('-', ' ').split()
        for p in parts:
            if p.isdigit() and len(p) == 4:
                year = int(p)
            elif p.isdigit() and 1 <= int(p) <= 12 and m_idx is None:
                m_idx = int(p)

        if not m_idx or not year:
            return JSONResponse({"status": "error", "message": f"Не удалось определить месяц из строки: '{month_str}'"})

        target_title = f"{m_idx:02d}.{year}"

        all_worksheets = sh.worksheets()
        titles = {ws.title.lower(): ws for ws in all_worksheets}
        if target_title.lower() in titles:
            return JSONResponse({"status": "ok", "message": f"Лист {target_title} уже существует", "title": target_title})

        template_ws = None
        for ws in all_worksheets:
            if ws.title.lower() == "11.2026":
                template_ws = ws
                break
        if not template_ws:
            for ws in all_worksheets:
                if any(ch.isdigit() for ch in ws.title) and "." in ws.title:
                    template_ws = ws
                    break
        if not template_ws:
            template_ws = all_worksheets[-1]

        new_ws = template_ws.duplicate(new_sheet_name=target_title)

        days_in_target = calendar.monthrange(year, m_idx)[1]
        vals = new_ws.get_all_values()
        cat_rows, has_levels = get_category_rows(vals)
        day_offset = 2 if has_levels else 1

        days_in_template = 0
        if vals and len(vals) > 0:
            for c in vals[0][day_offset:]:
                if 'итого' in c.lower():
                    break
                days_in_template += 1
        if days_in_template < 28 or days_in_template > 31:
            days_in_template = 30

        month_short = ["янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.", "окт.", "нояб.", "дек."]
        cur_m_name = month_short[m_idx - 1]

        if days_in_target == 31 and days_in_template == 30:
            new_ws.insert_cols([['']], col=33, inherit_from_before=True)
            vals = new_ws.get_all_values()
            cat_rows, has_levels = get_category_rows(vals)

            cells_to_set = []
            for k, rows in cat_rows.items():
                r_tot = rows['total']
                r_max = rows['maxim']
                r_yas = rows['yasya']
                cells_to_set.append(gspread.Cell(row=r_tot, col=33, value=f"=AG{r_max}+AG{r_yas}"))
                cells_to_set.append(gspread.Cell(row=r_tot, col=34, value=f"=AH{r_max}+AH{r_yas}"))
                cells_to_set.append(gspread.Cell(row=r_max, col=34, value=f"=SUM(C{r_max}:AG{r_max})"))
                cells_to_set.append(gspread.Cell(row=r_yas, col=34, value=f"=SUM(C{r_yas}:AG{r_yas})"))

            max_cells = '+'.join([f"AG{rows['maxim']}" for rows in cat_rows.values()])
            yas_cells = '+'.join([f"AG{rows['yasya']}" for rows in cat_rows.values()])
            cells_to_set.append(gspread.Cell(row=53, col=33, value=f"={max_cells}"))
            cells_to_set.append(gspread.Cell(row=54, col=33, value=f"={yas_cells}"))
            cells_to_set.append(gspread.Cell(row=55, col=33, value="=AG53+AG54"))
            new_ws.update_cells(cells_to_set, value_input_option='USER_ENTERED')

        header_cells = []
        for d in range(1, days_in_target + 1):
            col_num = day_offset + d
            header_cells.append(gspread.Cell(row=1, col=col_num, value=f"{d} {cur_m_name}"))
        new_ws.update_cells(header_cells, value_input_option='USER_ENTERED')

        end_col_letter = 'AG' if days_in_target >= 31 else 'AF'
        clear_ranges = []
        for k, rows in cat_rows.items():
            r_max = rows['maxim']
            r_yas = rows['yasya']
            clear_ranges.append(f"C{r_max}:{end_col_letter}{r_yas}")

        clear_ranges.append("D59:D60")
        clear_ranges.append("E65:E71")
        clear_ranges.append("I65:I71")

        new_ws.batch_clear(clear_ranges)

        return JSONResponse({
            "status": "ok",
            "message": f"Лист {target_title} успешно создан!",
            "title": target_title
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.api_route("/ping", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
async def ping_check():
    return {"status": "ok"}

@app.on_event("startup")
async def on_startup():
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Бюджет", web_app=WebAppInfo(url=WEBAPP_URL))
        )
    except Exception as e:
        print("Menu button error:", e)
    asyncio.create_task(dp.start_polling(bot))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)