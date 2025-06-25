# FINAL WORKING CODE (25-06-2025)
from machine import Pin, SoftI2C
from time import sleep, ticks_ms, localtime, mktime
import sys
import select
import rotary_irq_esp
import network
import ntptime
from ds3231 import DS3231
from i2c_lcd import I2cLcd
from sound import GORILLACELL_BUZZER, mario
import esp32

# Configuration
I2C_ADDR = 0x27
I2C_NUM_ROWS = 4
I2C_NUM_COLS = 20
WIFI_SSID = "Your WIFI_SSID"
WIFI_PASS = "Your WIFI_PASS"
TIMEZONE_OFFSET = 3  # UTC+3 (Odessa)
DEBOUNCE_MS = 300  # Button debounce time
ENCODER_DEBOUNCE_MS = 50  # Encoder rotation debounce time
SNOOZE_MINUTES = 5
ALARM_DURATION = 300  # 5 minutes in seconds
MELODY_SPEED = 150  # Note duration in ms for Mario theme
MELODY_DUTY = 32767  # PWM duty cycle for buzzer

# Pins
BUZZER_PIN = 4  # D4

# NVS Initialization
nvs = esp32.NVS("alarm_settings")

# Initialization
try:
    i2c = SoftI2C(sda=Pin(21), scl=Pin(22))
    lcd = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)
    lcd.backlight_on()
    lcd.clear()  # Clear display at startup
    rtc = DS3231(i2c)
    buzzer = GORILLACELL_BUZZER(BUZZER_PIN)
    buzzer.pwm.duty_u16(0)  # Explicitly silence buzzer at startup
    encoder = rotary_irq_esp.RotaryIRQ(18, 19, min_val=0, max_val=1, range_mode=rotary_irq_esp.RotaryIRQ.RANGE_BOUNDED)
    encoder_button = Pin(23, Pin.IN, Pin.PULL_UP)
except Exception as e:
    print("Initialization error:", e)
    lcd.move_to(0, 0)
    lcd.putstr("Init Error")
    sleep(2)

previous_pos = -1

# States
STATE_MAIN = 0
STATE_NTP_MENU = 1
STATE_RTC_MENU = 2
STATE_ALARM_CONTROL = 3

current_state = STATE_MAIN
current_pos = 0
menu_offset = 0
button_pressed = False
last_button_time = 0
last_encoder_time = 0
last_encoder_val = 0
display_time = ""
display_date = ""
ntp_sync_result = None
alarm_time = None
alarm_active = False
alarm_playing = False
alarm_paused = False
snooze_time = None
last_alarm_check = 0
alarm_start_time = 0
note_index = 0
last_note_time = 0
force_display_refresh = False

def load_alarm_settings():
    global alarm_time, alarm_active
    try:
        alarm_hour = nvs.get_i32("alarm_hour")
        alarm_minute = nvs.get_i32("alarm_minute")
        alarm_enabled = nvs.get_i32("alarm_enabled")
        if 0 <= alarm_hour <= 23 and 0 <= alarm_minute <= 59:
            alarm_time = (alarm_hour, alarm_minute)
            alarm_active = bool(alarm_enabled)
        else:
            alarm_time = None
            alarm_active = False
    except Exception as e:
        print("NVS load error:", e)
        alarm_time = None
        alarm_active = False

def save_alarm_settings():
    try:
        if alarm_time:
            nvs.set_i32("alarm_hour", alarm_time[0])
            nvs.set_i32("alarm_minute", alarm_time[1])
            nvs.set_i32("alarm_enabled", 1 if alarm_active else 0)
            nvs.commit()
        else:
            nvs.set_i32("alarm_hour", 0)
            nvs.set_i32("alarm_minute", 0)
            nvs.set_i32("alarm_enabled", 0)
            nvs.commit()
    except Exception as e:
        print("NVS save error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("NVS Save Error")
        sleep(1)

def handle_button(pin):
    global button_pressed, last_button_time
    now = ticks_ms()
    if now - last_button_time > DEBOUNCE_MS:
        button_pressed = True
        last_button_time = now

encoder_button.irq(trigger=Pin.IRQ_FALLING, handler=handle_button)

def format_time(hh, mm, ss):
    return f"{hh:02d}:{mm:02d}:{ss:02d}"

def format_date(d, m, y):
    return f"{d:02d}.{m:02d}.{y}"

def add_minutes_to_time(hh, mm, add_minutes):
    total_minutes = hh * 60 + mm + add_minutes
    new_hh = (total_minutes // 60) % 24
    new_mm = total_minutes % 60
    return (new_hh, new_mm)

def update_clock_display():
    global display_time, display_date
    try:
        y, m, d, hh, mm, ss = rtc.read_time()
        new_time = format_time(hh, mm, ss)
        new_date = format_date(d, m, y)
        if new_time != display_time or force_display_refresh:
            display_time = new_time
            lcd.move_to(0, 0)
            lcd.putstr(f"Time: {display_time:>13}")
        if new_date != display_date or force_display_refresh:
            display_date = new_date
            lcd.move_to(0, 1)
            lcd.putstr(f"Date: {display_date:>13}")
    except Exception as e:
        print("RTC read error:", e)

def clear_menu_lines():
    for i in range(2, 4):
        lcd.move_to(0, i)
        lcd.putstr(" " * 20)

def show_main_menu():
    clear_menu_lines()
    items = ["Get NTP Time", "Get RTC Time"]
    for i in range(2):
        lcd.move_to(0, 2 + i)
        prefix = ">" if current_pos == i else " "
        item_text = items[i]
        if i == 0 and alarm_active and alarm_time:
            display_text = f"{prefix}{item_text:<17}AL"
        else:
            display_text = f"{prefix}{item_text:<19}"
        lcd.putstr(display_text)

def show_ntp_menu():
    clear_menu_lines()
    items = ["Sync with NTP", "Save to RTC", "Back"]
    max_display = 2
    for i in range(max_display):
        pos = i + menu_offset
        if pos < len(items):
            lcd.move_to(0, 2 + i)
            prefix = ">" if pos == current_pos else " "
            lcd.putstr(prefix + items[pos][:19])

def show_rtc_menu():
    clear_menu_lines()
    items = ["View RTC Time", "Back"]
    for i in range(2):
        lcd.move_to(0, 2 + i)
        prefix = ">" if current_pos == i else " "
        lcd.putstr(prefix + items[i][:19])

def show_alarm_control():
    clear_menu_lines()
    items = ["Pause/Resume", "Stop", "Snooze"]
    lcd.move_to(0, 2)
    status = "PAUSED" if alarm_paused else "PLAYING"
    lcd.putstr(f"Status: {status:<12}")
    lcd.move_to(0, 3)
    prefix = ">" if current_pos < len(items) else " "
    lcd.putstr(prefix + items[current_pos][:19])

def update_display():
    global force_display_refresh, previous_pos
    if current_state == STATE_MAIN:
        if current_pos != previous_pos or force_display_refresh:
            show_main_menu()
            previous_pos = current_pos
    elif current_state == STATE_NTP_MENU:
        show_ntp_menu()
    elif current_state == STATE_RTC_MENU:
        show_rtc_menu()
    elif current_state == STATE_ALARM_CONTROL:
        lcd.clear()
        lcd.move_to(0, 0)
        lcd.putstr("!!! ALARM !!!      ")
        show_alarm_control()
    if force_display_refresh:
        force_display_refresh = False

def apply_timezone(tm):
    return localtime(mktime(tm[:8]) + TIMEZONE_OFFSET * 3600)

def sync_with_ntp():
    # ... (function is unchanged)
    global ntp_sync_result
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        lcd.move_to(0, 2)
        lcd.putstr("Connecting WiFi..." + " " * 3)
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(10):
            if wlan.isconnected():
                break
            sleep(1)
    if wlan.isconnected():
        try:
            ntptime.settime()
            t = apply_timezone(localtime())
            ntp_sync_result = t[:6]
            lcd.move_to(0, 2)
            lcd.putstr("NTP Sync OK" + " " * 9)
            sleep(1)
        except Exception as e:
            print("NTP Error:", e)
            lcd.move_to(0, 2)
            lcd.putstr("NTP Error" + " " * 11)
            sleep(1)
    else:
        lcd.move_to(0, 2)
        lcd.putstr("WiFi Failed" + " " * 9)
        sleep(1)

def save_to_rtc():
    # ... (function is unchanged)
    if ntp_sync_result:
        rtc.set_time(ntp_sync_result)
        lcd.move_to(0, 2)
        lcd.putstr("Saved to RTC" + " " * 8)
        sleep(1)

def set_rtc_time(y, m, d, hh, mm, ss):
    # ... (function is unchanged)
    try:
        rtc.set_time((y, m, d, hh, mm, ss))
        lcd.move_to(0, 2)
        lcd.putstr(f"RTC Set: {hh:02d}:{mm:02d}:{ss:02d}  ")
        sleep(1)
    except Exception as e:
        print("RTC set error:", e)
        lcd.move_to(0, 2)
        lcd.putstr("RTC Set Error" + " " * 7)
        sleep(1)

def show_rtc_time():
    # ... (function is unchanged)
    try:
        y, m, d, hh, mm, ss = rtc.read_time()
        lcd.move_to(0, 2)
        lcd.putstr(f"{hh:02d}:{mm:02d}:{ss:02d}" + " " * 12)
        lcd.move_to(0, 3)
        lcd.putstr(f"{d:02d}.{m:02d}.{y}" + " " * 10)
        sleep(2)
    except Exception as e:
        print("RTC display error:", e)
        lcd.move_to(0, 2)
        lcd.putstr("RTC Read Error" + " " * 6)
        sleep(2)

def reset_buzzer():
    # ... (function is unchanged)
    try:
        buzzer.pwm.duty_u16(0)
        buzzer.pwm.freq(440)
    except Exception as e:
        print("Buzzer reset error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Buzzer Error")
        sleep(1)

def play_melody():
    # ... (function is unchanged)
    global note_index, alarm_playing, alarm_paused, last_note_time
    if not alarm_playing or alarm_paused:
        reset_buzzer()
        return
    now = ticks_ms()
    if now - last_note_time < MELODY_SPEED:
        return
    melody = mario
    if note_index >= len(melody):
        note_index = 0
    note = melody[note_index]
    try:
        if note <= 0 or note > 20000:
            buzzer.pwm.duty_u16(0)
        else:
            buzzer.pwm.freq(note)
            buzzer.pwm.duty_u16(MELODY_DUTY)
    except ValueError as e:
        print(f"Note error at index {note_index}: {e}")
        buzzer.pwm.duty_u16(0)
        lcd.move_to(0, 3)
        lcd.putstr("Note Error")
        sleep(1)
    note_index += 1
    last_note_time = now

def play_alarm():
    # ... (function is unchanged)
    global alarm_playing, alarm_start_time, note_index, last_note_time
    try:
        reset_buzzer()
        note_index = 0
        last_note_time = ticks_ms()
        alarm_playing = True
        alarm_start_time = ticks_ms()
        print("Alarm started")
    except Exception as e:
        print("Play alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Alarm Error")
        sleep(1)

def stop_alarm():
    global alarm_active, alarm_playing, alarm_paused, snooze_time, current_state, note_index, force_display_refresh, previous_pos
    try:
        reset_buzzer()
        alarm_active = False
        alarm_playing = False
        alarm_paused = False
        snooze_time = None
        note_index = 0
        current_state = STATE_MAIN
        encoder.set(max_val=1)
        save_alarm_settings()
        
        # *** FIX IS HERE: Force a complete, immediate screen redraw ***
        lcd.clear()
        force_display_refresh = True
        update_clock_display()  # Redraws time and date
        show_main_menu()        # Redraws the main menu
        force_display_refresh = False
        previous_pos = current_pos  # Sync previous position to prevent re-redraw
        
        print("Alarm stopped")
    except Exception as e:
        print("Stop alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Stop Error")
        sleep(1)

def pause_alarm():
    # ... (function is unchanged)
    global alarm_playing, alarm_paused
    try:
        if alarm_playing:
            alarm_paused = True
            reset_buzzer()
            update_display()
            print("Alarm paused")
    except Exception as e:
        print("Pause alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Pause Error")
        sleep(1)

def resume_alarm():
    # ... (function is unchanged)
    global alarm_playing, alarm_paused
    try:
        if alarm_paused:
            alarm_paused = False
            last_note_time = ticks_ms()
            update_display()
            print("Alarm resumed")
    except Exception as e:
        print("Resume alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Resume Error")
        sleep(1)

def snooze_alarm():
    global alarm_active, alarm_playing, alarm_paused, snooze_time, current_state, note_index, force_display_refresh, previous_pos
    try:
        y, m, d, hh, mm, ss = rtc.read_time()
        snooze_hh, snooze_mm = add_minutes_to_time(hh, mm, SNOOZE_MINUTES)
        snooze_time = (snooze_hh, snooze_mm)
        reset_buzzer()
        alarm_playing = False
        alarm_paused = False
        note_index = 0
        current_state = STATE_MAIN
        encoder.set(max_val=1)
        
        # Show temporary message
        lcd.move_to(0, 3)
        lcd.putstr(f"Snoozed to {snooze_hh:02d}:{snooze_mm:02d}" + " " * 4)
        sleep(1)

        # *** FIX IS HERE: Force a complete, immediate screen redraw ***
        lcd.clear()
        force_display_refresh = True
        update_clock_display()
        show_main_menu()
        force_display_refresh = False
        previous_pos = current_pos # Sync previous position
        
        print(f"Alarm snoozed to {snooze_hh:02d}:{snooze_mm:02d}")
    except Exception as e:
        print("Snooze alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Snooze Error")
        sleep(1)

def get_alarm_status():
    # ... (function is unchanged)
    status = "STOPPED"
    if alarm_active and alarm_time:
        if alarm_playing:
            status = "PLAYING" if not alarm_paused else "PAUSED"
        elif snooze_time:
            status = f"SNOOZED:{snooze_time[0]:02d}:{snooze_time[1]:02d}"
        else:
            status = f"SET:{alarm_time[0]:02d}:{alarm_time[1]:02d}"
    print(f"ALARM_STATUS:{status}")

def handle_uart_commands():
    # ... (function is unchanged)
    global alarm_time, alarm_active
    try:
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            cmd = sys.stdin.readline().strip()
            if cmd.startswith("ALARM_SET:"):
                parts = cmd[10:].split(":")
                if len(parts) == 2:
                    hh = int(parts[0])
                    mm = int(parts[1])
                    if 0 <= hh <= 23 and 0 <= mm <= 59:
                        alarm_time = (hh, mm)
                        alarm_active = True
                        save_alarm_settings()
                        lcd.move_to(0, 3)
                        lcd.putstr(f"Alarm set: {hh:02d}:{mm:02d}" + " " * 6)
                        sleep(1)
                        force_display_refresh = True # Force main menu to show "AL"
                    else:
                        lcd.move_to(0, 3)
                        lcd.putstr("Invalid Time" + " " * 8)
                        sleep(1)
            elif cmd == "ALARM_CLEAR":
                stop_alarm()
                alarm_time = None
                save_alarm_settings()
                lcd.move_to(0, 3)
                lcd.putstr("Alarm cleared" + " " * 7)
                sleep(1)
                force_display_refresh = True
            elif cmd == "ALARM_PAUSE":
                pause_alarm()
            elif cmd == "ALARM_RESUME":
                resume_alarm()
            elif cmd == "ALARM_SNOOZE":
                snooze_alarm()
            elif cmd == "ALARM_STATUS":
                get_alarm_status()
            elif cmd.startswith("NTP_SET:"):
                parts = cmd[8:].split(":")
                if len(parts) == 6:
                    y, m, d, hh, mm, ss = map(int, parts)
                    set_rtc_time(y, m, d, hh, mm, ss)
    except Exception as e:
        print("UART command error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("UART Error" + " " * 10)
        sleep(1)


def check_alarm():
    # ... (function is unchanged)
    global alarm_active, alarm_playing, snooze_time, current_state, last_alarm_check, alarm_start_time
    try:
        now = ticks_ms()
        if now - last_alarm_check < 1000:
            return
        last_alarm_check = now
        if not alarm_active or not alarm_time:
            return
        y, m, d, hh, mm, ss = rtc.read_time()
        current_time = (hh, mm)
        if not alarm_playing and not alarm_paused:
            if (snooze_time and current_time == snooze_time) or (not snooze_time and current_time == alarm_time):
                trigger_alarm()
        if alarm_playing and not alarm_paused and (now - alarm_start_time > ALARM_DURATION * 1000):
            stop_alarm()
    except Exception as e:
        print("Check alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Check Alarm Error")
        sleep(1)

def trigger_alarm():
    # ... (function is unchanged)
    global current_state, current_pos, menu_offset
    try:
        current_state = STATE_ALARM_CONTROL
        current_pos = 0
        menu_offset = 0
        encoder.set(max_val=2)
        play_alarm()
        update_display()
        print("Alarm triggered")
    except Exception as e:
        print("Trigger alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Trigger Error")
        sleep(1)

# Main Loop
try:
    load_alarm_settings()
    lcd.clear()
    force_display_refresh = True
    update_display() # Initial draw
    last_encoder_val = encoder.value()
    reset_buzzer()
    while True:
        # Only update clock continuously if not in alarm state
        if current_state != STATE_ALARM_CONTROL:
            update_clock_display()
            
        handle_uart_commands()
        check_alarm()
        play_melody()

        new_val = encoder.value()
        if new_val != last_encoder_val:
            now = ticks_ms()
            if now - last_encoder_time > ENCODER_DEBOUNCE_MS:
                if current_state == STATE_NTP_MENU:
                    items = ["Sync with NTP", "Save to RTC", "Back"]
                    max_display = 2
                    current_pos = new_val
                    if current_pos >= menu_offset + max_display:
                        menu_offset = current_pos - max_display + 1
                    elif current_pos < menu_offset:
                        menu_offset = current_pos
                    menu_offset = max(0, min(menu_offset, len(items) - max_display))
                else:
                    current_pos = new_val
                update_display()
                sleep(0.01)
                last_encoder_val = new_val
                last_encoder_time = now

        if button_pressed:
            button_pressed = False
            if current_state == STATE_MAIN:
                if current_pos == 0:
                    current_state = STATE_NTP_MENU
                    encoder.set(max_val=2)
                    current_pos = 0
                    menu_offset = 0
                elif current_pos == 1:
                    current_state = STATE_RTC_MENU
                    encoder.set(max_val=1)
                    current_pos = 0
                    menu_offset = 0
            elif current_state == STATE_NTP_MENU:
                if current_pos == 0:
                    sync_with_ntp()
                elif current_pos == 1:
                    save_to_rtc()
                elif current_pos == 2:
                    current_state = STATE_MAIN
                    encoder.set(max_val=1)
                    current_pos = 0
                    menu_offset = 0
                    force_display_refresh = True
            elif current_state == STATE_RTC_MENU:
                if current_pos == 0:
                    show_rtc_time()
                elif current_pos == 1:
                    current_state = STATE_MAIN
                    encoder.set(max_val=1)
                    current_pos = 0
                    menu_offset = 0
                    force_display_refresh = True
            elif current_state == STATE_ALARM_CONTROL:
                if current_pos == 0:
                    if alarm_paused:
                        resume_alarm()
                    else:
                        pause_alarm()
                elif current_pos == 1:
                    stop_alarm()
                    current_pos = 0
                    menu_offset = 0
                elif current_pos == 2:
                    snooze_alarm()
                    current_pos = 0
                    menu_offset = 0
            
            # General update after any button press
            if current_state != STATE_ALARM_CONTROL:
                 update_display()

        sleep(0.05)
except Exception as e:
    print("Main loop error:", e)
    lcd.move_to(0, 0)
    lcd.putstr("Main Loop Error")
    reset_buzzer()
    sleep(2)




