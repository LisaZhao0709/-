import machine
import time

class GrayscaleSensor:
    """
    8路灰度传感器驱动 (基于 CD4051 多路复用器)
    接口: 5V, AD2, AD1, AD0, OUT, GND
    """
    def __init__(self, ad0_pin=25, ad1_pin=26, ad2_pin=27, out_pin=34):
        # 初始化地址引脚
        self.ad0 = machine.Pin(ad0_pin, machine.Pin.OUT)
        self.ad1 = machine.Pin(ad1_pin, machine.Pin.OUT)
        self.ad2 = machine.Pin(ad2_pin, machine.Pin.OUT)
        
        # 初始化输出读取引脚 (如果是数字量信号用 Pin.IN, 如果是模拟量信号用 ADC)
        # 根据用户描述 "输出端口:用于输出数字量信号"，使用 Pin.IN
        self.out = machine.Pin(out_pin, machine.Pin.IN)
        
        # 内部状态：存储8个通道的数据
        self.data = [0] * 8

    def read_channel(self, channel):
        """
        选择通道并读取信号
        channel: 0-7
        """
        if not 0 <= channel <= 7:
            return None
        
        # 设置地址线 (真值表逻辑)
        # AD0 是最低位 (LSB), AD2 是最高位 (MSB)
        self.ad0.value(channel & 0x01)
        self.ad1.value((channel >> 1) & 0x01)
        self.ad2.value((channel >> 2) & 0x01)
        
        # 稍微等待信号稳定 (CD4051 切换速度很快，但传感器响应可能需要时间)
        # time.sleep_us(10) 
        
        return self.out.value()

    def read_all(self):
        """
        循环读取所有8路通道
        """
        for i in range(8):
            self.data[i] = self.read_channel(i)
        return self.data

