# Car 系统实战操作手册

本文档用于统一说明本项目（`distance`、`line`、`motor`）的硬件连接、核心子函数和调用方式。

## 1. 引脚连接说明

### 1.1 HC-SR04 超声波（`distance/hc04.py`）

| 模块引脚 | ESP32 GPIO | 说明 |
| :-- | :-- | :-- |
| TRIG | GPIO 5 | 触发引脚（输出） |
| ECHO | GPIO 18 | 回波引脚（输入） |
| VCC | 5V | 电源 |
| GND | GND | 地 |

代码中固定定义：
- `TRIG_PIN = 5`
- `ECHO_PIN = 18`

### 1.2 8路灰度传感器（CD4051，多路复用，`line/line.py`）

| 传感器引脚 | ESP32 GPIO（默认） | 说明 |
| :-- | :-- | :-- |
| AD0 | GPIO 25 | 地址线低位 |
| AD1 | GPIO 26 | 地址线中位 |
| AD2 | GPIO 27 | 地址线高位 |
| OUT | GPIO 34 | 传感器输出输入口 |
| 5V | 5V / VIN | 电源 |
| GND | GND | 地 |

默认构造参数：
- `ad0_pin=25`
- `ad1_pin=26`
- `ad2_pin=27`
- `out_pin=34`

### 1.3 电机驱动板 Motor-4Ch v1.7（PCA9685，`motor/motro.py`）

I2C 默认使用：
- `SDA = GPIO 21`
- `SCL = GPIO 22`
- `I2C 频率 = 400000`
- `PCA9685 地址 = 0x40`

电机与 PWM 通道映射：
- 电机 0 -> `(0, 1)`
- 电机 1 -> `(2, 3)`
- 电机 2 -> `(4, 5)`
- 电机 3 -> `(6, 7)`

---

## 2. 有哪些函数（够用版）

### 2.1 超声波
- `measure_distance_cm()`：返回测距值（cm），超时返回 `-1.0`。

### 2.2 灰度
- `GrayscaleSensor(...)`：初始化灰度模块。
- `read_channel(channel)`：读取单路，`channel` 范围 `0~7`。
- `read_all()`：返回 8 路数组，如 `[0,1,0,0,1,0,0,1]`。

### 2.3 电机
- `Motor4Ch(i2c, address=0x40)`：初始化电机控制。
- `set_motor(motor_id, speed)`：设置单电机速度，`speed` 范围 `-100~100`。
- `stop_all()`：停止全部电机。

---

## 3. 怎么调用（直接能跑）

### 3.1 单模块测试入口

- 超声波：`distance/test_hc_sr04.py`
- 灰度：`line/test_line.py`
- 电机：`motor/test_motor_integration.py`

### 3.2 推荐调试顺序

1. 先跑电机模拟：`test_motor_integration.py` 里的 `test_mock_harness()`。
2. 再跑灰度实时读取：`line/test_line.py`。
3. 最后跑超声波：`distance/test_hc_sr04.py`。
4. 单项都通过后，再写总调度循环。

### 3.3 最小调度模板

```python
import time
import machine

from distance.hc04 import measure_distance_cm
from line.line import GrayscaleSensor
from motor.motro import Motor4Ch


def main_loop():
    i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21), freq=400000)
    motors = Motor4Ch(i2c, address=0x40)
    sensor = GrayscaleSensor(ad0_pin=25, ad1_pin=26, ad2_pin=27, out_pin=34)

    while True:
        dist = measure_distance_cm()
        line_data = sensor.read_all()

        if 0 < dist < 15:
            motors.stop_all()
        elif line_data[3] == 1 or line_data[4] == 1:
            for m in range(4):
                motors.set_motor(m, 40)
        else:
            motors.set_motor(0, 20)
            motors.set_motor(1, -20)
            motors.set_motor(2, 20)
            motors.set_motor(3, -20)

        time.sleep(0.05)
```

---

## 4. 常见错误与排查

### 错误 1：`ImportError: no module named machine`
原因：在电脑 Python 环境直接跑了 MicroPython 代码。

处理：
- 需要在 ESP32 MicroPython 环境运行硬件代码。
- 电机模块可先用 `test_mock_harness()` 做无硬件验证。

### 错误 2：超声波一直 `-1.0`
原因常见：
- `ECHO` / `TRIG` 接反。
- 供电或地线没接好。
- 目标太近或太远，导致超时。

处理：
- 先确认 `TRIG=GPIO5`、`ECHO=GPIO18`。
- 用万用表确认 5V 与 GND。
- 先拿平整障碍物在 `10~50cm` 范围测试。

### 错误 3：灰度 8 路读数全 0 或全 1
原因常见：
- `AD0/AD1/AD2` 地址线接错。
- `OUT` 没接到 `GPIO34`。
- 传感器阈值电位器未调。

处理：
- 对照真值表检查 `AD0~AD2`。
- 先读单通道 `read_channel(0)` 到 `read_channel(7)` 看是否变化。
- 调整传感器灵敏度后重测。

### 错误 4：电机不转 / 只单方向转
原因常见：
- I2C 引脚错误，或地址不是 `0x40`。
- 驱动板供电不足。
- 电机线序接错。

处理：
- 确认 `SDA=21`、`SCL=22`。
- 检查 `set_motor(motor_id, speed)` 的 `speed` 是否非 0。
- 逐个电机测试：`motor_id=0~3`。

### 错误 5：`ModuleNotFoundError: No module named 'hc_sr04'`
原因：当前实际文件名是 `hc04.py`，不是 `hc_sr04.py`。

处理：
- 导入时用 `import hc04` 或 `from distance.hc04 import ...`。
- 检查 IDE 运行路径是否在项目根目录。

---

## 5. 实战建议（避免翻车）

- 每次只改一个模块，改完立刻跑对应 `test_*.py`。
- 接线后先静态拍照留档，后续排错很快。
- 主循环里先保证“能停住”（`stop_all()`）再做复杂策略。
- 速度调参从 `20~40` 开始，不要一上来 `100`。
