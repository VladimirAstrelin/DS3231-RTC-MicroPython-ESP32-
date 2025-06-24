# WORKING VERSION 25-06-2025
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

# Initialization
try:
    i2c = SoftI2C(sda=Pin(21), scl=Pin(22))
    lcd = I2cLcd(i2c, I2C_ADDR, I2C_NUM_ROWS, I2C_NUM_COLS)
    lcd.backlight_on()
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
note_index = 0  # Track current note in melody
last_note_time = 0  # Track time of last note played

# Encoder Button Handler
def handle_button(pin):
    global button_pressed, last_button_time
    now = ticks_ms()
    if now - last_button_time > DEBOUNCE_MS:
        button_pressed = True
        last_button_time = now

encoder_button.irq(trigger=Pin.IRQ_FALLING, handler=handle_button)

# Helper Functions
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
    for i in range(2, 4):
        lcd.move_to(0, i)
        lcd.putstr(" " * 20)

def show_main_menu():
    clear_menu_lines()
    items = ["Get NTP Time", "Get RTC Time"]
    for i in range(2):
        lcd.move_to(0, 2 + i)
        prefix = ">" if current_pos == i else " "
        lcd.putstr(prefix + items[i][:19])

def show_ntp_menu():
    clear_menu_lines()
    items = ["Sync with NTP", "Save to RTC", "Back"]
    for i in range(2):
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

def show_alarm_control_menu():
    clear_menu_lines()
    items = ["Pause/Resume", "Stop", "Snooze"]
    lcd.move_to(0, 2)
    status = "PAUSED" if alarm_paused else "PLAYING"
    lcd.putstr(f"Status: {status:<12}")
    lcd.move_to(0, 3)
    prefix = ">" if current_pos < len(items) else " "
    lcd.putstr(prefix + items[current_pos][:19])

def update_display():
    update_clock_display()
    if current_state == STATE_MAIN:
        show_main_menu()
    elif current_state == STATE_NTP_MENU:
        show_ntp_menu()
    elif current_state == STATE_RTC_MENU:
        show_rtc_menu()
    elif current_state == STATE_ALARM_CONTROL:
        lcd.move_to(0, 0)
        lcd.putstr("!!! ALARM !!!      ")
        show_alarm_control_menu()

def apply_timezone(tm):
    return localtime(mktime(tm[:8]) + TIMEZONE_OFFSET * 3600)

def sync_with_ntp():
    global ntp_sync_result
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        lcd.move_to(0, 2)
        lcd.putstr("Connecting WiFi...")
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
            lcd.putstr("NTP Sync OK")
            sleep(1)
        except Exception as e:
            print("NTP Error:", e)
            lcd.move_to(0, 2)
            lcd.putstr("NTP Error")
            sleep(1)

def save_to_rtc():
    if ntp_sync_result:
        rtc.set_time(ntp_sync_result)
        lcd.move_to(0, 2)
        lcd.putstr("Saved to RTC")
        sleep(1)

def show_rtc_time():
    try:
        y, m, d, hh, mm, ss = rtc.read_time()
        lcd.move_to(0, 2)
        lcd.putstr(f"{hh:02d}:{mm:02d}:{ss:02d}")
        lcd.move_to(0, 3)
        lcd.putstr(f"{d:02d}.{m:02d}.{y}")
        sleep(2)
    except Exception as e:
        print("RTC display error:", e)

def reset_buzzer():
    try:
        buzzer.pwm.duty_u16(0)
        buzzer.pwm.freq(440)  # Set a safe default frequency
    except Exception as e:
        print("Buzzer reset error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Buzzer Error")
        sleep(1)

def play_melody():
    global note_index, alarm_playing, alarm_paused, last_note_time
    if not alarm_playing or alarm_paused:
        reset_buzzer()
        return
    now = ticks_ms()
    if now - last_note_time < MELODY_SPEED:
        return
    melody = mario
    if note_index >= len(melody):
        note_index = 0  # Loop melody
    note = melody[note_index]
    try:
        if note <= 0 or note > 20000:  # Validate note frequency
            buzzer.pwm.duty_u16(0)
        else:
            buzzer.pwm.freq(note)
            buzzer.pwm.duty_u16(MELODY_DUTY)
        print(f"Playing note {note_index}: {note} Hz")  # Debug output
    except ValueError as e:
        print(f"Note error at index {note_index}: {e}")
        buzzer.pwm.duty_u16(0)
        lcd.move_to(0, 3)
        lcd.putstr("Note Error")
        sleep(1)
    note_index += 1
    last_note_time = now

def play_alarm():
    global alarm_playing, alarm_start_time, note_index, last_note_time
    try:
        reset_buzzer()
        note_index = 0
        last_note_time = ticks_ms()
        alarm_playing = True
        alarm_start_time = ticks_ms()
        print("Alarm started")  # Debug output
    except Exception as e:
        print("Play alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Alarm Error")
        sleep(1)

def stop_alarm():
    global alarm_active, alarm_playing, alarm_paused, snooze_time, current_state, note_index
    try:
        reset_buzzer()
        alarm_active = False
        alarm_playing = False
        alarm_paused = False
        snooze_time = None
        note_index = 0
        current_state = STATE_MAIN
        encoder.set(max_val=1)
        current_pos = 0
        menu_offset = 0
        update_display()
        print("Alarm stopped")  # Debug output
    except Exception as e:
        print("Stop alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Stop Error")
        sleep(1)

def pause_alarm():
    global alarm_playing, alarm_paused
    try:
        if alarm_playing:
            alarm_paused = True
            reset_buzzer()
            update_display()
            print("Alarm paused")  # Debug output
    except Exception as e:
        print("Pause alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Pause Error")
        sleep(1)

def resume_alarm():
    global alarm_playing, alarm_paused
    try:
        if alarm_paused:
            alarm_paused = False
            last_note_time = ticks_ms()  # Reset note timing
            update_display()
            print("Alarm resumed")  # Debug output
    except Exception as e:
        print("Resume alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Resume Error")
        sleep(1)

def snooze_alarm():
    global alarm_active, alarm_playing, alarm_paused, snooze_time, current_state, note_index
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
        current_pos = 0
        menu_offset = 0
        lcd.move_to(0, 3)
        lcd.putstr(f"Snoozed to {snooze_hh:02d}:{snooze_mm:02d}")
        sleep(1)
        update_display()
        print(f"Alarm snoozed to {snooze_hh:02d}:{snooze_mm:02d}")  # Debug output
    except Exception as e:
        print("Snooze alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Snooze Error")
        sleep(1)

def handle_uart_commands():
    global alarm_time, alarm_active
    try:
        if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
            cmd = sys.stdin.readline().strip()
            if cmd.startswith("ALARM_SET:"):
                parts = cmd[10:].split(":")
                if len(parts) == 2:
                    hh = int(parts[0])
                    mm = int(parts[1])
                    alarm_time = (hh, mm)
                    alarm_active = True
                    lcd.move_to(0, 3)
                    lcd.putstr(f"Alarm set: {hh:02d}:{mm:02d}")
                    print(f"Alarm set: {hh:02d}:{mm:02d}")  # Debug output
            elif cmd == "ALARM_CLEAR":
                stop_alarm()
                alarm_time = None
                lcd.move_to(0, 3)
                lcd.putstr("Alarm cleared      ")
                print("Alarm cleared")  # Debug output
            elif cmd == "ALARM_PAUSE":
                pause_alarm()
            elif cmd == "ALARM_RESUME":
                resume_alarm()
            elif cmd == "ALARM_SNOOZE":
                snooze_alarm()
    except Exception as e:
        print("UART command error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("UART Error")
        sleep(1)

def check_alarm():
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
    global current_state, current_pos, menu_offset
    try:
        current_state = STATE_ALARM_CONTROL
        current_pos = 0
        menu_offset = 0
        encoder.set(max_val=2)
        play_alarm()
        update_display()
        print("Alarm triggered")  # Debug output
    except Exception as e:
        print("Trigger alarm error:", e)
        lcd.move_to(0, 3)
        lcd.putstr("Trigger Error")
        sleep(1)

# Main Loop
try:
    update_display()
    last_encoder_val = encoder.value()
    reset_buzzer()  # Ensure buzzer is silent at startup
    while True:
        update_clock_display()
        handle_uart_commands()
        check_alarm()
        play_melody()  # Handle melody playback in main loop
        new_val = encoder.value()
        if new_val != last_encoder_val:
            now = ticks_ms()
            if now - last_encoder_time > ENCODER_DEBOUNCE_MS:
                current_pos = new_val
                update_display()
                print(f"Encoder value changed to: {new_val}")  # Debug output
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
            elif current_state == STATE_RTC_MENU:
                if current_pos == 0:
                    show_rtc_time()
                elif current_pos == 1:
                    current_state = STATE_MAIN
                    encoder.set(max_val=1)
                    current_pos = 0
                    menu_offset = 0
            elif current_state == STATE_ALARM_CONTROL:
                if current_pos == 0:
                    if alarm_paused:
                        resume_alarm()
                    else:
                        pause_alarm()
                elif current_pos == 1:
                    stop_alarm()
                elif current_pos == 2:
                    snooze_alarm()
            update_display()
        sleep(0.05)
except Exception as e:
    print("Main loop error:", e)
    lcd.move_to(0, 0)
    lcd.putstr("Main Loop Error")
    reset_buzzer()
    sleep(2)