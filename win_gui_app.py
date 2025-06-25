import tkinter as tk
from tkinter import ttk, filedialog
import serial
import serial.tools.list_ports
import ntplib
from datetime import datetime, timezone, timedelta
import threading
import queue
import time

class AlarmControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ESP32 Alarm Control")
        self.root.geometry("360x570")
        self.root.resizable(False, False)
        
        self.serial = None
        self.serial_queue = queue.Queue()
        self.running = True
        
        self.setup_ui()
        self.refresh_ports()
        self.start_serial_reader()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def setup_ui(self):
        style = ttk.Style()
        style.configure("TButton", padding=5)
        style.configure("TLabel", padding=3)
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(1, weight=1)
        
        # Port selection
        ttk.Label(main_frame, text="ESP32 Port:").grid(row=0, column=0, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combobox = ttk.Combobox(main_frame, textvariable=self.port_var, state="readonly")
        self.port_combobox.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(main_frame, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=5)
        
        ttk.Separator(main_frame, orient="horizontal").grid(row=1, column=0, columnspan=3, sticky="ew", pady=10)
        
        # Alarm setup
        ttk.Label(main_frame, text="SET ALARM", font=("Arial", 10, "bold")).grid(row=2, column=0, columnspan=3, pady=5)
        
        time_frame = ttk.Frame(main_frame)
        time_frame.grid(row=3, column=0, columnspan=3, sticky="ew")
        
        ttk.Label(time_frame, text="Hours (0-23):").grid(row=0, column=0, padx=5, sticky="w")
        self.hour_spinbox = ttk.Spinbox(time_frame, from_=0, to=23, width=5, format="%02.0f")
        self.hour_spinbox.grid(row=0, column=1, padx=5)
        self.hour_spinbox.set("00")
        
        ttk.Label(time_frame, text="Minutes (0-59):").grid(row=0, column=2, padx=5, sticky="w")
        self.minute_spinbox = ttk.Spinbox(time_frame, from_=0, to=59, width=5, format="%02.0f")
        self.minute_spinbox.grid(row=0, column=3, padx=5)
        self.minute_spinbox.set("00")
        
        ttk.Button(main_frame, text="Set Alarm", command=self.set_alarm, style="Accent.TButton").grid(row=4, column=0, columnspan=3, sticky="ew", pady=5)
        ttk.Button(main_frame, text="Clear Alarm", command=self.clear_alarm).grid(row=5, column=0, columnspan=3, sticky="ew", pady=5)
        
        ttk.Separator(main_frame, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=10)
        
        # Additional controls
        ttk.Label(main_frame, text="CONTROLS", font=("Arial", 10, "bold")).grid(row=7, column=0, columnspan=3, pady=5)
        
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=8, column=0, columnspan=3, sticky="ew")
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        
        ttk.Button(button_frame, text="Alarm Status", command=self.get_alarm_status).grid(row=0, column=0, padx=2, sticky="ew")
        ttk.Button(button_frame, text="NTP Request", command=self.ntp_request).grid(row=0, column=1, padx=2, sticky="ew")
        
        ttk.Separator(main_frame, orient="horizontal").grid(row=9, column=0, columnspan=3, sticky="ew", pady=10)
        
        # Status displays
        ttk.Label(main_frame, text="Alarm Status:").grid(row=10, column=0, sticky="w")
        self.alarm_status_label = ttk.Label(main_frame, text="Unknown")
        self.alarm_status_label.grid(row=10, column=1, columnspan=2, sticky="w")
        
        ttk.Label(main_frame, text="Action Log:").grid(row=11, column=0, sticky="nw")
        self.log_text = tk.Text(main_frame, height=8, width=40, wrap=tk.WORD, state="disabled")
        self.log_text.grid(row=12, column=0, columnspan=3, sticky="ew", pady=5)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=12, column=3, sticky="ns")
        self.log_text["yscrollcommand"] = scrollbar.set
        
        # Log control buttons
        log_button_frame = ttk.Frame(main_frame)
        log_button_frame.grid(row=13, column=0, columnspan=3, sticky="ew", pady=5)
        log_button_frame.columnconfigure(0, weight=1)
        log_button_frame.columnconfigure(1, weight=1)
        
        ttk.Button(log_button_frame, text="Clear Log", command=self.clear_log).grid(row=0, column=0, padx=2, sticky="ew")
        ttk.Button(log_button_frame, text="Save Log", command=self.save_log).grid(row=0, column=1, padx=2, sticky="ew")
        
        # Configure style for Set Alarm button
        style.configure("Accent.TButton", background="lightgreen")
    
    def log_message(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')}: {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
    
    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")
        self.log_message("Log cleared")
    
    def save_log(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Action Log"
        )
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    log_content = self.log_text.get("1.0", tk.END).strip()
                    f.write(log_content)
                self.log_message(f"Log saved to {file_path}")
            except Exception as e:
                self.log_message(f"Save error: {str(e)}")
    
    def send_to_esp32(self, command):
        port = self.port_var.get()
        if not port:
            self.log_message("No ESP32 port selected")
            self.alarm_status_label.config(text="Error: No port")
            return False
        try:
            if not self.serial or self.serial.port != port:
                if self.serial:
                    self.serial.close()
                self.serial = serial.Serial(port, 115200, timeout=0.1)
            self.serial.write((command + '\n').encode('utf-8'))
            self.serial.flush()
            self.log_message(f"Sent: {command}")
            return True
        except Exception as e:
            self.log_message(f"Serial error: {str(e)}")
            self.alarm_status_label.config(text="Error: Serial")
            if self.serial:
                self.serial.close()
                self.serial = None
            return False
    
    def set_alarm(self):
        hh = int(self.hour_spinbox.get())
        mm = int(self.minute_spinbox.get())
        command = f"ALARM_SET:{hh:02d}:{mm:02d}"
        if self.send_to_esp32(command):
            self.alarm_status_label.config(text=f"Set at {hh:02d}:{mm:02d}")
    
    def clear_alarm(self):
        if self.send_to_esp32("ALARM_CLEAR"):
            self.alarm_status_label.config(text="Cleared")
    
    def get_alarm_status(self):
        self.send_to_esp32("ALARM_STATUS")
    
    def ntp_request(self):
        try:
            ntp_client = ntplib.NTPClient()
            response = ntp_client.request('pool.ntp.org')
            utc_time = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
            local_time = utc_time + timedelta(hours=3)  # UTC+3 for Odessa
            y, m, d, hh, mm, ss = local_time.year, local_time.month, local_time.day, local_time.hour, local_time.minute, local_time.second
            if 2000 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31 and 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
                command = f"NTP_SET:{y}:{m}:{d}:{hh}:{mm}:{ss}"
                self.log_message(f"Preparing: {command}")
                if self.send_to_esp32(command):
                    self.log_message(f"NTP time set: {local_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    self.alarm_status_label.config(text="RTC Updated")
            else:
                self.log_message("Invalid NTP time values")
                self.alarm_status_label.config(text="NTP Error")
        except Exception as e:
            self.log_message(f"NTP error: {str(e)}")
            self.alarm_status_label.config(text="NTP Error")
    
    def start_serial_reader(self):
        def reader():
            while self.running:
                if self.serial and self.serial.is_open:
                    try:
                        if self.serial.in_waiting:
                            line = self.serial.readline().decode('utf-8').strip()
                            if line.startswith("ALARM_STATUS:"):
                                status = line[13:]
                                if status.startswith("SET:"):
                                    hh, mm = status[4:].split(":")
                                    self.root.after(0, lambda: self.alarm_status_label.config(text=f"Set at {hh}:{mm}"))
                                elif status.startswith("SNOOZED:"):
                                    hh, mm = status[8:].split(":")
                                    self.root.after(0, lambda: self.alarm_status_label.config(text=f"Snoozed to {hh}:{mm}"))
                                else:
                                    self.root.after(0, lambda: self.alarm_status_label.config(text=status.capitalize()))
                                self.root.after(0, lambda: self.log_message(f"Status: {status}"))
                            elif line.startswith("RTC set error"):
                                self.root.after(0, lambda: self.alarm_status_label.config(text="RTC Set Error"))
                                self.root.after(0, lambda: self.log_message(f"ESP32 error: {line}"))
                            else:
                                self.root.after(0, lambda: self.log_message(f"ESP32: {line}"))
                    except Exception as e:
                        self.root.after(0, lambda: self.log_message(f"Read error: {str(e)}"))
                time.sleep(0.01)
        
        threading.Thread(target=reader, daemon=True).start()
    
    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combobox['values'] = ports
        if ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("")
    
    def on_closing(self):
        self.running = False
        if self.serial:
            self.serial.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = AlarmControlApp(root)
    root.mainloop()