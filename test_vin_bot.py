import logging
import os
import aiohttp
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN")
PARTSAPI_KEY_VIN       = os.getenv("PARTSAPI_KEY_VIN")
PARTSAPI_KEY_CROSSES   = os.getenv("PARTSAPI_KEY_CROSSES")
PARTSAPI_KEY_VINDECODE = os.getenv("PARTSAPI_KEY_VINDECODE")
BASE_URL = "https://api.partsapi.ru"


# ══════════════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ══════════════════════════════════════════════════════════════════

def normalize_article(article: str) -> str:
    return article.replace("-", "").replace(" ", "").replace(".", "").strip().upper()


def brand_root(brand: str) -> str:
    b = brand.upper()
    for suffix in ("FILTERS", "FILTER", "AUTO", "PARTS", "GROUP"):
        if b.endswith(suffix) and len(b) > len(suffix) + 2:
            b = b[:-len(suffix)].strip()
    return b


# ══════════════════════════════════════════════════════════════════
#  ГРУЗОВЫЕ БРЕНДЫ — исключаем из легковых результатов
# ══════════════════════════════════════════════════════════════════

TRUCK_BRANDS = {
    "MERITOR", "RENAULT TRUCKS", "VOLVO", "DAF", "SCANIA",
    "MAN", "IVECO", "BERLIET", "IKARUS", "INTERNATIONAL HARV.",
    "INTERNATIONAL", "KENWORTH", "PETERBILT", "FREIGHTLINER",
    "MACK", "NAVISTAR", "CATERPILLAR", "CUMMINS", "PACCAR",
    "WABCO", "KNORR-BREMSE", "HALDEX", "BPW", "SAF-HOLLAND",
}


# ══════════════════════════════════════════════════════════════════
#  OEM ПРЕФИКСЫ ПО МАРКЕ + КАТЕГОРИИ
# ══════════════════════════════════════════════════════════════════

OEM_PREFIXES: dict[str, dict[str, list[str]]] = {
    "TOYOTA": {
        "5":    ["43040", "43041", "43410", "43420", "43470"],
        "13":   ["43430", "43401"],
        "7":    ["90915", "15601", "15607"],
        "8":    ["17801"],
        "9":    ["23300", "23301", "77024"],
        "424":  ["87139"],
        "281":  ["04460", "04465", "04466", "04491"],
        "82":   ["4351", "4352"],
        "123":  ["4243"],
        "78":   ["4775", "4778"],
        "83":   ["9094706", "47331"],
        "124":  ["4640", "4641"],
        "277":  ["4757", "4755"],
        "1041": ["4851", "4852", "4853", "4854"],
        "198":  ["4851", "4852"],
        "188":  ["4861", "4860"],
        "273":  ["4806", "4807", "4808", "4809"],
        "1037": ["4333", "4330"],
        "274":  ["4881", "4882"],
        "331":  ["9038", "48815", "48818"],
        "304":  ["48820", "48830"],
        "655":  ["4245", "9036"],
        "653":  ["4232", "4251", "4252"],
        "306":  ["13568", "13507"],
        "307":  ["13506", "13505"],
        "305":  ["90916", "99368", "99367"],
        "308":  ["13505", "13506", "13567"],
        "470":  ["1640", "1641"],
        "316":  ["9091603"],
        "1046": ["1610"],
        "286":  ["4520", "4510"],
        "284":  ["4503", "4550"],
        "51":   ["4504"],
        "686":  ["9091901"],
        "689":  ["9091902", "9008019"],
        "2":    ["2810"],
        "4":    ["2700", "2706"],
        "479":  ["3125", "3101"],
        "262":  ["3125", "3126"],
        "48":   ["3123", "3117"],
    },
    "KIA":      {"8":["28113"],"7":["2630035","2630042"],"424":["97133"],"281":["58101","58301"],"82":["51712","58411"],"1041":["546512","546602"],"686":["1884211","1884208"]},
    "HYUNDAI":  {"8":["28113"],"7":["2630035","2630042"],"424":["97133"],"281":["58101","58301"],"82":["51712","58411"],"1041":["546512","546602"],"686":["1884211","1884208"]},
    "NISSAN":   {"8":["16546"],"7":["15208"],"281":["4106"],"82":["4020"],"1041":["5630","5631"],"686":["2240"]},
    "HONDA":    {"8":["17220"],"7":["15400"],"281":["43022","45022"],"82":["4510","4520"],"686":["98079","12290"]},
    "MITSUBISHI":{"8":["1500A","MR968274"],"7":["MD360935","MZ690072"],"281":["4605A","MN102468"],"82":["MN102503"],"686":["MN163235","1882A"]},
    "LADA":     {"8":["2112","21083"],"7":["21080","2101"],"281":["11180","21080"],"686":["21080","2101"]},
    "AUDI":     {"8":["8K0133843","1K0129620"],"7":["06J115403","06D115403"],"424":["8K0819439"],"281":["8K0698151","4G0698151"],"82":["8K0615301","4G0615301"],"686":["101905611","101000033"]},
    "VOLKSWAGEN":{"8":["1K0129620","6Q0129620"],"7":["06J115403","03C115561"],"424":["1K1819653","6Q0819653"],"281":["1K0698151","6Q0698451"],"82":["1K0615301","5C0615301"],"686":["101905611","101000033"]},
    "BMW":      {"8":["13717","13718"],"7":["11427","11428"],"424":["64119"],"281":["34116","34216"],"82":["34106","34116"],"686":["12120","12130"]},
    "MERCEDES-BENZ":{"8":["A6510940004","A6420940000"],"7":["A6511800009","A6421800109"],"424":["A2128300018"],"281":["A0054208320","A0044205820"],"82":["A0044210312"],"686":["A0041598903"]},
    "FORD":     {"8":["1S7Z9601AA","7M519601AA"],"7":["1S7Z6731AA","CM5Z6731A"],"281":["8V612001AA","1497792"],"82":["1497632","6G912B257AA"],"686":["3M5Z12029AA","CYFS12YA"]},
    "OPEL":     {"8":["13271187","5834039"],"7":["93185674","650316"],"281":["13502149","93179502"],"82":["93179697","13502145"],"686":["5960071","12573190"]},
    "MAZDA":    {"8":["LF10133A0","RF2N133A0"],"7":["LF10143029A","ZZM114302"],"281":["GHP29328ZA","BP4K43280A"],"82":["GJ6A2625XA","GHY93325XA"],"686":["LFY118110","ZZM118110"]},
    "SUBARU":   {"8":["16546AA120","16546AA010"],"7":["15208AA100","15208AA160"],"281":["26296FE000","26696FE000"],"82":["26300FE000","26300FE030"],"686":["22401AA651","22401AA720"]},
}

SHRUS_POSITION_FILTER = {
    "5": {"Наружний": ["434"], "Внутренний": ["430"]}
}


def classify_shrus(article: str, cat_id: str) -> str | None:
    rules = SHRUS_POSITION_FILTER.get(cat_id)
    if not rules:
        return None
    clean = normalize_article(article)
    for label, prefixes in rules.items():
        for p in prefixes:
            if clean.startswith(p):
                return label
    return None


# ══════════════════════════════════════════════════════════════════
#  СЛОВАРЬ ЗАПЧАСТЕЙ
# ══════════════════════════════════════════════════════════════════

PARTS_MAP = {
    "шрус наружний":        ([("5", "Наружний")],   "ШРУС"),
    "шрус внешний":         ([("5", "Наружний")],   "ШРУС"),
    "шрус внутренний":      ([("5", "Внутренний")], "ШРУС"),
    "граната наружняя":     ([("5", "Наружний")],   "ШРУС"),
    "граната внутренняя":   ([("5", "Внутренний")], "ШРУС"),
    "шрус":                 ([("5", "")],            "ШРУС"),
    "граната":              ([("5", "")],            "ШРУС"),
    "приводной вал":        ([("13", "")],           "Приводной вал"),
    "полуось":              ([("13", "")],           "Приводной вал"),
    "амортизатор":          ([("1041", "")],         "Амортизатор"),
    "стойка стабилизатора": ([("304", "")],          "Стойка стабилизатора"),
    "стойка":               ([("198", "")],          "Стойка амортизатора"),
    "пружина":              ([("188", "")],          "Пружина подвески"),
    "рычаг подвески":       ([("273", "")],          "Рычаг подвески"),
    "рычаг":                ([("273", "")],          "Рычаг подвески"),
    "шаровая опора":        ([("1037", "")],         "Шаровая опора"),
    "шаровая":              ([("1037", "")],         "Шаровая опора"),
    "сайлентблок":          ([("331", "")],          "Сайлентблок"),
    "подшипник ступицы":    ([("655", "")],          "Подшипник ступицы"),
    "ступичный подшипник":  ([("655", "")],          "Подшипник ступицы"),
    "ступица":              ([("653", "")],          "Ступица"),
    "тормозные колодки":    ([("281", "")],          "Тормозные колодки"),
    "колодки":              ([("281", "")],          "Тормозные колодки"),
    "тормозной диск":       ([("82", "")],           "Тормозной диск"),
    "диск тормозной":       ([("82", "")],           "Тормозной диск"),
    "тормозной барабан":    ([("123", "")],          "Тормозной барабан"),
    "барабан":              ([("123", "")],          "Тормозной барабан"),
    "суппорт":              ([("78", "")],           "Тормозной суппорт"),
    "колесный цилиндр":     ([("277", "")],          "Колесный цилиндр"),
    "тормозной шланг":      ([("83", "")],           "Тормозной шланг"),
    "ручник":               ([("124", "")],          "Трос ручника"),
    "масляный фильтр":      ([("7", "")],            "Масляный фильтр"),
    "фильтр масла":         ([("7", "")],            "Масляный фильтр"),
    "воздушный фильтр":     ([("8", "")],            "Воздушный фильтр"),
    "топливный фильтр":     ([("9", "")],            "Топливный фильтр"),
    "салонный фильтр":      ([("424", "")],          "Салонный фильтр"),
    "фильтр салона":        ([("424", "")],          "Салонный фильтр"),
    "ремень грм":           ([("306", "")],          "Ремень ГРМ"),
    "комплект грм":         ([("307", "")],          "Комплект ГРМ"),
    "поликлиновой ремень":  ([("305", "")],          "Поликлиновой ремень"),
    "ремень генератора":    ([("305", "")],          "Поликлиновой ремень"),
    "натяжной ролик":       ([("308", "")],          "Натяжной ролик"),
    "радиатор":             ([("470", "")],          "Радиатор охлаждения"),
    "термостат":            ([("316", "")],          "Термостат"),
    "помпа":                ([("1046", "")],         "Водяной насос"),
    "водяной насос":        ([("1046", "")],         "Водяной насос"),
    "рулевая рейка":        ([("286", "")],          "Рулевая рейка"),
    "рулевая тяга":         ([("284", "")],          "Рулевая тяга"),
    "наконечник":           ([("51", "")],           "Наконечник рул. тяги"),
    "сцепление":            ([("479", "")],          "Комплект сцепления"),
    "диск сцепления":       ([("262", "")],          "Диск сцепления"),
    "выжимной подшипник":   ([("48", "")],           "Выжимной подшипник"),
    "свечи":                ([("686", "")],          "Свеча зажигания"),
    "свеча":                ([("686", "")],          "Свеча зажигания"),
    "катушка":              ([("689", "")],          "Катушка зажигания"),
    "стартер":              ([("2", "")],            "Стартер"),
    "генератор":            ([("4", "")],            "Генератор"),
    "аккумулятор":          ([("1", "")],            "Аккумулятор"),
    "глушитель":            ([("26", "")],           "Глушитель"),
    "катализатор":          ([("429", "")],          "Катализатор"),
}

POSITION_KEYWORDS = {
    "левый": "Лев.", "левая": "Лев.", "лев": "Лев.",
    "правый": "Пр.",  "правая": "Пр.", "прав": "Пр.",
    "передний": "Пер.", "передняя": "Пер.",
    "задний": "Зад.",   "задняя": "Зад.",
}


# ══════════════════════════════════════════════════════════════════
#  ASYNC API
# ══════════════════════════════════════════════════════════════════

async def async_get(session: aiohttp.ClientSession, params: dict, timeout: int = 60):
    try:
        async with session.get(
            BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as r:
            text = await r.text()
            print(f"HTTP {r.status} | {params.get('method')} | {text[:300]}")
            return await r.json(content_type=None)
    except Exception as e:
        print(f"EXCEPTION in {params.get('method')}: {type(e).__name__}: {e}")
        logger.error("API %s error: %s", params.get("method"), e)
        return None


async def api_vindecode(session, vin: str) -> dict | None:
    data = await async_get(session, {
        "method": "VINdecode", "key": PARTSAPI_KEY_VINDECODE,
        "vin": vin, "lang": "ru",
    })
    if not data or not isinstance(data, dict):
        return None
    result = data.get("result", {})
    return next(iter(result.values()), None) if result else None


async def api_get_parts_by_vin(session, vin: str, cat: str) -> list:
    data = await async_get(session, {
        "method": "getPartsbyVIN", "key": PARTSAPI_KEY_VIN,
        "vin": vin, "type": "oem", "cat": cat,
    }, timeout=60)
    print(f"RAW API cat={cat}:", data)
    if not data:
        return []
    return data if isinstance(data, list) else [data]


async def api_get_crosses(session, number: str) -> list:
    data = await async_get(session, {
        "method": "getCrosses", "key": PARTSAPI_KEY_CROSSES,
        "number": normalize_article(number),
    })
    return data if isinstance(data, list) else []


# ══════════════════════════════════════════════════════════════════
#  ПАРСИНГ И ФИЛЬТРАЦИЯ
# ══════════════════════════════════════════════════════════════════

def parse_parts_string(parts_str: str) -> list[tuple[str, str]]:
    result = []
    for chunk in parts_str.split(","):
        chunk = chunk.strip()
        if "|" not in chunk:
            continue
        brand, art = chunk.split("|", 1)
        brand, art = brand.strip(), art.strip()
        if not art or art == "-":
            continue
        if brand.upper() in TRUCK_BRANDS:
            continue
        result.append((brand, art))
    return result


def pick_primary_oem(
    parts: list[tuple[str, str]],
    cat_id: str,
    manu_name: str,
    shrus_filter: str | None = None,
) -> tuple[tuple[str, str] | None, list[tuple[str, str]]]:

    manu_upper = manu_name.upper() if manu_name else ""
    prefixes = (OEM_PREFIXES.get(manu_upper) or {}).get(cat_id, [])

    # Только наша марка
    brand_parts = [(b, a) for b, a in parts if b.upper() == manu_upper]
    if not brand_parts:
        brand_parts = parts

    # Фильтр по префиксам
    if prefixes:
        filtered = [(b, a) for b, a in brand_parts
                    if any(normalize_article(a).startswith(normalize_article(p))
                           for p in prefixes)]
        if filtered:
            brand_parts = filtered

    # ШРУС позиция
    if shrus_filter and cat_id in SHRUS_POSITION_FILTER:
        pos_filtered = [(b, a) for b, a in brand_parts
                        if classify_shrus(a, cat_id) == shrus_filter]
        if pos_filtered:
            brand_parts = pos_filtered

    # Приоритет: дефис > пробел > остальные
    with_dash  = [(b, a) for b, a in brand_parts if "-" in a]
    with_space = [(b, a) for b, a in brand_parts if "-" not in a and " " in a.strip()]
    modern = with_dash if with_dash else with_space
    pool = sorted(modern, key=lambda x: len(normalize_article(x[1]))) if modern else brand_parts

    if not pool:
        return None, []

    primary = pool[0]
    norm_primary = normalize_article(primary[1])

    other_same_brand = [
        (b, a) for b, a in brand_parts
        if normalize_article(a) != norm_primary
    ]
    return primary, other_same_brand


def filter_crosses(
    raw_crosses: list,
    oem_article: str,
    oem_brand: str,
) -> list[tuple[str, str]]:
    norm_oem = normalize_article(oem_article)
    seen_roots: set = set()
    result = []
    for item in raw_crosses:
        brand = item.get("crossBrand") or item.get("brand") or ""
        art   = item.get("crossNumber") or item.get("number") or ""
        if not brand or not art:
            continue
        if normalize_article(art) == norm_oem:
            continue
        if brand.upper() == oem_brand.upper():
            continue
        root = brand_root(brand)
        if root in seen_roots:
            continue
        seen_roots.add(root)
        result.append((brand, art))
    return result


# ══════════════════════════════════════════════════════════════════
#  ФОРМАТИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════

def format_car_info(vin_info: dict) -> str:
    manu  = vin_info.get("manuName", "")
    model = vin_info.get("modelName", "")
    tname = vin_info.get("typeName", "")
    yf    = str(vin_info.get("yearOfConstrFrom", ""))[:4]
    yt    = str(vin_info.get("yearOfConstrTo", ""))[:4]
    fuel  = vin_info.get("fuelType", "")
    kw    = vin_info.get("powerKwFrom", "")
    hp    = vin_info.get("powerHpFrom", "")
    body  = vin_info.get("bodyStyle", "")
    years = f"{yf}–{yt}" if yt and yt != "0" else f"с {yf}"
    power = f"{kw} кВт / {hp} л.с." if kw and hp else ""
    car   = " ".join(p for p in [manu, model, tname] if p)
    det   = " | ".join(p for p in [body, years, fuel, power] if p)
    return f"{car}\n<i>{det}</i>" if det else car


def find_part(text: str):
    text_lower = text.lower()
    position_parts = []
    for kw, label in POSITION_KEYWORDS.items():
        if kw in text_lower.split() and label not in position_parts:
            position_parts.append(label)
    position_hint = " ".join(position_parts)
    for keyword in sorted(PARTS_MAP.keys(), key=len, reverse=True):
        if keyword in text_lower:
            cats_list, part_name = PARTS_MAP[keyword]
            return cats_list, part_name, position_hint
    return None


def dedupe_name(s: str) -> str:
    seen: set = set()
    out = []
    for w in s.split():
        k = normalize_article(w)
        if k not in seen:
            seen.add(k)
            out.append(w)
    return " ".join(out)


# ══════════════════════════════════════════════════════════════════
#  КОМАНДЫ
# ══════════════════════════════════════════════════════════════════

async def cmd_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ Формат: <code>/vin VIN запчасть</code>\n\n"
            "Примеры:\n"
            "<code>/vin XW7BF4FK60S145161 воздушный фильтр</code>\n"
            "<code>/vin XW7BF4FK60S145161 шрус внутренний левый</code>\n"
            "<code>/vin XW7BF4FK60S145161 тормозные колодки</code>",
            parse_mode="HTML",
        )
        return

    vin       = context.args[0].strip().upper()
    part_text = " ".join(context.args[1:]).strip()

    if len(vin) != 17:
        await update.message.reply_text(
            f"⚠️ VIN <code>{vin}</code> — неверная длина.", parse_mode="HTML"
        )
        return

    found = find_part(part_text)
    if not found:
        await update.message.reply_text(
            f"🤔 Не распознаю: <b>{part_text}</b>\n/help — список запчастей",
            parse_mode="HTML",
        )
        return

    cats_list, part_name, position = found

    async with aiohttp.ClientSession() as session:

        # Шаг 1: VINdecode
        vin_info  = None
        manu_name = ""
        car_str   = ""
        if PARTSAPI_KEY_VINDECODE:
            vin_info = await api_vindecode(session, vin)
            if vin_info:
                manu_name = vin_info.get("manuName", "")
                car_str   = format_car_info(vin_info)

        for cat_id, cat_label in cats_list:
            shrus_filter = None
            if "Наружний" in cat_label:
                shrus_filter = "Наружний"
            elif "Внутренний" in cat_label:
                shrus_filter = "Внутренний"

            pos_pfx    = f"{position} " if position else ""
            cat_pfx    = f"{cat_label} " if cat_label else ""
            group_name = dedupe_name(f"{pos_pfx}{cat_pfx}{part_name}".strip())

            header = [f"⏳ Ищу: <b>{group_name}</b>"]
            if car_str:
                header.append(f"🚗 {car_str}")
            header.append(f"VIN: <code>{vin}</code> | cat: <code>{cat_id}</code>")
            await update.message.reply_text("\n".join(header), parse_mode="HTML")

            # Шаг 2: getPartsbyVIN
            api_results = await api_get_parts_by_vin(session, vin, cat_id)
            if not api_results or not any(r.get("parts") for r in api_results):
                await update.message.reply_text(
                    f"❌ <b>{group_name}</b> — не найдено в базе", parse_mode="HTML"
                )
                continue

            all_parts: list[tuple[str, str]] = []
            seen_p: set = set()
            for r in api_results:
                if r.get("parts"):
                    for brand, art in parse_parts_string(r["parts"]):
                        k = f"{brand.upper()}|{normalize_article(art)}"
                        if k not in seen_p:
                            seen_p.add(k)
                            all_parts.append((brand, art))

            if not all_parts:
                await update.message.reply_text(
                    f"❌ <b>{group_name}</b> — данные в базе есть, но все отфильтрованы (грузовые/пустые)",
                    parse_mode="HTML",
                )
                continue

            # Шаг 3: выбор основного OEM
            primary, other_oem = pick_primary_oem(all_parts, cat_id, manu_name, shrus_filter)

            if not primary:
                await update.message.reply_text(
                    f"❌ Не удалось определить основной OEM для <b>{group_name}</b>",
                    parse_mode="HTML",
                )
                continue

            p_brand, p_art = primary

            # OEM блок
            oem_block = f"  ✅ <b>{p_brand}</b>  <code>{p_art}</code>  <i>(основной)</i>"
            if other_oem:
                others_str = "\n".join(
                    f"  • <code>{a}</code>" for b, a in other_oem[:5]
                )
                oem_block += (
                    f"\n\n  <i>Другие арт. {p_brand} ({len(other_oem)}):</i>\n"
                    + others_str
                )
                if len(other_oem) > 5:
                    oem_block += f"\n  <i>... и ещё {len(other_oem) - 5}</i>"

            # Шаг 4: getCrosses только для основного OEM
            raw_crosses = await api_get_crosses(session, p_art)
            crosses = filter_crosses(raw_crosses, p_art, p_brand) if raw_crosses else []

            if crosses:
                cross_block = "\n".join(
                    f"  • <b>{b}</b>  <code>{a}</code>" for b, a in crosses[:20]
                )
                cross_footer = "\n\n⚠️ <i>Проверяй соответствие перед заказом</i>"
            else:
                cross_block = "  <i>Аналоги не найдены</i>"
                cross_footer = f"\n💡 /crosses <code>{p_art}</code>"

            msg = "\n".join([
                f"✅ <b>{group_name}</b>",
                f"VIN: <code>{vin}</code>",
                *([ f"🚗 {car_str}" ] if car_str else []),
                "─" * 28,
                "🔵 <b>OEM:</b>",
                oem_block,
                "",
                f"🔄 <b>Аналоги ({len(crosses)}) — {p_brand} <code>{p_art}</code>:</b>",
                cross_block + cross_footer,
            ])
            await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_crosses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Формат: <code>/crosses артикул</code>\nПример: <code>/crosses 17801-0H030</code>",
            parse_mode="HTML",
        )
        return
    number = " ".join(context.args).strip()
    await update.message.reply_text(
        f"🔄 Ищу аналоги: <code>{number}</code>...", parse_mode="HTML"
    )
    async with aiohttp.ClientSession() as session:
        raw = await api_get_crosses(session, number)
    if not raw:
        await update.message.reply_text(
            f"⚠️ Аналоги для <code>{number}</code> не найдены.", parse_mode="HTML"
        )
        return
    crosses = filter_crosses(raw, number, "")
    lines = [f"  • <b>{b}</b>  <code>{a}</code>" for b, a in crosses[:25]]
    await update.message.reply_text(
        f"🔄 <b>Аналоги <code>{number}</code> ({len(crosses)}):</b>\n"
        + "\n".join(lines)
        + "\n\n⚠️ <i>Проверяй соответствие перед заказом</i>",
        parse_mode="HTML",
    )


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "<code>/debug vin XW7BF4FK60S145161</code>\n"
            "<code>/debug parts XW7BF4FK60S145161 8</code>\n"
            "<code>/debug crosses 17801-0H030</code>",
            parse_mode="HTML",
        )
        return
    cmd = context.args[0].lower()
    async with aiohttp.ClientSession() as session:
        if cmd == "vin":
            info = await api_vindecode(session, context.args[1].upper())
            if not info:
                await update.message.reply_text("❌ VINdecode не вернул данные.")
                return
            lines = [
                f"<b>Марка:</b> {info.get('manuName')}",
                f"<b>Модель:</b> {info.get('modelName')}",
                f"<b>Модификация:</b> {info.get('typeName')}",
                f"<b>carId:</b> {info.get('carId')}",
                f"<b>Кузов:</b> {info.get('bodyStyle')}",
                f"<b>Топливо:</b> {info.get('fuelType')}",
                f"<b>Объём:</b> {info.get('cylinderCapacityLiter')} л",
                f"<b>Мощность:</b> {info.get('powerKwFrom')} кВт / {info.get('powerHpFrom')} л.с.",
                f"<b>Привод:</b> {info.get('impulsionType')}",
                f"<b>Годы:</b> {str(info.get('yearOfConstrFrom',''))[:4]}–{str(info.get('yearOfConstrTo',''))[:4]}",
            ]
            await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        elif cmd == "parts":
            if len(context.args) < 3:
                await update.message.reply_text("<code>/debug parts VIN cat</code>", parse_mode="HTML")
                return
            params = {
                "method": "getPartsbyVIN", "key": PARTSAPI_KEY_VIN,
                "vin": context.args[1].upper(), "type": "oem", "cat": context.args[2],
            }
            async with session.get(BASE_URL, params=params,
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                raw = await r.text()
            await update.message.reply_text(f"<pre>{raw[:2000]}</pre>", parse_mode="HTML")
        elif cmd == "crosses":
            number = normalize_article(" ".join(context.args[1:]))
            params = {"method": "getCrosses", "key": PARTSAPI_KEY_CROSSES, "number": number}
            async with session.get(BASE_URL, params=params,
                                   timeout=aiohttp.ClientTimeout(total=20)) as r:
                raw = await r.text()
            await update.message.reply_text(f"<pre>{raw[:2000]}</pre>", parse_mode="HTML")
        else:
            await update.message.reply_text("Неизвестная команда. /debug — справка.")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>VIN-поиск запчастей</b>\n\n"
        "<code>/vin VIN запчасть</code> — подобрать деталь\n"
        "<code>/crosses артикул</code> — найти аналоги\n"
        "<code>/debug vin VIN</code> — расшифровка VIN\n"
        "/help — список запчастей",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 <b>Доступные запчасти:</b>\n\n"
        "<b>Фильтры:</b> масляный фильтр, воздушный фильтр, топливный фильтр, салонный фильтр\n\n"
        "<b>Тормоза:</b> колодки, диск, суппорт, барабан, тормозной шланг, колесный цилиндр\n\n"
        "<b>Подвеска:</b> амортизатор, стойка, пружина, рычаг, шаровая, сайлентблок,\n"
        "стойка стабилизатора, подшипник ступицы, ступица\n\n"
        "<b>ШРУС:</b> шрус наружний / шрус внутренний / граната\n\n"
        "<b>ГРМ:</b> ремень грм, натяжной ролик, комплект грм, поликлиновой ремень\n\n"
        "<b>Двигатель:</b> помпа, термостат, радиатор, свечи, катушка\n\n"
        "<b>Трансмиссия:</b> сцепление, диск сцепления, выжимной подшипник\n\n"
        "<b>Позиции:</b> левый / правый / передний / задний",
        parse_mode="HTML",
    )


# ══════════════════════════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════════════════════════

def main():
    for name, val in [
        ("TELEGRAM_BOT_TOKEN",   TELEGRAM_BOT_TOKEN),
        ("PARTSAPI_KEY_VIN",     PARTSAPI_KEY_VIN),
        ("PARTSAPI_KEY_CROSSES", PARTSAPI_KEY_CROSSES),
    ]:
        if not val:
            raise ValueError(f"Нет {name} в .env")
    if not PARTSAPI_KEY_VINDECODE:
        logger.warning("PARTSAPI_KEY_VINDECODE не задан — марка не определяется автоматически")

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("vin",     cmd_vin))
    app.add_handler(CommandHandler("crosses", cmd_crosses))
    app.add_handler(CommandHandler("debug",   cmd_debug))

    logger.info("Бот запущен.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
