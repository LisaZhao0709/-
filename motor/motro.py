"""
MicroPython driver for Motor-4Ch v1.7 (PCA9685 based) on ESP32-D.
Controls four TT motors with independent speed and direction via I2C.
"""

import time
try:
    import machine
except ImportError:
    # Mock machine module for host testing
    from types import SimpleNamespace
    machine = SimpleNamespace(
        I2C=lambda *a, **k: None,
        Pin=lambda *a, **k: None
    )

class PCA9685:
    """Low-level PCA9685 PWM controller driver."""
    _MODE1 = 0x00
    _PRESCALE = 0xFE
    _LED0_ON_L = 0x06
    _RESTART = 0x80
    _SLEEP = 0x10
    _AI = 0x20  # Auto-increment

    def __init__(self, i2c, address=0x40, freq=50):
        self.i2c = i2c
        self.address = address
        self._init_pca(freq)

    def _init_pca(self, freq):
        self.write_reg(self._MODE1, bytes([0x00]))
        self.set_freq(freq)

    def write_reg(self, reg, data):
        self.i2c.writeto_mem(self.address, reg, data)

    def read_reg(self, reg, length=1):
        return self.i2c.readfrom_mem(self.address, reg, length)

    def set_freq(self, freq):
        prescale_val = int(25000000.0 / (4096 * freq) - 0.5)
        old_mode = self.read_reg(self._MODE1)[0]
        new_mode = (old_mode & 0x7F) | self._SLEEP
        self.write_reg(self._MODE1, bytes([new_mode]))
        self.write_reg(self._PRESCALE, bytes([prescale_val]))
        self.write_reg(self._MODE1, bytes([old_mode]))
        time.sleep_ms(5)
        self.write_reg(self._MODE1, bytes([old_mode | self._RESTART | self._AI]))

    def set_pwm(self, channel, on, off):
        reg = self._LED0_ON_L + 4 * channel
        data = bytes([on & 0xFF, (on >> 8) & 0xFF, off & 0xFF, (off >> 8) & 0xFF])
        self.write_reg(reg, data)

class Motor4Ch:
    """
    High-level controller for Motor-4Ch v1.7.
    Maps 4 motors to PCA9685 channels 0-7.
    Motor ID: 0, 1, 2, 3
    Speed: -100 to 100
    """
    def __init__(self, i2c, address=0x40):
        self.pca = PCA9685(i2c, address)
        # Channels: (Forward_PWM, Backward_PWM)
        self.motor_map = {
            0: (0, 1),
            1: (2, 3),
            2: (4, 5),
            3: (6, 7)
        }

    def set_motor(self, motor_id, speed):
        """
        motor_id: 0-3
        speed: -100 to 100
        """
        if motor_id not in self.motor_map:
            raise ValueError(f"Invalid motor_id: {motor_id}")
        
        speed = max(-100, min(100, speed))
        duty = int(abs(speed) * 40.95) # 0-4095 range
        
        fwd_ch, bwd_ch = self.motor_map[motor_id]
        
        if speed > 0:
            self.pca.set_pwm(fwd_ch, 0, duty)
            self.pca.set_pwm(bwd_ch, 0, 0)
        elif speed < 0:
            self.pca.set_pwm(fwd_ch, 0, 0)
            self.pca.set_pwm(bwd_ch, 0, duty)
        else:
            self.pca.set_pwm(fwd_ch, 0, 0)
            self.pca.set_pwm(bwd_ch, 0, 0)
        
        return {"motor": motor_id, "speed": speed, "duty": duty}

    def stop_all(self):
        for i in range(4):
            self.set_motor(i, 0)

