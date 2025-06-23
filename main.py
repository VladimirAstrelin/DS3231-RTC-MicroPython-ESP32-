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
WIFI_SSID = "WIFI_SSID"
WIFI_PASS = "WIFI_PASS"
TIMEZONE_OFFSET = 3  # UTC+3 for Odessa
DEBOUNCE_MS = 300

# === Hardware Initialization ===
i2c = SoftI2C(sda=Pin(21), scl=Pin(22))
lcd = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)
lcd.backlight_on()
rtc = DS3231(i2c)

# Encoder setup
encoder = rotary_irq_esp.RotaryIRQ(
    pin_num_clk=18,
    pin_num_dt=19,
    min_val=0,
    max_val=1,
    reverse=False,
    range_mode=rotary_irq_esp.RotaryIRQ.RANGE_BOUNDED
)

encoder_button = Pin(23, Pin.IN, Pin.PULL_UP)

# Menu states
STATE_MAIN = 0
STATE_NTP_MENU = 1
STATE_RTC_MENU = 2

# Global variables
current_state = STATE_MAIN
current_pos = 0
menu_offset = 0  # For scrolling long menus
button_pressed = False
last_button_time = 0
last_time_update = 0
last_encoder_val = 0
display_time = ""
display_date = ""
ntp_sync_result = None

# Button interrupt handler
def handle_button(pin):
    global button_pressed, last_button_time
    current_time = ticks_ms()
    if current_time - last_button_time > DEBOUNCE_MS:
        button_pressed = True
        last_button_time = current_time

encoder_button.irq(trigger=Pin.IRQ_FALLING, handler=handle_button)

def format_time(hh, mm, ss):
    return f"{hh:02d}:{mm:02d}:{ss:02d}"

def format_date(d, m, y):
    return f"{d:02d}.{m:02d}.{y}"

def update_clock_display():
    global display_time, display_date
    try:
        y, m, d, hh, mm, ss = rtc.read_time()
        
        new_time = format_time(hh, mm, ss)
        new_date = format_date(d, m, y)
        
        if new_time != display_time:
            display_time = new_time
            lcd.move_to(0, 0)
            lcd.putstr(f"Time: {display_time:>13}")
            
        if new_date != display_date:
            display_date = new_date
            lcd.move_to(0, 1)
            lcd.putstr(f"Date: {display_date:>13}")
            
    except Exception as e:
        print("RTC read error:", e)

def clear_menu_lines():
    lcd.move_to(0, 2)
    lcd.putstr(" " * 20)
    lcd.move_to(0, 3)
    lcd.putstr(" " * 20)

def show_main_menu():
    global current_pos, menu_offset
    clear_menu_lines()
    items = [
        "Get NTP Date Time",
        "Get RTC Date Time"
    ]
    
    # Display 2 menu items
    for i in range(2):
        if current_pos == i:
            lcd.move_to(0, 2 + i)
            lcd.putstr(">" + items[i][:19])
        else:
            lcd.move_to(0, 2 + i)
            lcd.putstr(" " + items[i][:19])

def show_ntp_menu():
    global current_pos, menu_offset
    clear_menu_lines()
    items = [
        "Sync with NTP",
        "Save to RTC",
        "Back"
    ]
    
    # Handle scrolling
    if current_pos < menu_offset:
        menu_offset = current_pos
    elif current_pos > menu_offset + 1:
        menu_offset = current_pos - 1
    
    # Display 2 menu items at a time
    for i in range(2):
        pos = menu_offset + i
        if pos < len(items):
            lcd.move_to(0, 2 + i)
            if pos == current_pos:
                lcd.putstr(">" + items[pos][:19])
            else:
                lcd.putstr(" " + items[pos][:19])

def show_rtc_menu():
    global current_pos, menu_offset
    clear_menu_lines()
    items = [
        "View RTC Time",
        "Back"
    ]
    
    # Display all menu items (only 2)
    for i in range(2):
        if i < len(items):
            lcd.move_to(0, 2 + i)
            if current_pos == i:
                lcd.putstr(">" + items[i][:19])
            else:
                lcd.putstr(" " + items[i][:19])

def show_message(line1, line2="", duration=2):
    update_clock_display()
    clear_menu_lines()
    lcd.move_to(0, 2)
    lcd.putstr(line1[:20])
    lcd.move_to(0, 3)
    lcd.putstr(line2[:20] if line2 else " " * 20)
    sleep(duration)
    update_display()

def update_display():
    update_clock_display()
    if current_state == STATE_MAIN:
        show_main_menu()
    elif current_state == STATE_NTP_MENU:
        show_ntp_menu()
    elif current_state == STATE_RTC_MENU:
        show_rtc_menu()

def apply_timezone(tm):
    t = mktime(tm[:8]) + TIMEZONE_OFFSET * 3600
    return localtime(t)

def sync_with_ntp():
    global ntp_sync_result
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        show_message("Connecting to WiFi", "Please wait...")
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
            ntp_sync_result = (y, m, d, hh, mm, ss)
            # Immediately update RTC and display
            rtc.set_time((y, m, d, hh, mm, ss))
            update_clock_display()
            show_message("NTP Sync Success!", f"{hh:02d}:{mm:02d} {d:02d}.{m:02d}")
            return True
        except Exception as e:
            show_message("NTP Sync Failed", str(e))
            return False
    else:
        show_message("WiFi Connection", "Failed!")
        return False

def save_to_rtc():
    global ntp_sync_result
    if ntp_sync_result:
        try:
            y, m, d, hh, mm, ss = ntp_sync_result
            rtc.set_time((y, m, d, hh, mm, ss))
            update_clock_display()
            show_message("Time Saved to RTC", "Successfully!")
            return True
        except Exception as e:
            show_message("Save to RTC Failed", str(e))
            return False
    else:
        show_message("No NTP Data", "Sync first!")
        return False

def show_rtc_time():
    try:
        y, m, d, hh, mm, ss = rtc.read_time()
        show_message("Current RTC Time:", f"{hh:02d}:{mm:02d}:{ss:02d}")
        show_message("Current RTC Date:", f"{d:02d}.{m:02d}.{y}")
    except Exception as e:
        show_message("RTC Read Error", str(e))

# Main loop
update_display()
last_encoder_val = encoder.value()

while True:
    current_time = ticks_ms()
    
    # Update clock every second
    if current_time - last_time_update >= 1000:
        update_clock_display()
        last_time_update = current_time
    
    # Handle encoder rotation
    new_val = encoder.value()
    if new_val != last_encoder_val:
        current_pos = new_val
        update_display()
        last_encoder_val = new_val
    
    # Handle button press
    if button_pressed:
        button_pressed = False
        
        if current_state == STATE_MAIN:
            if current_pos == 0:  # NTP menu
                current_state = STATE_NTP_MENU
                encoder.set(max_val=2)  # 3 items (0-2)
                current_pos = 0
                menu_offset = 0
            elif current_pos == 1:  # RTC menu
                current_state = STATE_RTC_MENU
                encoder.set(max_val=1)  # 2 items (0-1)
                current_pos = 0
                menu_offset = 0
            
        elif current_state == STATE_NTP_MENU:
            if current_pos == 0:  # Sync with NTP
                sync_with_ntp()
            elif current_pos == 1:  # Save to RTC
                save_to_rtc()
            elif current_pos == 2:  # Back
                current_state = STATE_MAIN
                encoder.set(max_val=1)  # 2 items in main menu
                current_pos = 0
                menu_offset = 0
            
        elif current_state == STATE_RTC_MENU:
            if current_pos == 0:  # View RTC time
                show_rtc_time()
            elif current_pos == 1:  # Back
                current_state = STATE_MAIN
                encoder.set(max_val=1)  # 2 items in main menu
                current_pos = 0
                menu_offset = 0
        
        update_display()
    
    sleep(0.05)