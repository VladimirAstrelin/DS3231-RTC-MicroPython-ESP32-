from machine import Pin, SoftI2C
from i2c_lcd import I2cLcd
from time import sleep, ticks_ms, localtime, mktime
import rotary_irq_esp
import network
import ntptime
import gc
import ubinascii
from ds3231 import DS3231

# === Конфигурация ===
I2C_ADDR = 0x27
I2C_NUM_ROWS = 4
I2C_NUM_COLS = 20
WIFI_SSID = "Your SSID here"
WIFI_PASS = "Your WIFI_PASS here"
TIMEZONE_OFFSET = 3  # UTC+3 для Одессы

# === Инициализация ===
i2c = SoftI2C(sda=Pin(21), scl=Pin(22))
lcd = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)
lcd.backlight_on()
led = Pin(2, Pin.OUT)
encoder_button = Pin(23, Pin.IN, Pin.PULL_UP)
rtc_ds = DS3231(i2c)

menu_structure = {
    "main": [
        "1. Get Date and Time",
        "2. SD-Card",
        "< Exit"
    ],
    "datetime": [
        "1.1 Sync with NTP",
        "1.2 Get from RTC",
        "1.3 Back"
    ],
    "sync_ntp": [
        "1.1.1 Sync status",
        "1.1.2 Back"
    ],
    "get_rtc": [
        "1.2.1 RTC Date & Time",
        "1.2.2 Back"
    ]
}

current_menu = "main"
current_position = 0
button_pressed = False
last_button_time = 0
button_debounce = 800
last_ntp_status = "Not synced"
last_ntp_time = ""

def handle_button(pin):
    global button_pressed, last_button_time
    if ticks_ms() - last_button_time > button_debounce:
        button_pressed = True
        last_button_time = ticks_ms()

encoder_button.irq(trigger=Pin.IRQ_FALLING, handler=handle_button)

def init_encoder(min_val, max_val):
    global encoder
    encoder = rotary_irq_esp.RotaryIRQ(
        pin_num_clk=18,
        pin_num_dt=19,
        min_val=min_val,
        max_val=max_val,
        reverse=False,
        range_mode=rotary_irq_esp.RotaryIRQ.RANGE_BOUNDED
    )

def update_display():
    lcd.clear()
    items = menu_structure[current_menu]
    start = max(0, min(current_position, len(items) - I2C_NUM_ROWS))
    for i in range(I2C_NUM_ROWS):
        idx = start + i
        if idx < len(items):
            prefix = ">" if idx == current_position else " "
            lcd.move_to(0, i)
            lcd.putstr(f"{prefix} {items[idx][:18]}")

def show_message(line1, line2="", pause=2):
    lcd.clear()
    lcd.putstr(line1)
    if line2:
        lcd.move_to(0, 1)
        lcd.putstr(line2)
    sleep(pause)

def apply_timezone(tm):
    t = mktime(tm[:8]) + TIMEZONE_OFFSET * 3600
    return localtime(t)

def sync_ntp_to_rtc():
    global last_ntp_status, last_ntp_time
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        lcd.clear()
        lcd.putstr("Connecting...")
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(10):
            if wlan.isconnected():
                break
            sleep(1)
    if wlan.isconnected():
        try:
            ntptime.settime()
            tm = apply_timezone(localtime())
            y, m, d, hh, mm, ss = tm[0:6]
            rtc_ds.set_time((y, m, d, hh, mm, ss))
            last_ntp_status = "Success"
            last_ntp_time = f"{d:02d}.{m:02d}.{y} {hh:02d}:{mm:02d}:{ss:02d}"
        except:
            last_ntp_status = "NTP failed"
            last_ntp_time = ""
    else:
        last_ntp_status = "Wi-Fi failed"
        last_ntp_time = ""

def show_ntp_status():
    lcd.clear()
    lcd.putstr(f"NTP: {last_ntp_status}")
    if last_ntp_time:
        lcd.move_to(0, 1)
        lcd.putstr(last_ntp_time)
    sleep(3)

def show_rtc_time():
    try:
        y, m, d, hh, mm, ss = rtc_ds.read_time()
        lcd.clear()
        lcd.putstr(f"{d:02d}.{m:02d}.{y}")
        lcd.move_to(0, 1)
        lcd.putstr(f"{hh:02d}:{mm:02d}:{ss:02d}")
        sleep(3)
    except Exception as e:
        show_message("RTC Error", str(e))

# === Главный цикл ===
init_encoder(0, len(menu_structure["main"]) - 1)
update_display()
last_encoder_val = encoder.value()

while True:
    new_val = encoder.value()
    if new_val != last_encoder_val:
        current_position = new_val
        update_display()
        last_encoder_val = new_val

    if button_pressed:
        button_pressed = False
        current_items = menu_structure[current_menu]
        item = current_items[current_position]

        if item.endswith("Back"):
            if current_menu == "datetime" or current_menu == "sync_ntp" or current_menu == "get_rtc":
                current_menu = "datetime" if current_menu != "datetime" else "main"
            current_position = 0
            init_encoder(0, len(menu_structure[current_menu]) - 1)
            update_display()
            continue

        if item == "< Exit":
            show_message("Goodbye!")
            break

        if current_menu == "main":
            if item.startswith("1."):
                current_menu = "datetime"
            elif item.startswith("2."):
                show_message("Not implemented")
            current_position = 0
            init_encoder(0, len(menu_structure[current_menu]) - 1)
            update_display()
            continue

        if current_menu == "datetime":
            if item.startswith("1.1"):
                sync_ntp_to_rtc()
                current_menu = "sync_ntp"
            elif item.startswith("1.2"):
                current_menu = "get_rtc"
            current_position = 0
            init_encoder(0, len(menu_structure[current_menu]) - 1)
            update_display()
            continue

        if current_menu == "sync_ntp":
            if item.startswith("1.1.1"):
                show_ntp_status()
            update_display()
            continue

        if current_menu == "get_rtc":
            if item.startswith("1.2.1"):
                show_rtc_time()
            update_display()
            continue

    sleep(0.05)






