from machine import Pin, SoftI2C
from i2c_lcd import I2cLcd
from time import sleep, ticks_ms, localtime, mktime
import rotary_irq_esp
import network
import ntptime
from ds3231 import DS3231

# === Configuration ===
I2C_ADDR = 0x27
I2C_NUM_ROWS = 4
I2C_NUM_COLS = 20
WIFI_SSID = "Your WIFI_SSID"
WIFI_PASS = "Your WIFI_PASS"
TIMEZONE_OFFSET = 3  # UTC+3 for Odessa

# === Initialization ===
i2c = SoftI2C(sda=Pin(21), scl=Pin(22))
lcd = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)
lcd.backlight_on()
led = Pin(2, Pin.OUT)
encoder_button = Pin(23, Pin.IN, Pin.PULL_UP)
rtc_ds = DS3231(i2c)

menu_structure = {
    "main": [
        ("1. Date and Time", "datetime"),
        ("2. SD-Card", "not_implemented")
    ],
    "datetime": [
        ("1.1 Sync with NTP", "sync_ntp"),
        ("1.2 Data from RTC", "get_rtc"),
        ("< Back", "back")
    ],
    "sync_ntp": [
        ("1.1.1 Sync status", "show_ntp_status"),
        ("< Back", "back")
    ],
    "get_rtc": [
        ("1.2.1 Current Time", "show_rtc_time"),
        ("< Back", "back")
    ]
}

current_menu = "main"
menu_stack = []
current_position = 0
button_pressed = False
last_button_time = 0
button_debounce = 800
last_ntp_status = "Not synced"
last_ntp_time = ""
last_time_update = 0
time_str = ""
date_str = ""

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

def update_time_display():
    global time_str, date_str
    try:
        y, m, d, hh, mm, ss = rtc_ds.read_time()
        new_time_str = "Time: {:02d}:{:02d}:{:02d}".format(hh, mm, ss)
        new_date_str = "Date: {:02d}.{:02d}.{}".format(d, m, y)
        
        if new_time_str != time_str or new_date_str != date_str:
            time_str = new_time_str
            date_str = new_date_str
            lcd.move_to(0, 0)
            lcd.putstr(time_str)
            lcd.move_to(0, 1)
            lcd.putstr(date_str)
    except Exception as e:
        print("Time update error:", e)

def update_menu_display():
    items = [item[0] for item in menu_structure[current_menu]]
    start = max(0, min(current_position, len(items) - (I2C_NUM_ROWS - 2)))
    
    # Clear only menu lines (rows 2 and 3)
    for row in range(2, I2C_NUM_ROWS):
        lcd.move_to(0, row)
        lcd.putstr(" " * 20)
    
    for i in range(min(I2C_NUM_ROWS - 2, len(items))):
        idx = start + i
        if idx < len(items):
            prefix = ">" if idx == current_position else " "
            lcd.move_to(0, i + 2)
            lcd.putstr("{}{}".format(prefix, items[idx][:19]))

def update_display():
    update_time_display()
    update_menu_display()

def show_message(line1, line2=""):
    # Save current time display by keeping it visible
    update_time_display()
    
    # Clear message area
    for row in range(2, I2C_NUM_ROWS):
        lcd.move_to(0, row)
        lcd.putstr(" " * 20)
    
    # Show new message
    lcd.move_to(0, 2)
    lcd.putstr(line1[:20])
    if line2:
        lcd.move_to(0, 3)
        lcd.putstr(line2[:20])
    
    # Wait for user to see message
    sleep(2)
    
    # Restore menu display
    update_menu_display()

def apply_timezone(tm):
    t = mktime(tm[:8]) + TIMEZONE_OFFSET * 3600
    return localtime(t)

def sync_ntp_to_rtc():
    global last_ntp_status, last_ntp_time
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        show_message("Connecting...")
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
            last_ntp_time = "{:02d}.{:02d}.{} {:02d}:{:02d}:{:02d}".format(d, m, y, hh, mm, ss)
        except:
            last_ntp_status = "NTP Error"
            last_ntp_time = ""
    else:
        last_ntp_status = "Wi-Fi Error"
        last_ntp_time = ""

def show_ntp_status():
    show_message("Status: {}".format(last_ntp_status), last_ntp_time if last_ntp_time else "")

def show_rtc_time():
    try:
        y, m, d, hh, mm, ss = rtc_ds.read_time()
        show_message("Date: {:02d}.{:02d}.{}".format(d, m, y), 
                    "Time: {:02d}:{:02d}:{:02d}".format(hh, mm, ss))
    except Exception as e:
        show_message("RTC Error", str(e))

def handle_menu_selection(action):
    global current_menu, current_position, menu_stack
    
    if action == "back":
        if menu_stack:
            current_menu = menu_stack.pop()
            current_position = 0
        return True
    
    elif action == "not_implemented":
        show_message("Not implemented")
        return True
    
    elif action == "datetime":
        menu_stack.append(current_menu)
        current_menu = action
        current_position = 0
        return True
    
    elif action == "sync_ntp":
        sync_ntp_to_rtc()
        menu_stack.append(current_menu)
        current_menu = action
        current_position = 0
        return True
    
    elif action == "get_rtc":
        menu_stack.append(current_menu)
        current_menu = action
        current_position = 0
        return True
    
    elif action == "show_ntp_status":
        show_ntp_status()
        return False
    
    elif action == "show_rtc_time":
        show_rtc_time()
        return False
    
    return False

# === Main loop ===
init_encoder(0, len(menu_structure[current_menu]) - 1)
update_display()
last_encoder_val = encoder.value()
last_time_update = ticks_ms()

while True:
    current_time = ticks_ms()
    
    # Update time every second
    if current_time - last_time_update >= 1000:
        update_time_display()
        last_time_update = current_time
    
    # Handle encoder
    new_val = encoder.value()
    if new_val != last_encoder_val:
        current_position = new_val
        update_menu_display()
        last_encoder_val = new_val
    
    # Handle button press
    if button_pressed:
        button_pressed = False
        selected_item = menu_structure[current_menu][current_position][1]
        
        if handle_menu_selection(selected_item):
            init_encoder(0, len(menu_structure[current_menu]) - 1)
            last_encoder_val = encoder.value()
            update_menu_display()

    sleep(0.05)