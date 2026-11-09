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
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://534c-185-223-171-52.ngrok-free.app") 
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1x_aiXFd3Y0Mh_eHtahz2h6HnW6vx_1GhpbpFup9ljCU")

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
    "зоотовары": "зоотовары",
    "репетитор": "репетитор",
    "здоровье": "здоровье и личная гигиена (+линзы)",
    "уход": "уход за собой (крема, шампуни и т.д.)",
    "развлечения": "развлечения",
    "подарки": "подарки",
    "вклады": "вклады и накопительные счета",
    "учеба": "учеба (печать, канцтовары и т.д.)",
    "билеты": "билеты",
    "квартира": "квартира"
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

def get_sheet_name(dt: datetime):
    months = ["январь", "февраль", "март", "апрель", "май", "июнь", 
              "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    return f"{months[dt.month - 1]} {dt.year}"

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
async def get_expenses_month(month_str: str):
    try:
        months = ["январь", "февраль", "март", "апрель", "май", "июнь", 
                  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
        m_name, y_str = month_str.split()
        m_idx = months.index(m_name) + 1
        y = int(y_str)
        _, num_days = calendar.monthrange(y, m_idx)
        
        try:
            worksheet = sh.worksheet(month_str)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "ok", "data": {str(d): {} for d in range(1, num_days + 1)}, "num_days": num_days})

        all_values = worksheet.get_all_values()
        data = {str(d): {} for d in range(1, num_days + 1)}
        
        in_expenses = False
        for row in all_values:
            if not row or not row[0]: continue
            c_name = row[0].strip().lower().replace('ё', 'е')
            
            # Определяем начало блока Расходов
            if "расходы" in c_name and len(c_name) < 15:
                in_expenses = True
                continue
            # Конец блока ежедневных расходов
            if in_expenses and "итого" in c_name:
                break
            if not in_expenses:
                continue
            
            matched_key = None
            for k, v in CATEGORY_MAPPING.items():
                if v.strip().lower().replace('ё', 'е') == c_name:
                    matched_key = k
                    break
            
            if matched_key:
                for d in range(1, num_days + 1):
                    val = ""
                    if len(row) > d:
                        raw_val = row[d]
                        clean_str = raw_val.replace('₽', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
                        if clean_str:
                            try:
                                f_val = float(clean_str)
                                val = str(int(f_val)) if f_val.is_integer() else clean_str
                            except ValueError:
                                val = clean_str
                        else:
                            val = ""
                    data[str(d)][matched_key] = val
                    
        return JSONResponse({"status": "ok", "data": data, "num_days": num_days})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

@app.post("/api/day")
async def save_day(request: Request):
    try:
        payload = await request.json()
        dt = datetime.strptime(payload.get("date"), "%Y-%m-%d")
        data = payload.get("data", {})
        
        sheet_name = get_sheet_name(dt)
        try:
            worksheet = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист '{sheet_name}' не найден в таблице!"})
            
        col_idx = dt.day + 1
        col1 = [c.strip().lower().replace('ё', 'е') for c in worksheet.col_values(1)]
        
        # Находим диапазон строк блока расходов
        start_idx = 0
        end_idx = len(col1)
        for i, val in enumerate(col1):
            if "расходы" in val and len(val) < 15:
                start_idx = i
                break
        for i in range(start_idx + 1, len(col1)):
            if "итого" in col1[i]:
                end_idx = i
                break

        cells_to_update = []
        for key, val in data.items():
            sheet_cat = CATEGORY_MAPPING.get(key)
            if sheet_cat:
                target_clean = sheet_cat.strip().lower().replace('ё', 'е')
                target_row = None
                for r in range(start_idx, end_idx):
                    if col1[r] == target_clean:
                        target_row = r + 1
                        break
                if not target_row and target_clean in col1:
                    target_row = col1.index(target_clean) + 1
                    
                if target_row:
                    val_to_write = float(val) if val != "" else ""
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
            
        key = payload.get("category")
        try:
            amount = float(str(payload.get("amount", "")).replace(',', '.'))
        except (ValueError, TypeError):
            amount = 0.0
            
        if amount <= 0:
            return JSONResponse({"status": "error", "message": "Введите сумму больше 0"})
            
        sheet_cat = CATEGORY_MAPPING.get(key)
        if not sheet_cat:
            return JSONResponse({"status": "error", "message": f"Категория '{key}' не найдена"})
            
        sheet_name = get_sheet_name(dt)
        try:
            worksheet = sh.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист '{sheet_name}' не найден в таблице!"})
            
        col_idx = dt.day + 1
        col1 = [c.strip().lower().replace('ё', 'е') for c in worksheet.col_values(1)]
        
        start_idx = 0
        end_idx = len(col1)
        for i, val in enumerate(col1):
            if "расходы" in val and len(val) < 15:
                start_idx = i
                break
        for i in range(start_idx + 1, len(col1)):
            if "итого" in col1[i]:
                end_idx = i
                break

        target_clean = sheet_cat.strip().lower().replace('ё', 'е')
        target_row = None
        for r in range(start_idx, end_idx):
            if col1[r] == target_clean:
                target_row = r + 1
                break
        if not target_row and target_clean in col1:
            target_row = col1.index(target_clean) + 1
            
        if not target_row:
            return JSONResponse({"status": "error", "message": "Строка категории не найдена в таблице"})
            
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
            "category": key,
            "added": amount,
            "previous": existing_val,
            "new_total": val_to_write,
            "day": dt.day
        })
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)})

# ================= ДОХОДЫ (ОБНОВЛЕННАЯ ЛОГИКА ФИЛЬТРАЦИИ) =================
@app.get("/api/income")
async def get_income(month: str):
    try:
        try:
            worksheet = sh.worksheet(month)
        except gspread.WorksheetNotFound:
            return JSONResponse({"status": "error", "message": f"Лист '{month}' не найден!"})
        
        # Получаем данные первых трех колонок
        col1 = worksheet.col_values(1)
        col2 = worksheet.col_values(2) if worksheet.col_count >= 2 else []
        col3 = worksheet.col_values(3) if worksheet.col_count >= 3 else []
        
        income_data = []
        
        # Ищем в таблице ТОЛЬКО те пункты, которые есть в INCOME_SOURCES
        for source in INCOME_SOURCES:
            if source in col1:
                row_idx = col1.index(source)
                
                date_val = col2[row_idx] if row_idx < len(col2) else ""
                amount_val = col3[row_idx] if row_idx < len(col3) else ""
                clean_amt = amount_val.replace('₽', '').replace(' ', '').replace('\xa0', '').replace(',', '.')
                if clean_amt:
                    try:
                        f_amt = float(clean_amt)
                        clean_amt = str(int(f_amt)) if f_amt.is_integer() else clean_amt
                    except ValueError:
                        pass
                
                income_data.append({
                    "row": row_idx + 1, 
                    "name": source, 
                    "date": date_val, 
                    "amount": clean_amt
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
        
        worksheet = sh.worksheet(month_str)
        cells_to_update = []
        
        for item in items:
            row = int(item["row"])
            val = float(item["amount"]) if str(item["amount"]) != "" else ""
            cells_to_update.append(gspread.Cell(row=row, col=3, value=val))
            
        if cells_to_update:
            worksheet.update_cells(cells_to_update)
            
        return JSONResponse({"status": "ok"})
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