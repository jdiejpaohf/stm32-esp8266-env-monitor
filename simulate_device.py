#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟设备上报数据，通过后端 /inject 接口注入，验证数据处理全链路。
不依赖 OneNET，不抢 ClientID。

用法: python simulate_device.py
"""
import json
import time
import urllib.request

BACKEND_URL = "http://localhost:8000/inject"

# 模拟数据序列：覆盖正常/标红/弹窗/突变/光照过低等场景
TEST_DATA = [
    # 1. 正常数据
    {"temp": 25.0, "humi": 50.0, "adcx": 60, "desc": "正常"},
    # 2. 正常数据（连续，用于滑动平均）
    {"temp": 26.0, "humi": 51.0, "adcx": 58, "desc": "正常"},
    # 3. 温度标红（>40）
    {"temp": 42.0, "humi": 50.0, "adcx": 60, "desc": "温度标红(>40)"},
    # 4. 温度弹窗（>50）
    {"temp": 52.0, "humi": 50.0, "adcx": 55, "desc": "温度弹窗(>50)"},
    # 5. 湿度标红（>70）
    {"temp": 25.0, "humi": 75.0, "adcx": 60, "desc": "湿度标红(>70)"},
    # 6. 湿度弹窗（>80）
    {"temp": 25.0, "humi": 85.0, "adcx": 60, "desc": "湿度弹窗(>80)"},
    # 7. 突变检测（温度从25跳到35，差值10>5）
    {"temp": 35.0, "humi": 50.0, "adcx": 60, "desc": "温度突变(25→35)"},
    # 8. 光照过低（<10，触发预留扩展点）
    {"temp": 25.0, "humi": 50.0, "adcx": 5, "desc": "光照过低(<10)"},
    # 9. OneNET dp 格式（验证 dp 解析）
    {"dp": {"temp": [{"v": 28.5}], "humi": [{"v": 55.0}], "adcx": [{"v": 70}]}, "desc": "OneNET dp 格式"},
    # 10. 正常收尾
    {"temp": 27.0, "humi": 52.0, "adcx": 62, "desc": "正常收尾"},
]


def send_one(item):
    desc = item.pop("desc", "")
    payload = json.dumps(item).encode("utf-8")
    req = urllib.request.Request(
        BACKEND_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            record = result.get("record", {})
            alert = result.get("alert")
            temp_lvl = record.get("temp_level", "?")
            hum_lvl = record.get("hum_level", "?")
            temp_anom = record.get("temp_anomaly", False)
            hum_anom = record.get("hum_anomaly", False)
            print(f"[{desc}]")
            print(f"  注入: {item}")
            print(f"  处理后: temp={record.get('temp'):.1f}°C hum={record.get('hum'):.1f}% "
                  f"light={record.get('light')} | temp_level={temp_lvl} hum_level={hum_lvl} "
                  f"| temp_anomaly={temp_anom} hum_anomaly={hum_anom}")
            if alert:
                print(f"  🚨 告警弹窗: {alert.get('message')} 原因={alert.get('reasons')}")
            print(f"  WebSocket客户端数: {result.get('websocket_clients', 0)}")
            return True
    except Exception as e:
        print(f"[{desc}] ❌ 失败: {e}")
        return False


def main():
    print(f"=== 模拟设备数据注入测试（共{len(TEST_DATA)}条） ===")
    print(f"目标: {BACKEND_URL}")
    print(f"间隔: 1.5秒/条\n")

    ok_count = 0
    for i, item in enumerate(TEST_DATA, 1):
        # 深拷贝避免 pop 影响
        send_item = {k: v for k, v in item.items()}
        print(f"--- 第{i}条 ---")
        if send_one(send_item):
            ok_count += 1
        time.sleep(1.5)

    print(f"\n=== 完成: {ok_count}/{len(TEST_DATA)} 条成功 ===")
    print("现在可以检查：")
    print("  1. 浏览器打开 http://localhost:8000/latest  看最新数据")
    print("  2. 浏览器打开 http://localhost:8000/history   看历史数据")
    print("  3. 浏览器打开 http://localhost:8000/health    看数据计数")
    print("  4. 查看 data_log.csv 文件是否有完整记录")


if __name__ == "__main__":
    main()
