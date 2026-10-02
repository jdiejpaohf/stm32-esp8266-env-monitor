#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock Server v2 - 模拟 OneNET 温湿度+光照后端 v2，用于前端全功能测试。
同步 v2 新增：alert_type / ai_score / ai_anomaly 字段 + 滑动窗口 AI 异常检测模拟。

启动: python mock_server.py
端口: 8000（与真实后端一致，前端无需改地址）
前端连接: http://localhost:8000  ws://localhost:8000/ws

场景循环（每2秒一条，约70秒一轮）:
  1. 正常数据 ×4
  2. 温度标红(>40) → 弹窗(>50) → 回落
  3. 湿度标红(>70) → 弹窗(>80) → 回落
  4. 温湿度同时弹窗（alert_type=both）
  5. 温度突变(相邻差值>5)
  6. AI异常：温度骤降到15°C（阈值内但统计异常，alert_type=ai_anomaly）
  7. AI异常：湿度跳到68%（阈值内但统计异常）
  8. 阈值+AI同时异常（温度52°C + AI也判定异常，alert_type=both）
  9. 光照过低(<10) → 恢复
  10. 设备离线模拟 → 上线恢复
  11. 正常收尾
"""
import asyncio
import json
import random
import math
from collections import deque
from datetime import datetime

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

# ==================== 配置 ====================
MOCK_PORT = 8000
MAX_HISTORY = 2000
FILTER_WINDOW = 5

# 告警阈值（与真实后端 v2 一致）
TEMP_RED_LINE = 40.0
TEMP_POPUP_LINE = 50.0
HUM_RED_LINE = 70.0
HUM_POPUP_LINE = 80.0
CHANGE_THRESHOLD = 5.0
LIGHT_LOW_THRESHOLD = 10
DEVICE_OFFLINE_SECONDS = 180

# AI 配置（模拟 v2 的滑动窗口 + 隔离森林）
AI_WINDOW_SIZE = 100
AI_MIN_TRAIN = 15  # mock 里降低最小训练量，让 AI 异常场景更早触发
AI_SCORE_THRESHOLD = -0.1

# ==================== 测试场景序列 ====================
# (temp, humi, light, 描述, force_offline)
SCENARIOS = [
    # 阶段1: 正常运行（4条）—— 稳定基线，让 AI 学到正常分布
    (25.0, 50.0, 60, "正常", False),
    (25.5, 50.5, 58, "正常", False),
    (26.0, 51.0, 55, "正常", False),
    (27.0, 52.0, 50, "正常", False),

    # 阶段2: 温度标红 → 弹窗 → 回落（5条）
    (35.0, 55.0, 50, "温度缓升", False),
    (42.0, 58.0, 48, "温度标红(>40)", False),
    (52.0, 50.0, 50, "温度弹窗(>50)→alert", False),
    (45.0, 55.0, 55, "温度回落", False),
    (28.0, 55.0, 58, "温度恢复正常", False),

    # 阶段3: 湿度标红 → 弹窗 → 回落（5条）
    (25.0, 65.0, 60, "湿度缓升", False),
    (25.0, 72.0, 60, "湿度标红(>70)", False),
    (25.0, 82.0, 60, "湿度弹窗(>80)→alert", False),
    (25.0, 68.0, 60, "湿度回落", False),
    (25.0, 55.0, 60, "湿度恢复正常", False),

    # 阶段4: 温湿度同时弹窗（2条）→ alert_type=both
    (52.0, 82.0, 50, "温湿度同时弹窗→alert", False),
    (30.0, 60.0, 55, "恢复正常", False),

    # 阶段5: 突变检测（2条）→ temp_anomaly=true
    (25.0, 50.0, 60, "正常基线", False),
    (35.0, 50.0, 60, "温度突变(+10>5)", False),

    # 阶段6: AI异常——温度骤降到15°C（阈值内0-40，但偏离正常25-27分布）
    (15.0, 50.0, 60, "AI异常:温度骤降(15°C,阈值内)", False),
    (16.0, 51.0, 58, "AI异常持续", False),
    (25.0, 50.0, 60, "温度恢复正常", False),

    # 阶段7: AI异常——湿度跳到68%（阈值内0-70，但偏离正常50-55分布）
    (25.0, 68.0, 60, "AI异常:湿度偏高(68%,阈值内)", False),
    (25.0, 55.0, 60, "湿度恢复正常", False),

    # 阶段8: 阈值+AI同时异常（温度52°C超弹窗线 + AI也判定异常）→ alert_type=both
    (52.0, 50.0, 50, "阈值+AI同时异常→alert_type=both", False),
    (28.0, 50.0, 58, "恢复正常", False),

    # 阶段9: 光照过低 → 恢复（3条）
    (28.0, 52.0, 8, "光照过低(<10)", False),
    (28.0, 52.0, 5, "光照过低持续", False),
    (28.0, 52.0, 55, "光照恢复", False),

    # 阶段10: 设备离线模拟（3条，只发status不发data）
    (0, 0, 0, "设备离线", True),
    (0, 0, 0, "设备离线持续", True),
    (0, 0, 0, "设备上线恢复", False),

    # 阶段11: 正常收尾
    (25.0, 50.0, 60, "正常收尾", False),
]


# ==================== AI 模拟检测器 ====================
class MockAIDetector:
    """
    模拟 v2 的滑动窗口 + 隔离森林 AI 检测。
    用简单的统计方法（z-score）模拟 IsolationForest 的 score_samples 输出。
    score 越低 = 越异常（与 sklearn IsolationForest 一致）。
    """
    def __init__(self):
        self.window = deque(maxlen=AI_WINDOW_SIZE)
        self.min_train = AI_MIN_TRAIN

    def detect(self, temp, hum):
        """
        返回 (ai_score, ai_anomaly)
        ai_score: float 或 None（样本不足时）
        ai_anomaly: bool
        """
        self.window.append((temp, hum))

        if len(self.window) < self.min_train:
            return None, False

        # 计算 z-score 模拟 AI 分数
        temps = [t for t, h in self.window]
        hums = [h for t, h in self.window]
        mean_t = sum(temps) / len(temps)
        mean_h = sum(hums) / len(hums)
        var_t = sum((t - mean_t) ** 2 for t in temps) / len(temps)
        var_h = sum((h - mean_h) ** 2 for h in hums) / len(hums)
        std_t = math.sqrt(var_t) if var_t > 0 else 0.001
        std_h = math.sqrt(var_h) if var_h > 0 else 0.001

        z_t = abs(temp - mean_t) / std_t
        z_h = abs(hum - mean_h) / std_h
        max_z = max(z_t, z_h)

        # 映射到 IsolationForest score 范围（约 -0.5 ~ 0.3）
        # z=0 → score≈0.05（正常）
        # z=1 → score≈-0.1（临界）
        # z=2 → score≈-0.25（异常）
        score = round(0.05 - max_z * 0.15, 3)
        is_anomaly = score < AI_SCORE_THRESHOLD
        return score, is_anomaly


# ==================== 模拟数据生成器 ====================
class MockDataGenerator:
    def __init__(self):
        self.history = deque(maxlen=MAX_HISTORY)
        self.latest = None
        self.last_data_time = datetime.now().timestamp()
        self.temp_filter = deque(maxlen=FILTER_WINDOW)
        self.hum_filter = deque(maxlen=FILTER_WINDOW)
        self.light_filter = deque(maxlen=FILTER_WINDOW)
        self.prev_temp = None
        self.prev_hum = None
        self.scenario_idx = 0
        self.force_offline = False
        self.ai_detector = MockAIDetector()

    def _smooth(self, filter_buf, val):
        filter_buf.append(val)
        return sum(filter_buf) / len(filter_buf)

    def _get_alert_levels(self, temp, hum):
        levels = {}
        if temp >= TEMP_POPUP_LINE or temp < 0:
            levels['temp'] = 'popup'
        elif temp >= TEMP_RED_LINE or temp < 5:
            levels['temp'] = 'red'
        else:
            levels['temp'] = 'normal'
        if hum >= HUM_POPUP_LINE or hum < 0:
            levels['hum'] = 'popup'
        elif hum >= HUM_RED_LINE or hum < 10:
            levels['hum'] = 'red'
        else:
            levels['hum'] = 'normal'
        return levels

    def _get_alert_reasons(self, temp, hum, temp_anomaly, hum_anomaly,
                           ai_anomaly, threshold_alert):
        reasons = []
        levels = self._get_alert_levels(temp, hum)
        if levels['temp'] == 'popup':
            reasons.append("温度超限弹窗")
        elif levels['temp'] == 'red':
            reasons.append("温度超限标红")
        if levels['hum'] == 'popup':
            reasons.append("湿度超限弹窗")
        elif levels['hum'] == 'red':
            reasons.append("湿度超限标红")
        if temp_anomaly:
            reasons.append("温度突变")
        if hum_anomaly:
            reasons.append("湿度突变")
        # AI 异常且无阈值告警时追加原因（与 v2 一致）
        if ai_anomaly and not threshold_alert:
            reasons.append("AI检测异常")
        return reasons

    def generate(self):
        """生成一条模拟数据，返回 (record, desc)"""
        temp_raw, hum_raw, light_raw, desc, offline = SCENARIOS[self.scenario_idx]
        self.scenario_idx = (self.scenario_idx + 1) % len(SCENARIOS)
        self.force_offline = offline

        if offline:
            return None, desc

        # 加微小随机抖动
        temp_raw += random.uniform(-0.5, 0.5)
        hum_raw += random.uniform(-1.0, 1.0)
        light_raw = int(light_raw + random.randint(-2, 2))
        light_raw = max(0, light_raw)

        temp_filtered = self._smooth(self.temp_filter, temp_raw)
        hum_filtered = self._smooth(self.hum_filter, hum_raw)
        light_filtered = self._smooth(self.light_filter, light_raw)

        # 突变检测
        temp_anomaly = self.prev_temp is not None and abs(temp_raw - self.prev_temp) > CHANGE_THRESHOLD
        hum_anomaly = self.prev_hum is not None and abs(hum_raw - self.prev_hum) > CHANGE_THRESHOLD
        self.prev_temp = temp_raw
        self.prev_hum = hum_raw

        levels = self._get_alert_levels(temp_raw, hum_raw)

        # ---- AI 并行检测 ----
        ai_score, ai_anomaly = self.ai_detector.detect(temp_raw, hum_raw)

        # ---- 计算综合告警类型（与 v2 逻辑一致）----
        threshold_alert = (levels['temp'] != 'normal' or levels['hum'] != 'normal')
        if threshold_alert and ai_anomaly:
            alert_type = 'both'
        elif threshold_alert:
            alert_type = 'threshold'
        elif ai_anomaly:
            alert_type = 'ai_anomaly'
        else:
            alert_type = 'normal'

        reasons = self._get_alert_reasons(
            temp_raw, hum_raw, temp_anomaly, hum_anomaly,
            ai_anomaly, threshold_alert
        )

        now = datetime.now()
        record = {
            'timestamp': now.isoformat(),
            'temp_raw': round(temp_raw, 2),
            'hum_raw': round(hum_raw, 2),
            'light_raw': light_raw,
            'temp_filtered': round(temp_filtered, 2),
            'hum_filtered': round(hum_filtered, 2),
            'light_filtered': round(light_filtered, 1),
            'temp_anomaly': temp_anomaly,
            'hum_anomaly': hum_anomaly,
            'temp_level': levels['temp'],
            'hum_level': levels['hum'],
            'alert_reasons': reasons,
            # ---- v2 新增 AI 字段 ----
            'alert_type': alert_type,
            'ai_score': ai_score,
            'ai_anomaly': ai_anomaly,
            '_desc': desc,
        }
        self.history.append(record)
        self.latest = record
        self.last_data_time = now.timestamp()
        return record, desc

    def is_device_online(self):
        if self.force_offline:
            return False
        return (datetime.now().timestamp() - self.last_data_time) < DEVICE_OFFLINE_SECONDS


# ==================== 消息构建（与真实后端 v2 一致） ====================
def build_data_message(record):
    return {
        'type': 'data',
        'timestamp': record['timestamp'],
        'temp': record['temp_filtered'],
        'hum': record['hum_filtered'],
        'light': record['light_filtered'],
        'temp_raw': record['temp_raw'],
        'hum_raw': record['hum_raw'],
        'light_raw': record['light_raw'],
        'temp_anomaly': record['temp_anomaly'],
        'hum_anomaly': record['hum_anomaly'],
        'temp_level': record['temp_level'],
        'hum_level': record['hum_level'],
        'alert_reasons': record.get('alert_reasons', []),
        # ---- v2 新增 AI 字段 ----
        'alert_type': record.get('alert_type', 'normal'),
        'ai_score': record.get('ai_score'),
        'ai_anomaly': record.get('ai_anomaly', False),
    }


def build_alert_message(record):
    """构建 alert 消息（仅弹窗级告警时），level=critical 对齐前端"""
    temp_level = record.get('temp_level', 'normal')
    hum_level = record.get('hum_level', 'normal')
    if temp_level != 'popup' and hum_level != 'popup':
        return None
    return {
        'type': 'alert',
        'level': 'critical',
        'timestamp': record['timestamp'],
        'temp': record['temp_filtered'],
        'hum': record['hum_filtered'],
        'temp_level': temp_level,
        'hum_level': hum_level,
        'reasons': record.get('alert_reasons', []),
        'message': f"温度{record['temp_filtered']:.1f}°C, 湿度{record['hum_filtered']:.1f}%RH",
    }


def build_status_message(generator):
    """构建 status 消息（HTTP 模式格式，与真实后端 v2 一致）"""
    return {
        'type': 'status',
        'device': 'online' if generator.is_device_online() else 'offline',
        'data_source': 'http',
        'http_api': 'ok',
        'timestamp': datetime.now().isoformat(),
    }


# ==================== FastAPI 应用 ====================
generator = MockDataGenerator()
ws_clients = set()


@asynccontextmanager
async def lifespan(app):
    # 预生成 10 条正常数据（让 AI 窗口有足够样本）
    for _ in range(10):
        generator.generate()
    print(f"\n{'='*70}")
    print(f"  Mock Server v2 启动 — 端口 {MOCK_PORT}")
    print(f"  HTTP:  http://localhost:{MOCK_PORT}")
    print(f"  WS:    ws://localhost:{MOCK_PORT}/ws")
    print(f"  接口:  /latest /history /history/range /status /health /ws")
    print(f"  v2 新增字段: alert_type / ai_score / ai_anomaly")
    print(f"  AI 模拟: 滑动窗口(z-score模拟IsolationForest), 最小训练={AI_MIN_TRAIN}")
    print(f"  数据:  每2秒自动生成，覆盖正常/标红/弹窗/突变/AI异常/离线等场景")
    print(f"  预生成 {len(generator.history)} 条历史数据")
    print(f"{'='*70}\n")

    async def data_loop():
        while True:
            await asyncio.sleep(2)
            record, desc = generator.generate()

            now_str = datetime.now().strftime('%H:%M:%S')
            if record is None:
                # 离线场景：只发 status
                print(f"[{now_str}] 场景: {desc} | 设备离线，仅推送 status")
                status_msg = build_status_message(generator)
                msg_str = json.dumps(status_msg, ensure_ascii=False)
                for ws in list(ws_clients):
                    try:
                        await ws.send_text(msg_str)
                    except Exception:
                        ws_clients.discard(ws)
                continue

            # 正常场景：发 data + alert（如有）
            ai_score_str = f"{record['ai_score']:.3f}" if record['ai_score'] is not None else "N/A"
            print(f"[{now_str}] 场景: {desc} | "
                  f"temp={record['temp_raw']}°C hum={record['hum_raw']}% "
                  f"light={record['light_raw']} | "
                  f"temp_level={record['temp_level']} hum_level={record['hum_level']} | "
                  f"alert_type={record['alert_type']} "
                  f"ai_score={ai_score_str} ai_anomaly={record['ai_anomaly']}")

            data_msg = build_data_message(record)
            alert_msg = build_alert_message(record)

            msg_str = json.dumps(data_msg, ensure_ascii=False)
            alert_str = json.dumps(alert_msg, ensure_ascii=False) if alert_msg else None

            for ws in list(ws_clients):
                try:
                    await ws.send_text(msg_str)
                    if alert_str:
                        await ws.send_text(alert_str)
                        print(f"  >>> 已推送 alert (level=critical): {alert_msg['message']}")
                except Exception:
                    ws_clients.discard(ws)

    task = asyncio.create_task(data_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/latest")
async def get_latest():
    if not generator.latest:
        return JSONResponse(status_code=404, content={"detail": "暂无数据"})
    return build_data_message(generator.latest)


@app.get("/history")
async def get_history(limit: int = Query(default=100, ge=1, le=500)):
    data = list(generator.history)[-limit:]
    return JSONResponse(content=[build_data_message(r) for r in reversed(data)])


@app.get("/history/range")
async def get_history_range(
    start: str = Query(..., description="开始时间 ISO 格式"),
    end: str = Query(..., description="结束时间 ISO 格式"),
    limit: int = Query(default=500, ge=1, le=1000),
):
    try:
        start_ts = datetime.fromisoformat(start).timestamp()
        end_ts = datetime.fromisoformat(end).timestamp()
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "时间格式错误"})
    if start_ts > end_ts:
        return JSONResponse(status_code=400, content={"detail": "开始时间不能大于结束时间"})
    result = []
    for r in reversed(list(generator.history)):
        ts = datetime.fromisoformat(r['timestamp']).timestamp()
        if start_ts <= ts <= end_ts:
            result.append(build_data_message(r))
            if len(result) >= limit:
                break
    return JSONResponse(content=result)


@app.get("/status")
async def get_status():
    return build_status_message(generator)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "device_online": generator.is_device_online(),
        "data_source": "http",
        "http_api_ok": True,
        "data_count": len(generator.history),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    print(f"[WebSocket] 客户端连接，当前共 {len(ws_clients)} 个")

    if generator.latest:
        await websocket.send_text(json.dumps(build_data_message(generator.latest), ensure_ascii=False))
    await websocket.send_text(json.dumps(build_status_message(generator), ensure_ascii=False))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(websocket)
        print(f"[WebSocket] 客户端断开，当前共 {len(ws_clients)} 个")
    except Exception:
        ws_clients.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=MOCK_PORT, access_log=False)
