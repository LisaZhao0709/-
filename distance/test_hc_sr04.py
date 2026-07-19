# test_hc_sr04.py
"""Basic synchronous verification for hc-sr04 measuring routine."""

import importlib
import sys
import time
import types


class FakePin:
    OUT = 0
    IN = 1

    def __init__(self, pin_no, mode):
        self.pin_no = pin_no
        self.mode = mode
        self.state = 0

    def value(self, val=None):
        if val is None:
            return self.state
        self.state = val


class FakePWM:
    def __init__(self, pin, freq, duty_u16=0):
        self.pin = pin
        self.freq = freq
        self.duty = duty_u16

    def duty_u16(self, value):
        self.duty = value


class MachineStub(types.SimpleNamespace):
    def __init__(self):
        super().__init__(Pin=FakePin, PWM=FakePWM)
        self._pulses = []

    def time_pulse_us(self, pin, level, timeout):
        if not self._pulses:
            raise OSError
        return self._pulses.pop(0)

    def set_pulse(self, duration):
        self._pulses.append(duration)


def run_test(func, *args, **kwargs):
    start = time.perf_counter()
    try:
        res = func(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000
        print(
            f" [SUCCESS] 函数: {func.__name__} | 耗时: {duration_ms:.2f}ms | 输出: {res}"
        )
        return res
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        print(
            f" [FAILED] 函数: {func.__name__} | 耗时: {duration_ms:.2f}ms | 错误: {exc}"
        )
        raise


def reload_with_machine(machine_stub):
    sys.modules.pop("hc_sr04", None)
    sys.modules["machine"] = machine_stub
    return importlib.import_module("hc_sr04")


def test_measure_distance_success():
    machine_stub = MachineStub()
    machine_stub.set_pulse(4000.0)
    module = reload_with_machine(machine_stub)
    distance = run_test(module.measure_distance_cm)
    expected = 4000.0 * 0.0343 / 2
    assert abs(distance - expected) < 1e-3


def test_measure_distance_timeout():
    machine_stub = MachineStub()
    module = reload_with_machine(machine_stub)
    distance = run_test(module.measure_distance_cm)
    assert distance == -1.0


def start_integration_test():
    """
    HC-SR04 测距集成测试 (无限循环)
    """
    import hc04
    print(">>> 启动 HC-SR04 测距集成测试 (Ctrl+C 停止) <<<")
    try:
        while True:
            dist = run_test(hc04.measure_distance_cm)
            if dist < 0:
                print("未检测到回波")
            else:
                print("距离: {:.1f} cm".format(dist))
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n测试正常结束")


if __name__ == "__main__":
    print("Running hc-sr04 unit tests...")
    test_measure_distance_success()
    test_measure_distance_timeout()
    print("Unit tests finished.")
    
    # 如果在硬件上运行，可以取消注释以开始集成测试
    # start_integration_test()
