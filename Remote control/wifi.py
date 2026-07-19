import time

try:
    import network
except ImportError:
    network = None

try:
    import socket
except ImportError:
    socket = None

try:
    import ujson as json
except ImportError:
    import json


CENTER_RAW = 2048
RAW_MIN = 0
RAW_MAX = 4095
RAW_SPAN = 2047
DEADZONE_RAW = 50

MAX_PWM = 255
MAX_PWM_RATIO = 0.8
MAX_PWM_OUT = int(MAX_PWM * MAX_PWM_RATIO)

TURN_DIFF_THRESHOLD_PERCENT = 30.0
TURN_REDUCE_RATIO = 0.9
REAR_FOLLOW_RATIO = 0.95

BRAKE_TRIGGER_PERCENT = 20.0
BRAKE_TRIGGER_WINDOW_MS = 200
E_BRAKE_PERCENT = 5.0
E_BRAKE_DURATION_MS = 100


def _now_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.perf_counter() * 1000)


def _ms_diff(now_ms, start_ms):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(now_ms, start_ms)
    return now_ms - start_ms


def run_test(func, *args, **kwargs):
    start = _now_ms()
    try:
        res = func(*args, **kwargs)
        duration = _ms_diff(_now_ms(), start)
        print(f" [SUCCESS] 函数: {func.__name__} | 耗时: {duration:.2f}ms")
        print(f" 输入: {args} {kwargs} | 输出: {res}")
        return res
    except Exception as e:
        duration = _ms_diff(_now_ms(), start)
        print(f" [FAILED] 函数: {func.__name__} | 耗时: {duration:.2f}ms | 错误原因: {e}")
        raise e


def clamp_int(value, low, high):
    return max(low, min(high, int(value)))


def apply_deadzone(offset_raw):
    if abs(offset_raw) < DEADZONE_RAW:
        return 0
    return offset_raw


def raw_to_percent(raw_value):
    raw_value = clamp_int(raw_value, RAW_MIN, RAW_MAX)
    offset = apply_deadzone(raw_value - CENTER_RAW)
    if offset == 0:
        return 0.0

    norm = min(1.0, abs(offset) / RAW_SPAN)
    return (1 if offset > 0 else -1) * (norm * norm) * 100.0


def percent_to_pwm(percent_value):
    percent_value = max(-100.0, min(100.0, float(percent_value)))
    value = int(round(percent_value / 100.0 * MAX_PWM_OUT))
    return clamp_int(value, -MAX_PWM_OUT, MAX_PWM_OUT)


def apply_turn_assist(left_front, right_front, left_percent, right_percent):
    if abs(left_percent - right_percent) <= TURN_DIFF_THRESHOLD_PERCENT:
        return left_front, right_front

    if abs(left_front) > abs(right_front):
        left_front = int(round(left_front * TURN_REDUCE_RATIO))
    else:
        right_front = int(round(right_front * TURN_REDUCE_RATIO))
    return left_front, right_front


def apply_inplace_rotation(left_front, right_front):
    if left_front == 0 or right_front == 0:
        return left_front, right_front

    if left_front * right_front >= 0:
        return left_front, right_front

    if abs(abs(left_front) - abs(right_front)) > 8:
        return left_front, right_front

    mag = int(round((abs(left_front) + abs(right_front)) / 2.0))
    return (mag if left_front > 0 else -mag), (mag if right_front > 0 else -mag)


def rear_follow(front_value):
    return int(round(front_value * REAR_FOLLOW_RATIO))


def mode_cn(mode):
    return "滑行" if mode == "coast" else "电刹"


def sign_nonzero(value, default=1):
    if value > 0:
        return 1
    if value < 0:
        return -1
    return default


class SimState:
    def __init__(self):
        now = _now_ms()
        self.left_percent = 0.0
        self.right_percent = 0.0
        self.wheels = {"lf": 0, "lr": 0, "rf": 0, "rr": 0}
        self.left_raw = {"x": CENTER_RAW, "y": CENTER_RAW}
        self.right_raw = {"x": CENTER_RAW, "y": CENTER_RAW}
        self.brake_mode = "coast"
        self.prev_left_percent = 0.0
        self.prev_right_percent = 0.0
        self.prev_update_ms = now
        self.last_signal_ms = now
        self.signal_timeout_ms = 1500
        self.ebrake_until_ms = 0
        self.ebrake_left_sign = -1
        self.ebrake_right_sign = -1

    def _force_stop(self):
        self.wheels["lf"] = 0
        self.wheels["lr"] = 0
        self.wheels["rf"] = 0
        self.wheels["rr"] = 0
        self.left_percent = 0.0
        self.right_percent = 0.0
        self.ebrake_until_ms = 0

    def update_control(self, left_raw, right_raw, brake_mode="coast", now_ms=None):
        now_ms = _now_ms() if now_ms is None else now_ms
        self.brake_mode = "ebrake" if brake_mode == "ebrake" else "coast"

        lx = clamp_int(left_raw.get("x", CENTER_RAW), RAW_MIN, RAW_MAX)
        ly = clamp_int(left_raw.get("y", CENTER_RAW), RAW_MIN, RAW_MAX)
        rx = clamp_int(right_raw.get("x", CENTER_RAW), RAW_MIN, RAW_MAX)
        ry = clamp_int(right_raw.get("y", CENTER_RAW), RAW_MIN, RAW_MAX)

        left_percent = raw_to_percent(ly)
        right_percent = raw_to_percent(ry)
        both_center = left_percent == 0.0 and right_percent == 0.0

        max_prev_abs = max(abs(self.prev_left_percent), abs(self.prev_right_percent))
        delta_ms = _ms_diff(now_ms, self.prev_update_ms)
        quick_center = both_center and max_prev_abs > BRAKE_TRIGGER_PERCENT and delta_ms <= BRAKE_TRIGGER_WINDOW_MS

        if both_center and self.brake_mode == "ebrake" and quick_center:
            self.ebrake_until_ms = now_ms + E_BRAKE_DURATION_MS
            self.ebrake_left_sign = -sign_nonzero(self.prev_left_percent, 1)
            self.ebrake_right_sign = -sign_nonzero(self.prev_right_percent, 1)

        if both_center:
            if _ms_diff(self.ebrake_until_ms, now_ms) > 0 and self.brake_mode == "ebrake":
                brake_pwm = percent_to_pwm(E_BRAKE_PERCENT)
                lf = self.ebrake_left_sign * brake_pwm
                rf = self.ebrake_right_sign * brake_pwm
            else:
                lf = 0
                rf = 0
        else:
            self.ebrake_until_ms = 0
            lf = percent_to_pwm(left_percent)
            rf = percent_to_pwm(right_percent)
            lf, rf = apply_turn_assist(lf, rf, left_percent, right_percent)
            lf, rf = apply_inplace_rotation(lf, rf)

        if both_center and self.brake_mode == "coast":
            lf = 0
            rf = 0

        lr = rear_follow(lf)
        rr = rear_follow(rf)

        self.wheels["lf"] = lf
        self.wheels["lr"] = lr
        self.wheels["rf"] = rf
        self.wheels["rr"] = rr
        self.left_percent = left_percent
        self.right_percent = right_percent
        self.left_raw = {"x": lx, "y": ly}
        self.right_raw = {"x": rx, "y": ry}

        self.prev_left_percent = left_percent
        self.prev_right_percent = right_percent
        self.prev_update_ms = now_ms
        self.last_signal_ms = now_ms

    def tick(self, now_ms=None):
        now_ms = _now_ms() if now_ms is None else now_ms
        if _ms_diff(now_ms, self.last_signal_ms) >= self.signal_timeout_ms:
            self._force_stop()

    def to_dict(self):
        return {
            "lf": self.wheels["lf"],
            "lr": self.wheels["lr"],
            "rf": self.wheels["rf"],
            "rr": self.wheels["rr"],
            "left_percent": self.left_percent,
            "right_percent": self.right_percent,
            "left_raw": self.left_raw,
            "right_raw": self.right_raw,
            "brake_mode": self.brake_mode,
            "signal_timeout_ms": self.signal_timeout_ms,
            "mode": "simulation_only",
        }

    def format_status_line(self):
        return (
            f"LF:{self.wheels['lf']:+d} "
            f"LR:{self.wheels['lr']:+d} "
            f"RF:{self.wheels['rf']:+d} "
            f"RR:{self.wheels['rr']:+d} | "
            f"左杆Y:{self.left_percent:+.0f}% "
            f"右杆Y:{self.right_percent:+.0f}% | "
            f"模式:{mode_cn(self.brake_mode)}"
        )


class CarRemoteServer:
    def __init__(self):
        self.state = SimState()
        self.print_interval_ms = 50
        self.last_print_ms = 0

    def connect_wifi(self, mode="ap", ssid="ESP32D_CAR", password="12345678", timeout=15):
        if network is None:
            return {"mode": "mock", "ip": "127.0.0.1"}

        mode = (mode or "ap").lower()
        if mode == "sta":
            sta = network.WLAN(network.STA_IF)
            sta.active(True)
            if not sta.isconnected():
                sta.connect(ssid, password)
                t0 = _now_ms()
                while (not sta.isconnected()) and _ms_diff(_now_ms(), t0) < timeout * 1000:
                    time.sleep(0.2)
            if not sta.isconnected():
                raise RuntimeError("STA 模式连接失败")
            ip = sta.ifconfig()[0]
            return {"mode": "sta", "ip": ip, "ssid": ssid}

        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid=ssid, password=password)
        ip = ap.ifconfig()[0]
        return {"mode": "ap", "ip": ip, "ssid": ssid, "password": password}

    def _send_response(self, conn, status, body_bytes, content_type="text/plain; charset=utf-8"):
        header = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n\r\n"
        )
        conn.send(header.encode("utf-8"))
        conn.send(body_bytes)

    def _json_bytes(self, data):
        return json.dumps(data).encode("utf-8")

    def _read_request(self, conn):
        data = conn.recv(4096)
        if not data:
            return None, None, None

        split_at = data.find(b"\r\n\r\n")
        if split_at < 0:
            return None, None, None

        head = data[:split_at].decode("utf-8", "ignore")
        body = data[split_at + 4 :]

        lines = head.split("\r\n")
        first = lines[0].split(" ")
        if len(first) < 2:
            return None, None, None
        method = first[0]
        path = first[1]

        content_length = 0
        for line in lines[1:]:
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except Exception:
                    content_length = 0
                break

        while len(body) < content_length:
            chunk = conn.recv(1024)
            if not chunk:
                break
            body += chunk

        return method, path, body

    def _handle_control(self, body_bytes):
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            payload = {}

        left = payload.get("left", {})
        right = payload.get("right", {})
        brake_mode = payload.get("brake_mode", "coast")

        left_raw = {
            "x": left.get("x_raw", CENTER_RAW),
            "y": left.get("y_raw", CENTER_RAW),
        }
        right_raw = {
            "x": right.get("x_raw", CENTER_RAW),
            "y": right.get("y_raw", CENTER_RAW),
        }

        self.state.update_control(left_raw=left_raw, right_raw=right_raw, brake_mode=brake_mode)
        return self.state.to_dict()

    def _build_html(self):
        return """<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>四轮小车摇杆控制模拟器</title>
<style>
body{margin:0;background:#101722;color:#eaf0ff;font-family:Arial,sans-serif}
.app{max-width:1200px;margin:8px auto;padding:8px}
h1{margin:0 0 8px;text-align:center;font-size:24px}
.top{display:flex;justify-content:center;gap:16px;flex-wrap:wrap;background:#162133;padding:8px;border-radius:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.card{background:#1a263a;border-radius:12px;padding:10px}
.card h2{margin:0 0 8px;text-align:center;font-size:16px}
canvas{width:100%;max-width:360px;aspect-ratio:1/1;display:block;margin:0 auto;background:#23324a;border-radius:50%;touch-action:none}
.axis{margin-top:6px;text-align:center;font-size:12px;color:#b6c3d7;line-height:1.4}
.wheels{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:10px;margin-top:12px}
.w{background:#141e2d;padding:8px;border-radius:10px}
.row{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px}
.bar{height:10px;background:#3a4557;border-radius:999px;overflow:hidden}
.fill{height:100%;width:0%}
.status{margin-top:10px;background:#0f1826;border-radius:8px;padding:8px;text-align:center;font-family:Consolas,monospace;font-size:13px}
.landscape-tip{display:block;margin-top:8px;text-align:center;color:#ffd28a;font-size:12px}
@media (max-width:760px){
  .app{padding:6px}
  h1{font-size:18px}
  .grid{grid-template-columns:1fr 1fr;gap:8px}
  .card{padding:8px}
  .card h2{font-size:14px}
  canvas{max-width:45vw}
  .wheels{grid-template-columns:repeat(2,minmax(130px,1fr));gap:6px}
}
</style>
</head>
<body>
<div class='app'>
<h1>四轮小车摇杆控制模拟器</h1>
<div class='top'>
<label><input id='ebrake' type='checkbox'> 电刹模式（默认滑行）</label>
<span id='conn'>状态: 连接中</span>
</div>
<div class='landscape-tip'>建议横屏操作：双摇杆可同时触控，体验更稳定。</div>

<div class='grid'>
  <div class='card'>
    <h2>左摇杆（LF/LR）</h2>
    <canvas id='left' width='300' height='300'></canvas>
    <div id='leftInfo' class='axis'></div>
  </div>
  <div class='card'>
    <h2>右摇杆（RF/RR）</h2>
    <canvas id='right' width='300' height='300'></canvas>
    <div id='rightInfo' class='axis'></div>
  </div>
</div>

<div class='wheels' id='wheels'></div>
<div class='status' id='statusLine'>LF:+0 LR:+0 RF:+0 RR:+0 | 左杆Y:+0% 右杆Y:+0% | 模式:滑行</div>
</div>

<script>
const CENTER=2048, SPAN=2047, DZ=50;
const wheelNames=['LF','LR','RF','RR'];
const wheels={};
const wheelWrap=document.getElementById('wheels');
wheelNames.forEach(n=>{
  const el=document.createElement('div');
  el.className='w';
  el.innerHTML=`<div class='row'><b>${n}</b><span id='${n}T'>+0 停止</span></div><div class='bar'><div class='fill' id='${n}F'></div></div>`;
  wheelWrap.appendChild(el);
  wheels[n]={t:document.getElementById(n+'T'),f:document.getElementById(n+'F')};
});

function clamp(v,l,h){return Math.max(l,Math.min(h,v));}
function sign(v){return v>0?1:(v<0?-1:0);}
function rawToPercent(raw){
  raw=clamp(Math.round(raw),0,4095);
  let off=raw-CENTER;
  if(Math.abs(off)<DZ)off=0;
  if(!off)return 0;
  const n=Math.min(1,Math.abs(off)/SPAN);
  return sign(off)*n*n*100;
}
function color(v){return v>0?'#24b36b':(v<0?'#d65454':'#7d8794');}
function dir(v){return v>0?'正转':(v<0?'反转':'停止');}

class Joy{
  constructor(canvasId,infoId){
    this.c=document.getElementById(canvasId);this.i=document.getElementById(infoId);
    this.ctx=this.c.getContext('2d');this.r=this.c.width*0.4;this.k=this.c.width*0.1;this.cx=this.c.width/2;this.cy=this.c.height/2;
    this.dx=0;this.dy=0;this.drag=false;this.touchId=null;this.bind();this.draw();
  }
  bind(){
    const downMouse=e=>{this.drag=true;this.moveByPoint(e.clientX,e.clientY);};
    const moveMouse=e=>{if(this.drag)this.moveByPoint(e.clientX,e.clientY);};
    const upMouse=()=>{if(this.touchId===null){this.drag=false;this.dx=0;this.dy=0;this.draw();}};

    const downTouch=e=>{
      if(e.cancelable)e.preventDefault();
      if(this.touchId!==null)return;
      const t=e.changedTouches[0];
      this.touchId=t.identifier;
      this.drag=true;
      this.moveByPoint(t.clientX,t.clientY);
    };
    const moveTouch=e=>{
      if(this.touchId===null)return;
      if(e.cancelable)e.preventDefault();
      const t=this.findTouchById(e.touches,this.touchId);
      if(t)this.moveByPoint(t.clientX,t.clientY);
    };
    const upTouch=e=>{
      const t=this.findTouchById(e.changedTouches,this.touchId);
      if(!t)return;
      if(e.cancelable)e.preventDefault();
      this.touchId=null;
      this.drag=false;
      this.dx=0;
      this.dy=0;
      this.draw();
    };

    this.c.addEventListener('mousedown',downMouse);
    window.addEventListener('mousemove',moveMouse);
    window.addEventListener('mouseup',upMouse);
    this.c.addEventListener('touchstart',downTouch,{passive:false});
    window.addEventListener('touchmove',moveTouch,{passive:false});
    window.addEventListener('touchend',upTouch,{passive:false});
    window.addEventListener('touchcancel',upTouch,{passive:false});
  }
  findTouchById(list,id){if(id===null||!list)return null;for(let i=0;i<list.length;i++){if(list[i].identifier===id)return list[i];}return null;}
  moveByPoint(clientX,clientY){const r=this.c.getBoundingClientRect();let dx=clientX-r.left-this.cx,dy=clientY-r.top-this.cy;const len=Math.hypot(dx,dy);if(len>this.r){dx*=this.r/len;dy*=this.r/len;}this.dx=dx;this.dy=dy;this.draw();}
  raw(){const nx=this.dx/this.r, ny=this.dy/this.r;return {x_raw:clamp(Math.round(CENTER+nx*SPAN),0,4095), y_raw:clamp(Math.round(CENTER-ny*SPAN),0,4095)};}
  draw(){const c=this.ctx;c.clearRect(0,0,this.c.width,this.c.height);c.beginPath();c.arc(this.cx,this.cy,this.r,0,Math.PI*2);c.strokeStyle='rgba(255,255,255,.45)';c.lineWidth=2;c.stroke();c.beginPath();c.arc(this.cx,this.cy,this.k,0,Math.PI*2);c.fillStyle='#2da8ff';c.fill();c.beginPath();c.arc(this.cx+this.dx,this.cy+this.dy,this.k,0,Math.PI*2);c.fillStyle='#2da8ff';c.fill();const raw=this.raw();this.i.innerHTML=`X 原始:${raw.x_raw} | X 映射:${rawToPercent(raw.x_raw).toFixed(1)}%<br>Y 原始:${raw.y_raw} | Y 映射:${rawToPercent(raw.y_raw).toFixed(1)}%`;}
}

const leftJoy=new Joy('left','leftInfo');
const rightJoy=new Joy('right','rightInfo');
const ebrakeEl=document.getElementById('ebrake');
const connEl=document.getElementById('conn');
const statusEl=document.getElementById('statusLine');

function setWheel(name,v){const e=wheels[name];e.t.textContent=`${v>=0?'+':''}${v} ${dir(v)}`;e.f.style.width=`${Math.round(Math.abs(v)/255*100)}%`;e.f.style.background=color(v);}

function updateState(s){
  if(!s)return;
  setWheel('LF',s.lf);setWheel('LR',s.lr);setWheel('RF',s.rf);setWheel('RR',s.rr);
  statusEl.textContent=`LF:${s.lf>=0?'+':''}${s.lf} LR:${s.lr>=0?'+':''}${s.lr} RF:${s.rf>=0?'+':''}${s.rf} RR:${s.rr>=0?'+':''}${s.rr} | 左杆Y:${s.left_percent>=0?'+':''}${s.left_percent.toFixed(0)}% 右杆Y:${s.right_percent>=0?'+':''}${s.right_percent.toFixed(0)}% | 模式:${s.brake_mode==='coast'?'滑行':'电刹'}`;
}

async function sendControl(){
  const payload={left:leftJoy.raw(),right:rightJoy.raw(),brake_mode:ebrakeEl.checked?'ebrake':'coast'};
  try{
    const r=await fetch('/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(r.ok){updateState(await r.json());connEl.textContent='状态: 已连接';}
    else{connEl.textContent='状态: 异常响应';}
  }catch(e){connEl.textContent='状态: 已断开';}
}

setInterval(sendControl,50);

async function tryLockLandscape(){
  try{
    if(screen.orientation&&screen.orientation.lock){
      await screen.orientation.lock('landscape');
      connEl.textContent='状态: 已连接（横屏锁定）';
      return;
    }
  }catch(e){}
}

window.addEventListener('load',()=>{tryLockLandscape();});
</script>
</body>
</html>"""

    def _handle_request(self, conn):
        method, path, body = self._read_request(conn)
        if not method:
            self._send_response(conn, "400 Bad Request", b"bad request")
            return

        if method == "GET" and path == "/":
            html = self._build_html().encode("utf-8")
            self._send_response(conn, "200 OK", html, "text/html; charset=utf-8")
            return

        if method == "GET" and path.startswith("/state"):
            self._send_response(conn, "200 OK", self._json_bytes(self.state.to_dict()), "application/json")
            return

        if method == "POST" and path.startswith("/control"):
            data = self._handle_control(body)
            self._send_response(conn, "200 OK", self._json_bytes(data), "application/json")
            return

        self._send_response(conn, "404 Not Found", b"not found")

    def _print_status_if_needed(self):
        now = _now_ms()
        if _ms_diff(now, self.last_print_ms) < self.print_interval_ms:
            return
        self.last_print_ms = now
        line = self.state.format_status_line()
        print("\r" + line, end="")

    def start(self, host="0.0.0.0", port=80):
        if socket is None:
            raise RuntimeError("当前环境无 socket，无法启动 HTTP 服务")

        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(2)
        server.settimeout(0.05)
        print(f"[INFO] HTTP 服务已启动: http://{host}:{port}")

        while True:
            now = _now_ms()
            self.state.tick(now)
            self._print_status_if_needed()

            try:
                conn, _ = server.accept()
            except OSError:
                continue

            try:
                self._handle_request(conn)
            except Exception as e:
                try:
                    self._send_response(conn, "500 Internal Server Error", str(e).encode("utf-8"))
                except Exception:
                    pass
            finally:
                conn.close()


def test_deadzone_rule():
    return {
        "offset_30": apply_deadzone(30),
        "offset_80": apply_deadzone(80),
        "center_percent": raw_to_percent(CENTER_RAW),
    }


def test_nonlinear_mapping_rule():
    return {
        "raw_2300": raw_to_percent(2300),
        "raw_3072": raw_to_percent(3072),
        "raw_4095": raw_to_percent(4095),
    }


def test_speed_limit_rule():
    return {
        "pwm_100": percent_to_pwm(100),
        "pwm_-100": percent_to_pwm(-100),
        "pwm_160": percent_to_pwm(160),
    }


def test_turn_assist_rule():
    before = (190, 20)
    after = apply_turn_assist(before[0], before[1], 95, 10)
    return {"before": before, "after": after}


def test_inplace_rotation_rule():
    return {"after": apply_inplace_rotation(120, -118)}


def test_rear_follow_rule():
    return {"front": 200, "rear": rear_follow(200)}


def test_brake_modes_rule():
    sim = SimState()
    sim.update_control({"x": CENTER_RAW, "y": 4095}, {"x": CENTER_RAW, "y": 4095}, "ebrake", now_ms=1000)
    sim.update_control({"x": CENTER_RAW, "y": CENTER_RAW}, {"x": CENTER_RAW, "y": CENTER_RAW}, "ebrake", now_ms=1100)
    return sim.to_dict()


def test_center_force_stop_rule():
    sim = SimState()
    sim.update_control({"x": CENTER_RAW, "y": 3200}, {"x": CENTER_RAW, "y": 3200}, "coast", now_ms=1000)
    sim.update_control({"x": CENTER_RAW, "y": CENTER_RAW}, {"x": CENTER_RAW, "y": CENTER_RAW}, "coast", now_ms=1010)
    return sim.to_dict()


def test_timeout_force_stop_rule():
    sim = SimState()
    sim.signal_timeout_ms = 10
    sim.update_control({"x": CENTER_RAW, "y": 3500}, {"x": CENTER_RAW, "y": 3500}, "coast", now_ms=1000)
    sim.tick(now_ms=1015)
    return sim.to_dict()


def run_all_tests():
    print("=== wifi.py 双摇杆纯模拟自检开始 ===")
    run_test(test_deadzone_rule)
    run_test(test_nonlinear_mapping_rule)
    run_test(test_speed_limit_rule)
    run_test(test_turn_assist_rule)
    run_test(test_inplace_rotation_rule)
    run_test(test_rear_follow_rule)
    run_test(test_brake_modes_rule)
    run_test(test_center_force_stop_rule)
    run_test(test_timeout_force_stop_rule)
    print("=== wifi.py 双摇杆纯模拟自检结束 ===")


def main():
    server = CarRemoteServer()
    wifi_info = server.connect_wifi(mode="ap", ssid="ESP32D_CAR", password="12345678")
    print(f"[INFO] Wi-Fi 已就绪: {wifi_info}")
    print("[INFO] 手机连接后打开浏览器访问上面的 IP")
    print("[INFO] 当前为纯模拟模式，不访问 I2C/电机硬件")
    server.start(host="0.0.0.0", port=80)


if __name__ == "__main__":
    run_all_tests()
    main()
