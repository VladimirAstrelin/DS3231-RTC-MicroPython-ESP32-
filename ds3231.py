# ds3231.py
class DS3231:
    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr

    def _bcd2dec(self, bcd): return (bcd >> 4) * 10 + (bcd & 0x0F)
    def _dec2bcd(self, dec): return ((dec // 10) << 4) + (dec % 10)

    def read_time(self):
        data = self.i2c.readfrom_mem(self.addr, 0x00, 7)
        return (
            self._bcd2dec(data[6]) + 2000,
            self._bcd2dec(data[5]),
            self._bcd2dec(data[4]),
            self._bcd2dec(data[2]),
            self._bcd2dec(data[1]),
            self._bcd2dec(data[0])
        )

    def set_time(self, dt):
        year, month, day, hour, minute, second = dt
        self.i2c.writeto_mem(self.addr, 0x00, bytes([
            self._dec2bcd(second),
            self._dec2bcd(minute),
            self._dec2bcd(hour),
            0,
            self._dec2bcd(day),
            self._dec2bcd(month),
            self._dec2bcd(year - 2000)
        ]))

