import time
from line import GrayscaleSensor

def run_test(func, *args, **kwargs):
    """
    [规范要求] 详细输出报告与耗时统计 (微秒级精确版)
    """
    start = time.ticks_us()
    try:
        res = func(*args, **kwargs)
        duration_us = time.ticks_diff(time.ticks_us(), start)
        print(f" [SUCCESS] 扫描耗时: {duration_us} us (约 {1000000/duration_us:.1f} Hz)")
        
        # 满足用户需求：按顺序输出几号传感器的数值是多少
        if isinstance(res, list) and len(res) == 8:
            print("-" * 30)
            for i, val in enumerate(res):
                # 明确输出：几号传感器: 数值
                status = "检测到" if val else "未触发"
                print(f" 传感器 {i} 号: 数值 = {val} ({status})")
            print("-" * 30)
            
        return res
    except Exception as e:
        print(f" [FAILED] 错误原因: {e}")
        raise e

def start_integration_test():
    """
    传感器全链路集成测试
    """
    # 硬件引脚配置
    sensor = GrayscaleSensor(ad0_pin=25, ad1_pin=26, ad2_pin=27, out_pin=34)
    
    print(">>> 开启8路灰度传感器顺序读取测试 (Ctrl+C 停止) <<<")
    try:
        while True:
            run_test(sensor.read_all)
            time.sleep(1.0)  # 降低刷新频率，方便查看输出
    except KeyboardInterrupt:
        print("\n测试正常结束")

if __name__ == "__main__":
    start_integration_test()
