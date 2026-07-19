import time
import machine
from motor.motro import Motor4Ch

def run_test(func, *args, **kwargs):
    """
    通用测试运行器，符合用户 global 规范。
    打印状态、耗时、输入和输出。
    """
    start = time.perf_counter()
    try:
        res = func(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000
        print(f" [SUCCESS] 函数: {func.__name__} | 耗时: {duration_ms:.2f}ms")
        print(f" 输入: {args} {kwargs} | 输出: {res}")
        return res
    except Exception as e:
        print(f" [FAILED] 错误原因: {e}")
        raise e

def test_mock_harness():
    """
    Motor-4Ch 模拟测试 (无硬件环境)
    """
    print("--- 启动 Motor-4Ch 模拟连通性测试 ---")
    
    # 模拟 I2C
    class MockI2C:
        def writeto_mem(self, addr, reg, data): pass
        def readfrom_mem(self, addr, reg, length): return b'\x00' * length
    
    mock_i2c = MockI2C()
    motors = Motor4Ch(mock_i2c)

    # 测试不同转速与方向
    run_test(motors.set_motor, 0, 50)   # 电机0 正转 50%
    run_test(motors.set_motor, 1, -80)  # 电机1 反转 80%
    run_test(motors.set_motor, 2, 100)  # 电机2 正转 100%
    run_test(motors.set_motor, 3, 0)    # 电机3 停止
    
    # 全停测试
    run_test(motors.stop_all)
    print("--- 模拟测试完成 ---")

def main():
    print("=== 启动 ESP32-D Motor-4Ch 硬件集成测试 ===")
    
    # 1. 初始化 I2C (ESP32-D 默认引脚)
    try:
        # SDA=21, SCL=22 是 ESP32 标准 I2C 引脚
        i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21), freq=400000)
        print(" [INFO] I2C 初始化成功")
    except Exception as e:
        print(f" [ERROR] I2C 初始化失败: {e}")
        return

    # 2. 实例化电机控制类
    try:
        motors = Motor4Ch(i2c, address=0x40)
        print(" [INFO] Motor4Ch 实例化成功")
    except Exception as e:
        print(f" [ERROR] 无法连接到解码器: {e}")
        return

    # 3. 执行测试序列
    print("\n--- 开始执行动作测试 ---")
    
    # 测试电机 0: 慢速正转
    run_test(motors.set_motor, 0, 30)
    time.sleep(1)
    
    # 测试电机 1: 快速反转
    run_test(motors.set_motor, 1, -80)
    time.sleep(1)
    
    # 测试电机 2 & 3: 不同速度同步转动
    run_test(motors.set_motor, 2, 100)
    run_test(motors.set_motor, 3, -50)
    time.sleep(2)
    
    # 4. 停止所有电机
    print("\n--- 停止测试 ---")
    run_test(motors.stop_all)
    
    print("\n=== 硬件测试全部完成 ===")

if __name__ == "__main__":
    # 执行模拟测试
    test_mock_harness()
    
    # 如果在硬件上运行，可以执行硬件集成测试
    # main()
