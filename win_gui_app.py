import tkinter as tk
import serial
import serial.tools.list_ports

class AlarmControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Управление Будильником ESP32")
        self.root.geometry("450x400")
        
        self.setup_ui()
        self.refresh_ports()
    
    def setup_ui(self):
        # Port selection
        tk.Label(self.root, text="Порт ESP32:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.port_var = tk.StringVar()
        self.port_menu = tk.OptionMenu(self.root, self.port_var, "")
        self.port_menu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        tk.Button(self.root, text="Обновить", command=self.refresh_ports).grid(row=0, column=2, padx=5, pady=5)
        
        # Separator
        tk.Label(self.root, text="", height=1).grid(row=1, column=0, columnspan=3)
        
        # Alarm setup
        tk.Label(self.root, text="УСТАНОВКА БУДИЛЬНИКА", font=("Arial", 10, "bold")).grid(row=2, column=0, columnspan=3, pady=5)
        
        tk.Label(self.root, text="Часы (0-23):").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.hour_entry = tk.Entry(self.root, width=5)
        self.hour_entry.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        
        tk.Label(self.root, text="Минуты (0-59):").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.minute_entry = tk.Entry(self.root, width=5)
        self.minute_entry.grid(row=4, column=1, padx=5, pady=5, sticky="w")
        
        # Alarm buttons
        tk.Button(self.root, text="Установить будильник", command=self.set_alarm, bg="lightgreen").grid(row=5, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        tk.Button(self.root, text="Удалить будильник", command=self.clear_alarm, bg="lightcoral").grid(row=6, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        
        # Separator
        tk.Label(self.root, text="", height=1).grid(row=7, column=0, columnspan=3)
        
        # Alarm control
        tk.Label(self.root, text="УПРАВЛЕНИЕ БУДИЛЬНИКОМ", font=("Arial", 10, "bold")).grid(row=8, column=0, columnspan=3, pady=5)
        
        # First row of buttons
        button_frame1 = tk.Frame(self.root)
        button_frame1.grid(row=9, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        button_frame1.columnconfigure(0, weight=1)
        button_frame1.columnconfigure(1, weight=1)
        
        tk.Button(button_frame1, text="Пауза", command=self.pause_alarm, bg="lightyellow").grid(row=0, column=0, padx=2, sticky="ew")
        tk.Button(button_frame1, text="Продолжить", command=self.resume_alarm, bg="lightblue").grid(row=0, column=1, padx=2, sticky="ew")
        
        # Second row of buttons
        button_frame2 = tk.Frame(self.root)
        button_frame2.grid(row=10, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        button_frame2.columnconfigure(0, weight=1)
        button_frame2.columnconfigure(1, weight=1)
        
        tk.Button(button_frame2, text="Стоп", command=self.stop_alarm, bg="lightcoral").grid(row=0, column=0, padx=2, sticky="ew")
        tk.Button(button_frame2, text="Отложить (+5 мин)", command=self.snooze_alarm, bg="lightgray").grid(row=0, column=1, padx=2, sticky="ew")
        
        # Status button
        tk.Button(self.root, text="Узнать статус будильника", command=self.get_alarm_status, bg="lightsteelblue").grid(row=11, column=0, columnspan=3, padx=10, pady=10, sticky="ew")
        
        # Separator
        tk.Label(self.root, text="", height=1).grid(row=12, column=0, columnspan=3)
        
        # Instructions
        instructions = tk.Text(self.root, height=4, width=50, wrap=tk.WORD)
        instructions.grid(row=13, column=0, columnspan=3, padx=10, pady=5, sticky="ew")
        instructions.insert(tk.END, "ИНСТРУКЦИЯ:\n• Пауза - временно останавливает звук будильника\n• Продолжить - возобновляет звук после паузы\n• Стоп - полностью останавливает будильник\n• Отложить - откладывает будильник на 5 минут")
        instructions.config(state=tk.DISABLED)
        
        # Status label
        self.status_label = tk.Label(self.root, text="", fg="black")
        self.status_label.grid(row=14, column=0, columnspan=3, padx=10, pady=5)
        
        # Configure columns
        self.root.columnconfigure(1, weight=1)
    
    def send_to_esp32(self, command):
        port = self.port_var.get()
        if port:
            try:
                ser = serial.Serial(port, 115200, timeout=1)
                ser.write((command + '\n').encode('utf-8'))
                ser.close()
                self.status_label.config(text=f"Команда '{command}' отправлена", fg="green")
            except Exception as e:
                self.status_label.config(text=f"Ошибка: {str(e)}", fg="red")
        else:
            self.status_label.config(text="Порт ESP32 не выбран", fg="red")
    
    def set_alarm(self):
        hh = self.hour_entry.get()
        mm = self.minute_entry.get()
        if hh.isdigit() and mm.isdigit():
            hh = int(hh)
            mm = int(mm)
            if 0 <= hh < 24 and 0 <= mm < 60:
                command = f"ALARM_SET:{hh:02d}:{mm:02d}"
                self.send_to_esp32(command)
            else:
                self.status_label.config(text="Время вне диапазона", fg="red")
        else:
            self.status_label.config(text="Введите корректные числа", fg="red")
    
    def clear_alarm(self):
        self.send_to_esp32("ALARM_CLEAR")
    
    def pause_alarm(self):
        self.send_to_esp32("ALARM_PAUSE")
    
    def stop_alarm(self):
        self.send_to_esp32("ALARM_STOP")
    
    def snooze_alarm(self):
        self.send_to_esp32("ALARM_SNOOZE")
    
    def resume_alarm(self):
        self.send_to_esp32("ALARM_RESUME")
    
    def get_alarm_status(self):
        self.send_to_esp32("ALARM_STATUS")
    
    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_menu['menu'].delete(0, 'end')
        for p in ports:
            self.port_menu['menu'].add_command(label=p, command=tk._setit(self.port_var, p))
        if ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("")

if __name__ == "__main__":
    root = tk.Tk()
    app = AlarmControlApp(root)
    root.mainloop()