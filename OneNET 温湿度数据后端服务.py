#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OneNET 温湿度+光照数据后端服务
功能：
1. 通过 paho-mqtt 订阅 OneNET 平台设备上报的 JSON 数据
2. 数据解析、滑动平均滤波、异常检测（阈值/突变/可选孤立森林）
3. 告警分级：40°C标红/50°C弹窗，70%RH标红/80%RH弹窗
4. 处理结果追加保存至 CSV 文件
5. 通过 WebSocket 分类型推送（data/alert/status），并提供 HTTP REST API 查询
6. 设备离线判定：3分钟无新数据
7. 预留光照扩展点（亮度过低触发跑马灯接口）
"""

import os
import sys
import json
import csv
import time
import ssl
import base64
import hashlib
import hmac
import threading
import asyncio
import logging
import urllib.parse
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime
from typing import Optional, List, Dict, Any, Set

# ==================== 自动安装依赖 ====================
def install_missing_packages():
    required = {
        'paho-mqtt': 'paho.mqtt.client',
        'numpy': 'numpy',
        'fastapi': 'fastapi',
        'uvicorn': 'uvicorn',
        'websockets': 'websockets',
    }
    missing = []
    for pkg, imp in required.items():
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"缺少依赖包: {missing}，正在使用清华镜像安装...")
        import subprocess
        for pkg in missing:
            cmd = [sys.executable, '-m', 'pip', 'install',
                   '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple', pkg]
            subprocess.check_call(cmd)
        print("所有依赖安装完成，请重新启动脚本。")
        sys.exit(0)

install_missing_packages()

import numpy as np
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
import uvicorn

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('service.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==================== 配置加载 ====================
class Config:
    # OneNET MQTT 连接参数
    #   经验证：OneNET 平台强制要求 ClientID == 设备名 (mqtt1)
    #   即使使用产品级 res + 产品级 access_key 签名的 token，其他 ClientID 也会 rc=4
    #   因此调试阶段需要板子和后端"错开"上线，不能同时在线
    MQTT_BROKER = os.getenv('ONENET_MQTT_BROKER', 'mqtts.heclouds.com')
    MQTT_PORT = int(os.getenv('ONENET_MQTT_PORT', '8883'))
    MQTT_USE_TLS = os.getenv('ONENET_MQTT_USE_TLS', 'true').lower() == 'true'
    MQTT_CLIENT_ID = os.getenv('ONENET_DEVICE_NAME', 'mqtt1')
    MQTT_USERNAME = os.getenv('ONENET_PRODUCT_ID', 'MC56SRi2cs')
    # 产品级 res=products/MC56SRi2cs + 产品级 access_key 签名（2026-08-24 实测唯一能过鉴权）
    MQTT_PASSWORD = os.getenv('ONENET_API_KEY',
                              'version=2018-10-31&res=products%2FMC56SRi2cs&et=2000000000&method=md5&sign=Y1j5Axa0MeTXeV568du%2BzQ%3D%3D')
    MQTT_TOPIC = os.getenv('ONENET_SUB_TOPIC',
                            '$sys/MC56SRi2cs/mqtt1/dp/post/json')

    # 数据源切换
    #   "http"  = 产品级 AccessKey + HTTP API 轮询（板子和后端同时在线，推荐）
    #   "mqtt"  = paho-mqtt 订阅（ClientID=mqtt1，和板子互踢，仅错峰调试用）
    DATA_SOURCE = os.getenv('DATA_SOURCE', 'http')

    # OneNET HTTP API 参数（已实测验证：iot-api.heclouds.com + 物模型查询接口）
    #   鉴权：version=2022-05-01, res=products/{产品ID}, method=sha1, AK=产品级 AccessKey
    HTTP_API_BASE = os.getenv('ONENET_HTTP_API_BASE', 'https://iot-api.heclouds.com')
    HTTP_API_PATH = os.getenv(
        'ONENET_HTTP_API_PATH',
        '/thingmodel/query-device-property'
    )
    HTTP_PRODUCT_ID = os.getenv('ONENET_HTTP_PRODUCT_ID', 'MC56SRi2cs')
    HTTP_DEVICE_NAME = os.getenv('ONENET_HTTP_DEVICE_NAME', 'mqtt1')
    HTTP_PRODUCT_ACCESS_KEY = os.getenv(
        'ONENET_HTTP_AK',
        'd0PnFW15K+0t+7W9U2lvP19BNzPV1Z+NUbEfqwOh/eM='
    )
    HTTP_POLL_INTERVAL = float(os.getenv('HTTP_POLL_INTERVAL', '3.0'))  # 秒，默认3秒
    HTTP_DEDUP_CACHE_SIZE = int(os.getenv('HTTP_DEDUP_CACHE_SIZE', '100'))
    HTTP_REQUEST_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '15.0'))
    # HTTP 轮询去重策略：
    #   "timestamp"（默认，推荐）：按板子上报的 time 毫秒时间戳去重，不会漏值、稳定可靠
    #   "content_hash"：按 temp|humi|adcx 拼串 MD5 去重，环境完全稳定时会误吞重复值（但能区分同时间戳的不同值）
    HTTP_DEDUP_METHOD = os.getenv('HTTP_DEDUP_METHOD', 'timestamp')

    # 数据字段映射（OneNET 平台 JSON 键名）
    KEY_TEMP = os.getenv('KEY_TEMP', 'temp')
    KEY_HUM = os.getenv('KEY_HUM', 'humi')
    KEY_LIGHT = os.getenv('KEY_LIGHT', 'adcx')
    KEY_TIME = os.getenv('KEY_TIME', 'time')

    # 数据处理参数
    FILTER_WINDOW = int(os.getenv('FILTER_WINDOW', '5'))
    TEMP_MIN = float(os.getenv('TEMP_MIN', '0.0'))
    TEMP_MAX = float(os.getenv('TEMP_MAX', '100.0'))
    HUM_MIN = float(os.getenv('HUM_MIN', '0.0'))
    HUM_MAX = float(os.getenv('HUM_MAX', '100.0'))
    LIGHT_MIN = int(os.getenv('LIGHT_MIN', '0'))
    LIGHT_MAX = int(os.getenv('LIGHT_MAX', '100'))

    # 突变检测（相邻两点差值）
    CHANGE_THRESHOLD = float(os.getenv('CHANGE_THRESHOLD', '5.0'))

    # 告警分级
    TEMP_RED_LINE = float(os.getenv('TEMP_RED_LINE', '40.0'))
    TEMP_POPUP_LINE = float(os.getenv('TEMP_POPUP_LINE', '50.0'))
    HUM_RED_LINE = float(os.getenv('HUM_RED_LINE', '70.0'))
    HUM_POPUP_LINE = float(os.getenv('HUM_POPUP_LINE', '80.0'))

    # 光照扩展
    LIGHT_LOW_THRESHOLD = int(os.getenv('LIGHT_LOW_THRESHOLD', '10'))

    # 设备离线判定（秒）
    DEVICE_OFFLINE_SECONDS = int(os.getenv('DEVICE_OFFLINE_SECONDS', '180'))

    # 孤立森林（初始关闭）
    IFOREST_ENABLE = os.getenv('IFOREST_ENABLE', 'false').lower() == 'true'
    IFOREST_CONTAMINATION = float(os.getenv('IFOREST_CONTAMINATION', '0.1'))
    IFOREST_TRAIN_SIZE = int(os.getenv('IFOREST_TRAIN_SIZE', '100'))

    # 服务配置
    HTTP_HOST = os.getenv('HTTP_HOST', '0.0.0.0')
    HTTP_PORT = int(os.getenv('HTTP_PORT', '8000'))
    CSV_FILE = os.getenv('CSV_FILE', 'data_log.csv')
    MAX_HISTORY = int(os.getenv('MAX_HISTORY', '2000'))
    MAX_HISTORY_QUERY = int(os.getenv('MAX_HISTORY_QUERY', '500'))

config = Config()


# ==================== 告警分级判定 ====================
def get_alert_levels(temp: float, hum: float) -> Dict[str, str]:
    """
    返回各指标的告警级别：normal / red / popup
    - normal: 正常
    - red: 标红（超红线）
    - popup: 弹窗（超弹窗线）
    """
    temp_level = 'normal'
    hum_level = 'normal'

    # 温度：40标红, 50弹窗
    if temp >= config.TEMP_POPUP_LINE or temp < config.TEMP_MIN:
        temp_level = 'popup'
    elif temp >= config.TEMP_RED_LINE or temp < config.TEMP_MIN + 5:
        temp_level = 'red'

    # 湿度：70标红, 80弹窗
    if hum >= config.HUM_POPUP_LINE or hum < config.HUM_MIN:
        hum_level = 'popup'
    elif hum >= config.HUM_RED_LINE or hum < config.HUM_MIN + 10:
        hum_level = 'red'

    return {'temp': temp_level, 'hum': hum_level}


def get_alert_reasons(temp: float, hum: float,
                      temp_anomaly: bool, hum_anomaly: bool) -> List[str]:
    """返回告警原因列表"""
    reasons = []
    if temp_anomaly:
        if temp > config.TEMP_MAX or temp < config.TEMP_MIN:
            reasons.append('温度超限')
        else:
            reasons.append('温度突变')
    if hum_anomaly:
        if hum > config.HUM_MAX or hum < config.HUM_MIN:
            reasons.append('湿度超限')
        else:
            reasons.append('湿度突变')
    return reasons


# ==================== 数据处理核心 ====================
class AnomalyDetector:
    """异常检测器：阈值 + 相邻差值突变 + 可选孤立森林"""
    def __init__(self):
        self.iforest = None
        self.trained = False
        self.buffer = []
        self.last_values = {}

    def threshold_check(self, temp: float, hum: float) -> Dict[str, bool]:
        temp_abnormal = (temp < config.TEMP_MIN) or (temp > config.TEMP_MAX)
        hum_abnormal = (hum < config.HUM_MIN) or (hum > config.HUM_MAX)
        return {'temp': temp_abnormal, 'hum': hum_abnormal}

    def change_check(self, temp: float, hum: float) -> Dict[str, bool]:
        """突变检测：相邻两点差值"""
        temp_abnormal = False
        hum_abnormal = False
        if self.last_values:
            last_temp = self.last_values.get('temp', temp)
            last_hum = self.last_values.get('hum', hum)
            if abs(temp - last_temp) > config.CHANGE_THRESHOLD:
                temp_abnormal = True
            if abs(hum - last_hum) > config.CHANGE_THRESHOLD:
                hum_abnormal = True
        self.last_values = {'temp': temp, 'hum': hum}
        return {'temp': temp_abnormal, 'hum': hum_abnormal}

    def iforest_check(self, temp: float, hum: float) -> Dict[str, bool]:
        if not config.IFOREST_ENABLE or not self.trained or self.iforest is None:
            return {'temp': False, 'hum': False}
        X = np.array([[temp, hum]])
        pred = self.iforest.predict(X)
        abnormal = (pred[0] == -1)
        return {'temp': abnormal, 'hum': abnormal}

    def train_iforest(self, data: List[Dict[str, float]]):
        if not config.IFOREST_ENABLE:
            return
        if len(data) < 2:
            return
        X = np.array([[d['temp'], d['hum']] for d in data])
        try:
            from sklearn.ensemble import IsolationForest
            self.iforest = IsolationForest(
                contamination=config.IFOREST_CONTAMINATION,
                random_state=42
            )
            self.iforest.fit(X)
            self.trained = True
            logger.info(f"孤立森林训练完成，使用 {len(X)} 条数据")
        except Exception as e:
            logger.error(f"孤立森林训练失败: {e}")

    def detect(self, temp: float, hum: float) -> Dict[str, bool]:
        th = self.threshold_check(temp, hum)
        ch = self.change_check(temp, hum)
        iforest = self.iforest_check(temp, hum)
        temp_anomaly = th['temp'] or ch['temp'] or iforest['temp']
        hum_anomaly = th['hum'] or ch['hum'] or iforest['hum']
        return {'temp': temp_anomaly, 'hum': hum_anomaly}

    def feed_for_training(self, temp: float, hum: float):
        if not config.IFOREST_ENABLE or self.trained:
            return
        self.buffer.append({'temp': temp, 'hum': hum})
        if len(self.buffer) >= config.IFOREST_TRAIN_SIZE:
            self.train_iforest(self.buffer)
            self.buffer = []


class DataProcessor:
    def __init__(self):
        self.filter_window = deque(maxlen=config.FILTER_WINDOW)
        self.history = deque(maxlen=config.MAX_HISTORY)
        self.latest = None
        self.lock = threading.Lock()
        self.anomaly_detector = AnomalyDetector()
        self.last_data_time: Optional[float] = None
        self._init_csv()

    def _init_csv(self):
        if not os.path.exists(config.CSV_FILE):
            with open(config.CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'temp_raw', 'hum_raw', 'light_raw',
                    'temp_filtered', 'hum_filtered', 'light_filtered',
                    'temp_anomaly', 'hum_anomaly',
                    'temp_level', 'hum_level'
                ])

    def _write_csv(self, record: Dict[str, Any]):
        with open(config.CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                record['timestamp'],
                record['temp_raw'],
                record['hum_raw'],
                record['light_raw'],
                record['temp_filtered'],
                record['hum_filtered'],
                record['light_filtered'],
                record['temp_anomaly'],
                record['hum_anomaly'],
                record.get('temp_level', 'normal'),
                record.get('hum_level', 'normal'),
            ])

    def process(self, raw_data: Dict[str, float],
                device_time: Optional[str] = None) -> Optional[Dict]:
        temp_raw = raw_data.get(config.KEY_TEMP)
        hum_raw = raw_data.get(config.KEY_HUM)
        light_raw = raw_data.get(config.KEY_LIGHT)

        if temp_raw is None or hum_raw is None:
            logger.warning("数据缺少温度或湿度字段，跳过")
            return None

        if not isinstance(temp_raw, (int, float)) or not isinstance(hum_raw, (int, float)):
            logger.warning(f"数据类型异常: temp={temp_raw}({type(temp_raw)}), hum={hum_raw}({type(hum_raw)})")
            return None

        temp_raw = float(temp_raw)
        hum_raw = float(hum_raw)
        light_val = int(light_raw) if light_raw is not None else 0

        if device_time:
            try:
                ts = datetime.fromisoformat(device_time.replace('Z', '+00:00'))
            except Exception:
                ts = datetime.now()
        else:
            ts = datetime.now()
        timestamp_str = ts.isoformat()
        timestamp_float = ts.timestamp()

        self.last_data_time = timestamp_float

        with self.lock:
            self.filter_window.append((temp_raw, hum_raw, light_val))
            temps = [t for t, h, l in self.filter_window]
            hums = [h for t, h, l in self.filter_window]
            lights = [l for t, h, l in self.filter_window]
            temp_filtered = float(np.mean(temps))
            hum_filtered = float(np.mean(hums))
            light_filtered = int(round(np.mean(lights)))

            anomaly = self.anomaly_detector.detect(temp_raw, hum_raw)
            self.anomaly_detector.feed_for_training(temp_raw, hum_raw)

            alert_levels = get_alert_levels(temp_raw, hum_raw)
            alert_reasons = get_alert_reasons(temp_raw, hum_raw,
                                              anomaly['temp'], anomaly['hum'])

            record = {
                'timestamp': timestamp_str,
                'temp_raw': temp_raw,
                'hum_raw': hum_raw,
                'light_raw': light_val,
                'temp_filtered': round(temp_filtered, 2),
                'hum_filtered': round(hum_filtered, 2),
                'light_filtered': light_filtered,
                'temp_anomaly': anomaly['temp'],
                'hum_anomaly': anomaly['hum'],
                'temp_level': alert_levels['temp'],
                'hum_level': alert_levels['hum'],
                'alert_reasons': alert_reasons,
            }

            self.history.append(record)
            self.latest = record
            self._write_csv(record)

            logger.info(
                f"数据: temp={temp_raw}->{temp_filtered:.1f}°C "
                f"hum={hum_raw}->{hum_filtered:.1f}% "
                f"light={light_val}->{light_filtered} "
                f"告警级别: temp={alert_levels['temp']} hum={alert_levels['hum']} "
                f"原因: {alert_reasons}"
            )
            return record

    def is_device_online(self) -> bool:
        if self.last_data_time is None:
            return False
        return (time.time() - self.last_data_time) < config.DEVICE_OFFLINE_SECONDS

    def get_latest(self) -> Optional[Dict]:
        with self.lock:
            return self.latest

    def get_history(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            return list(self.history)[-limit:]

    def get_history_range(self, start_ts: float, end_ts: float,
                          limit: int = 500) -> List[Dict]:
        with self.lock:
            result = []
            for r in self.history:
                try:
                    ts = datetime.fromisoformat(r['timestamp']).timestamp()
                    if start_ts <= ts <= end_ts:
                        result.append(r)
                except Exception:
                    continue
            return result[-limit:]


# ==================== WebSocket 连接管理器 ====================
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("WebSocket 客户端连接，当前连接数: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info("WebSocket 客户端断开，当前连接数: %d", len(self.active_connections))

    async def broadcast(self, message: Dict):
        if not self.active_connections:
            return
        data = json.dumps(message, ensure_ascii=False)
        dead = []
        for conn in list(self.active_connections):
            try:
                await conn.send_text(data)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.active_connections.discard(conn)


# ==================== FastAPI 应用 ====================
app = FastAPI(title="OneNET 温湿度+光照数据后端服务")
manager = ConnectionManager()
processor = DataProcessor()
mqtt_subscriber = None
http_poller = None
_main_event_loop = None


@app.on_event("startup")
async def startup_event():
    global mqtt_subscriber, http_poller, _main_event_loop
    _main_event_loop = asyncio.get_running_loop()

    source = config.DATA_SOURCE.lower()
    if source == 'http':
        http_poller = HttpPoller(processor, manager, _main_event_loop)
        threading.Thread(target=http_poller.start, daemon=True).start()
        logger.info("数据源模式: HTTP API 轮询")
    elif source == 'mqtt':
        mqtt_subscriber = MqttSubscriber(processor, manager, _main_event_loop)
        threading.Thread(target=mqtt_subscriber.start, daemon=True).start()
        logger.info("数据源模式: MQTT 订阅")
    else:
        logger.error(f"未知 DATA_SOURCE={source}，仅支持 'http' 或 'mqtt'")
    logger.info("后端服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    if mqtt_subscriber:
        mqtt_subscriber.stop()
    if http_poller:
        http_poller.stop()


# ==================== WebSocket 端点 ====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # 先发最新数据
        latest = processor.get_latest()
        if latest:
            data_msg = build_data_message(latest)
            await websocket.send_text(json.dumps(data_msg, ensure_ascii=False))

        # 再发设备状态
        status_msg = build_status_message()
        await websocket.send_text(json.dumps(status_msg, ensure_ascii=False))

        # 持续接收心跳
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket 异常: %s", e)
        manager.disconnect(websocket)


def build_data_message(record: Dict) -> Dict:
    """构建 data 类型消息"""
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
    }


def build_alert_message(record: Dict) -> Optional[Dict]:
    """构建 alert 类型消息（仅当有弹窗级告警时）"""
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


def build_status_message() -> Dict:
    """构建 status 类型消息（兼容 MQTT / HTTP 两种数据源）"""
    source = config.DATA_SOURCE.lower()
    msg = {
        'type': 'status',
        'device': 'online' if processor.is_device_online() else 'offline',
        'data_source': source,
        'timestamp': datetime.now().isoformat(),
    }
    if source == 'mqtt':
        msg['mqtt'] = 'connected' if (mqtt_subscriber and mqtt_subscriber.is_connected()) else 'disconnected'
    elif source == 'http':
        msg['http_api'] = 'ok' if (http_poller and http_poller.is_api_ok()) else 'error'
    return msg


# ==================== HTTP API ====================
@app.get("/latest", response_model=Dict)
async def get_latest():
    data = processor.get_latest()
    if not data:
        raise HTTPException(status_code=404, detail="暂无数据")
    return build_data_message(data)


@app.get("/history")
async def get_history(limit: int = Query(default=100, ge=1, le=500)):
    data = processor.get_history(limit)
    result = [build_data_message(r) for r in data]
    return JSONResponse(content=result)


@app.get("/history/range")
async def get_history_range(
    start: str = Query(..., description="开始时间 ISO 格式，如 2026-08-23T00:00:00"),
    end: str = Query(..., description="结束时间 ISO 格式"),
    limit: int = Query(default=500, ge=1, le=1000),
):
    try:
        start_ts = datetime.fromisoformat(start).timestamp()
        end_ts = datetime.fromisoformat(end).timestamp()
    except ValueError:
        raise HTTPException(status_code=400, detail="时间格式错误，请使用 ISO 格式")
    if start_ts > end_ts:
        raise HTTPException(status_code=400, detail="开始时间不能大于结束时间")
    data = processor.get_history_range(start_ts, end_ts, limit)
    result = [build_data_message(r) for r in data]
    return JSONResponse(content=result)


@app.get("/status")
async def get_status():
    return build_status_message()


@app.get("/health")
async def health_check():
    source = config.DATA_SOURCE.lower()
    resp = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "device_online": processor.is_device_online(),
        "data_source": source,
        "data_count": len(processor.history),
    }
    if source == 'mqtt':
        resp["mqtt_connected"] = mqtt_subscriber.is_connected() if mqtt_subscriber else False
    elif source == 'http':
        resp["http_api_ok"] = http_poller.is_api_ok() if http_poller else False
    return resp


# ==================== MQTT 客户端 ====================
class MqttSubscriber:
    def __init__(self, processor_ref: DataProcessor, ws_mgr: ConnectionManager, event_loop):
        self.processor = processor_ref
        self.ws_manager = ws_mgr
        self._event_loop = event_loop
        self._connected = False
        self.client = mqtt.Client(client_id=config.MQTT_CLIENT_ID)
        self.client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)
        if config.MQTT_USE_TLS:
            self.client.tls_set(cert_reqs=ssl.CERT_NONE)
            self.client.tls_insecure_set(True)
        self.client.reconnect_delay_set(min_delay=2, max_delay=30)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def is_connected(self) -> bool:
        return self._connected

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("MQTT 连接成功，订阅主题: %s", config.MQTT_TOPIC)
            client.subscribe(config.MQTT_TOPIC, qos=1)
            status_msg = build_status_message()
            asyncio.run_coroutine_threadsafe(
                self.ws_manager.broadcast(status_msg),
                self._event_loop
            )
        else:
            self._connected = False
            logger.error("MQTT 连接失败，返回码: %d", rc)

    def on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            logger.warning("MQTT 意外断开 (rc=%d)，loop_start 将自动重连...", rc)
        else:
            logger.info("MQTT 正常断开")
        status_msg = build_status_message()
        try:
            asyncio.run_coroutine_threadsafe(
                self.ws_manager.broadcast(status_msg),
                self._event_loop
            )
        except Exception:
            pass

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode('utf-8')
            logger.debug("收到 MQTT 消息: %s", payload[:200])
            data = json.loads(payload)

            # OneNET 转发格式: {"dp": {"temp": [{"v":25.5,"t":...}], "humi":[...]}}
            raw = {}
            if 'dp' in data:
                dp = data['dp']
                for key_name in [config.KEY_TEMP, config.KEY_HUM, config.KEY_LIGHT]:
                    if key_name in dp and isinstance(dp[key_name], list) and len(dp[key_name]) > 0:
                        val = dp[key_name][0].get('v')
                        if val is not None:
                            raw[key_name] = val

            # 兼容简单格式: {"temp":25.5, "humi":60}
            if config.KEY_TEMP not in raw and config.KEY_TEMP in data:
                raw[config.KEY_TEMP] = data[config.KEY_TEMP]
            if config.KEY_HUM not in raw and config.KEY_HUM in data:
                raw[config.KEY_HUM] = data[config.KEY_HUM]
            if config.KEY_LIGHT not in raw and config.KEY_LIGHT in data:
                raw[config.KEY_LIGHT] = data[config.KEY_LIGHT]

            if config.KEY_TEMP not in raw or config.KEY_HUM not in raw:
                logger.warning("无法从消息中解析出温湿度，跳过。原始: %s", payload[:200])
                return

            # 获取设备时间
            device_time = None
            if config.KEY_TIME in data:
                device_time = str(data[config.KEY_TIME])
            elif 'dp' in data:
                dp = data['dp']
                for key_name in [config.KEY_TEMP, config.KEY_HUM]:
                    if key_name in dp and isinstance(dp[key_name], list) and len(dp[key_name]) > 0:
                        t_val = dp[key_name][0].get('t')
                        if t_val:
                            try:
                                device_time = datetime.fromtimestamp(t_val / 1000).isoformat()
                            except Exception:
                                pass
                            break

            record = self.processor.process(raw, device_time)
            if record:
                data_msg = build_data_message(record)
                asyncio.run_coroutine_threadsafe(
                    self.ws_manager.broadcast(data_msg),
                    self._event_loop
                )
                alert_msg = build_alert_message(record)
                if alert_msg:
                    asyncio.run_coroutine_threadsafe(
                        self.ws_manager.broadcast(alert_msg),
                        self._event_loop
                    )
        except json.JSONDecodeError as e:
            logger.error("JSON 解析失败: %s", e)
        except Exception as e:
            logger.error("处理消息异常: %s", e, exc_info=True)

    def start(self):
        try:
            self.client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
            self.client.loop_start()
            logger.info("MQTT 客户端已启动 (broker=%s:%s, TLS=%s)",
                        config.MQTT_BROKER, config.MQTT_PORT, config.MQTT_USE_TLS)
        except Exception as e:
            logger.error("MQTT 初始连接失败: %s（后台将自动重连）", e)
            try:
                self.client.loop_start()
            except Exception as e2:
                logger.error("MQTT loop_start 失败: %s", e2)

    def stop(self):
        self._connected = False
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        logger.info("MQTT 客户端已停止")


# ==================== HTTP API 轮询器（板子和后端可同时在线） ====================
class HttpPoller:
    """
    定期轮询 OneNET 新版 HTTP API 获取设备最新属性。
    - 鉴权：产品级 AccessKey + version=2022-05-01 + sha1（官方文档 format）
    - 接口：GET {BASE}{PATH}?product_id=..&device_name=..
    - 响应格式：{"code":0,"data":[{"identifier":"temp","value":"29.300000","time":1787...120}, ...]}
    - 去重：按 temp|humi|adcx 字符串算 MD5，缓存最近 N 个哈希（用户选择）
    """
    def __init__(self, processor_ref: DataProcessor, ws_mgr: ConnectionManager, event_loop):
        self.processor = processor_ref
        self.ws_manager = ws_mgr
        self._event_loop = event_loop
        self._stop_event = threading.Event()
        self._thread = None
        self._api_ok = False
        self._dedup_cache = deque(maxlen=config.HTTP_DEDUP_CACHE_SIZE)
        self._token = None
        self._token_expire_at = 0
        self._last_status_sent = 0.0
        self._last_api_ok_value = None  # 用于检测状态变化时广播

    def is_api_ok(self) -> bool:
        return self._api_ok

    # ---------- Token 生成（按官方安全鉴权文档） ----------
    def _generate_token(self) -> str:
        """
        文档: https://iot.10086.cn/doc/aiot/fuse/detail/1464
          sign_string = et + "\n" + method + "\n" + res + "\n" + version
          version=2022-05-01, method=sha1
          res=products/{产品ID}
          key=base64decode(产品级 AccessKey)
        """
        version = "2022-05-01"
        method = "sha1"
        res = f"products/{config.HTTP_PRODUCT_ID}"
        et = str(int(time.time()) + 3600 * 24 * 365)  # 1 年过期
        key = base64.b64decode(config.HTTP_PRODUCT_ACCESS_KEY)
        org = et + "\n" + method + "\n" + res + "\n" + version
        sign_b = hmac.new(key=key, msg=org.encode(), digestmod=hashlib.sha1)
        sign = base64.b64encode(sign_b.digest()).decode()
        sign = urllib.parse.quote(sign, safe="")
        res_enc = urllib.parse.quote(res, safe="")
        token = f"version={version}&res={res_enc}&et={et}&method={method}&sign={sign}"
        self._token = token
        self._token_expire_at = int(et) - 3600 * 24  # 提前 1 天刷新
        return token

    def _get_token(self) -> str:
        if not self._token or time.time() > self._token_expire_at:
            return self._generate_token()
        return self._token

    # ---------- 去重（timestamp 或 content_hash MD5） ----------
    def _is_duplicate(self, raw: Dict[str, float],
                      device_time_ms: Optional[int]) -> bool:
        """
        用户选择（默认推荐）：按板子上报的 time 毫秒时间戳去重
          - 不会漏值（每一批上报 time_ms 唯一）
          - 稳定可靠（板子同一批上报 3 个字段 time_ms 完全相同）
        可选：按内容哈希（temp|humi|adcx 拼串 MD5），环境完全稳定时会误吞
        """
        mode = config.HTTP_DEDUP_METHOD.lower()

        # ---- timestamp 模式（默认）----
        if mode == 'timestamp':
            if device_time_ms is None:
                # API 没返回时间戳时降级为 content_hash，避免一直重复/一直不重复
                mode = 'content_hash'
            else:
                if device_time_ms in self._dedup_cache:
                    return True
                self._dedup_cache.append(device_time_ms)
                return False

        # ---- content_hash 模式 ----
        t = raw.get(config.KEY_TEMP, '')
        h = raw.get(config.KEY_HUM, '')
        l = raw.get(config.KEY_LIGHT, '')
        key = f"{t}|{h}|{l}"
        digest = hashlib.md5(key.encode()).hexdigest()
        if digest in self._dedup_cache:
            return True
        self._dedup_cache.append(digest)
        return False

    # ---------- 单次 API 调用 ----------
    def _fetch_once(self):
        """返回 (raw_data_dict, device_time_ms)；失败返回 (None, None)"""
        try:
            params = urllib.parse.urlencode({
                'product_id': config.HTTP_PRODUCT_ID,
                'device_name': config.HTTP_DEVICE_NAME,
            })
            url = f"{config.HTTP_API_BASE}{config.HTTP_API_PATH}?{params}"

            req = urllib.request.Request(url)
            token = self._get_token()
            req.add_header("authorization", token)
            req.add_header("Authorization", token)

            with urllib.request.urlopen(req, timeout=config.HTTP_REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)

            code = data.get("code", data.get("errno", -1))
            if code not in (0, "0"):
                msg = data.get("error", data.get("msg", str(data)))
                logger.error(f"OneNET API 返回错误: code={code} msg={msg[:120]}")
                self._api_ok = False
                return None, None

            items = data.get("data", [])
            if not isinstance(items, list) or len(items) == 0:
                logger.debug("OneNET API data 为空（设备刚启动或还没上报）")
                self._api_ok = True
                return None, None

            raw: Dict[str, float] = {}
            device_time_ms: Optional[int] = None
            for item in items:
                identifier = item.get("identifier")
                value_str = item.get("value")
                t_ms = item.get("time")
                if identifier == config.KEY_TEMP and value_str is not None:
                    try: raw[config.KEY_TEMP] = float(value_str)
                    except (ValueError, TypeError): pass
                elif identifier == config.KEY_HUM and value_str is not None:
                    try: raw[config.KEY_HUM] = float(value_str)
                    except (ValueError, TypeError): pass
                elif identifier == config.KEY_LIGHT and value_str is not None:
                    try: raw[config.KEY_LIGHT] = int(float(value_str))
                    except (ValueError, TypeError): pass
                if t_ms and device_time_ms is None:
                    try: device_time_ms = int(t_ms)
                    except (ValueError, TypeError): pass

            self._api_ok = True

            if config.KEY_TEMP not in raw or config.KEY_HUM not in raw:
                logger.debug(f"API 返回缺少温湿度字段，已解析 raw={raw}")
                return None, device_time_ms

            return raw, device_time_ms

        except urllib.error.HTTPError as e:
            self._api_ok = False
            body = ""
            try: body = e.read().decode("utf-8", errors="replace")[:150]
            except Exception: pass
            logger.warning(f"OneNET HTTP {e.code} {e.reason} {body}")
            return None, None
        except Exception as e:
            self._api_ok = False
            logger.warning(f"OneNET HTTP 异常: {type(e).__name__}: {e}")
            return None, None

    # ---------- 跨线程广播 ----------
    def _broadcast(self, coro):
        try:
            asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        except Exception as e:
            logger.error(f"广播失败: {e}")

    def _broadcast_if_status_changed(self):
        """设备上线/离线、API OK/Error 状态变化时广播 status"""
        now = time.time()
        api_changed = (self._last_api_ok_value != self._api_ok)
        # 每 30 秒保底发一次 status，防止前端连上后等太久
        periodic = (now - self._last_status_sent) > 30.0
        if api_changed or periodic:
            status = build_status_message()
            self._broadcast(self.ws_manager.broadcast(status))
            self._last_api_ok_value = self._api_ok
            self._last_status_sent = now

    # ---------- 主循环 ----------
    def _run_loop(self):
        logger.info(
            "HttpPoller 启动: base=%s interval=%ss prod=%s dev=%s",
            config.HTTP_API_BASE,
            config.HTTP_POLL_INTERVAL,
            config.HTTP_PRODUCT_ID,
            config.HTTP_DEVICE_NAME,
        )
        # 启动时立即广播状态
        self._broadcast(self.ws_manager.broadcast(build_status_message()))
        self._last_status_sent = time.time()

        while not self._stop_event.is_set():
            start_t = time.time()

            raw, device_time_ms = self._fetch_once()
            if raw:
                if not self._is_duplicate(raw, device_time_ms):
                    # 毫秒时间戳转 ISO 格式供 DataProcessor 使用
                    device_time_iso = None
                    if device_time_ms:
                        try:
                            device_time_iso = datetime.fromtimestamp(device_time_ms / 1000).isoformat()
                        except Exception:
                            device_time_iso = None
                    record = self.processor.process(raw, device_time_iso)
                    if record:
                        self._broadcast(self.ws_manager.broadcast(build_data_message(record)))
                        alert = build_alert_message(record)
                        if alert:
                            self._broadcast(self.ws_manager.broadcast(alert))

            self._broadcast_if_status_changed()

            elapsed = time.time() - start_t
            sleep_sec = max(0.05, config.HTTP_POLL_INTERVAL - elapsed)
            if self._stop_event.wait(timeout=sleep_sec):
                break

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            try:
                self._thread.join(timeout=3)
            except Exception:
                pass
        logger.info("HttpPoller 已停止")


# ==================== 主程序 ====================
def main():
    logger.info("启动 OneNET 数据后端服务...")
    logger.info(f"监听地址: {config.HTTP_HOST}:{config.HTTP_PORT}")
    logger.info(f"CSV 日志文件: {config.CSV_FILE}")
    logger.info(f"数据源模式: DATA_SOURCE={config.DATA_SOURCE}")
    source = config.DATA_SOURCE.lower()
    if source == 'mqtt':
        logger.info(f"Broker: {config.MQTT_BROKER}:{config.MQTT_PORT} (TLS={config.MQTT_USE_TLS})")
        logger.info(f"ClientID: {config.MQTT_CLIENT_ID}")
        logger.info(f"订阅主题: {config.MQTT_TOPIC}")
    elif source == 'http':
        logger.info(f"OneNET API: {config.HTTP_API_BASE}{config.HTTP_API_PATH}")
        logger.info(f"轮询间隔: {config.HTTP_POLL_INTERVAL}s")
        logger.info(f"产品/设备: {config.HTTP_PRODUCT_ID}/{config.HTTP_DEVICE_NAME}")
        dedup = config.HTTP_DEDUP_METHOD.lower()
        if dedup == 'timestamp':
            logger.info(f"去重策略: 板子上报time毫秒时间戳（默认推荐，不会漏值），缓存 {config.HTTP_DEDUP_CACHE_SIZE} 条")
        else:
            logger.info(f"去重策略: 内容哈希 MD5，缓存 {config.HTTP_DEDUP_CACHE_SIZE} 条（环境完全稳定时可能漏值）")
    logger.info(f"孤立森林: {'开启' if config.IFOREST_ENABLE else '关闭'}")
    logger.info(f"告警阈值: 温度 {config.TEMP_RED_LINE}°C(标红)/{config.TEMP_POPUP_LINE}°C(弹窗),  "
                f"湿度 {config.HUM_RED_LINE}%(标红)/{config.HUM_POPUP_LINE}%(弹窗)")
    logger.info(f"设备离线判定: {config.DEVICE_OFFLINE_SECONDS}s 无新数据")

    uvicorn.run(
        app,
        host=config.HTTP_HOST,
        port=config.HTTP_PORT,
        log_level="info",
        access_log=False
    )


if __name__ == "__main__":
    main()

