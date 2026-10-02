#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按照官方文档 https://iot.10086.cn/doc/aiot/fuse/detail/1464 实现：
- version=2022-05-01
- method=sha1
- res: userid/{数字ID} 或 products/{产品ID}
- sign_string = et + '\n' + method + '\n' + res + '\n' + version
"""
import base64, hmac, hashlib, json, urllib.parse, urllib.request, urllib.error, time

USER_ID = "1491570"
PRODUCT_ID = "MC56SRi2cs"
DEVICE_NAME = "mqtt1"
# 新重置后的用户级 AccessKey
USER_ACCESS_KEY = "OWUyZjc4ZDc5MDFlNDUzMDkzZmY3NzhkOTM0MGQ3Njc="
# 产品级 AccessKey
PRODUCT_ACCESS_KEY = "d0PnFW15K+0t+7W9U2lvP19BNzPV1Z+NUbEfqwOh/eM="

def generate_token(res, access_key, et=str(int(time.time()) + 3600*24*365)):
    """按文档：version=2022-05-01, method=sha1"""
    version = "2022-05-01"
    method = "sha1"
    key = base64.b64decode(access_key)
    org = et + "\n" + method + "\n" + res + "\n" + version
    sign_b = hmac.new(key=key, msg=org.encode(), digestmod=hashlib.sha1)
    sign = base64.b64encode(sign_b.digest()).decode()
    sign = urllib.parse.quote(sign, safe="")
    res_enc = urllib.parse.quote(res, safe="")
    return f"version={version}&res={res_enc}&et={et}&method={method}&sign={sign}"

# 三种鉴权方式
TOKENS = [
    ("用户鉴权(res=userid/{数字ID})", f"userid/{USER_ID}", USER_ACCESS_KEY),
    ("产品鉴权(res=products/{产品ID})", f"products/{PRODUCT_ID}", PRODUCT_ACCESS_KEY),
]

# 多域名 + 多 API 路径
API_CALLS = [
    # 设备属性查询（物模型）
    ("https://iot-api.heclouds.com", f"/thingmodel/query-device-property?product_id={PRODUCT_ID}&device_name={DEVICE_NAME}", "新版-设备属性"),
    # 设备列表
    ("https://iot-api.heclouds.com", f"/devices?product_id={PRODUCT_ID}", "新版-设备列表"),
    # 设备数据点历史
    ("https://iot-api.heclouds.com", f"/thingmodel/query-device-property-ts?product_id={PRODUCT_ID}&device_name={DEVICE_NAME}&datastream_id=temp&limit=10", "新版-历史数据点(猜测)"),
    # DMP 域名（文档提到 DMP token工具）
    ("https://dmp.api.cmaiot.cn", f"/dmp/v1/datapoint/current-datapoints?product_id={PRODUCT_ID}&device_name={DEVICE_NAME}", "DMP-最新数据点"),
    ("https://dmp.api.cmaiot.cn", f"/dmp/v1/datapoint/history-datapoints?product_id={PRODUCT_ID}&device_name={DEVICE_NAME}&limit=10", "DMP-历史数据点"),
    # 旧版 api.heclouds.com (Authorization头)
    ("https://api.heclouds.com", f"/devices?product_id={PRODUCT_ID}", "旧版-设备列表"),
]

for token_desc, res, ak in TOKENS:
    token = generate_token(res, ak)
    ak_mask = ak[:4] + "..." + ak[-4:]
    print(f"\n{'='*80}")
    print(f"🔑 {token_desc}")
    print(f"   res = {res}")
    print(f"   ak  = {ak_mask}")
    print(f"   token(截前90): {token[:90]}...")
    print(f"{'='*80}")

    for base_url, path, desc in API_CALLS:
        url = base_url + path
        req = urllib.request.Request(url)
        # 文档 Header 名: authorization
        req.add_header("authorization", token)
        # 有些文档用 Authorization
        req.add_header("Authorization", token)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                    err = data.get("errno", data.get("code", "?"))
                    msg = data.get("error", data.get("msg", ""))
                    if err in (0, "0"):
                        print(f"  ✅ [{base_url.replace('https://','')[:25]}] {desc}")
                        print(f"     {json.dumps(data, ensure_ascii=False, indent=2)[:900]}")
                    else:
                        print(f"  ❌ [{base_url.replace('https://','')[:25]}] {desc}: errno={err} {msg[:100]}")
                except:
                    print(f"  HTTP {resp.getcode()} {desc}: {body[:200]}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"  HTTP {e.code} [{base_url.replace('https://','')[:25]}] {desc}: {body[:150]}")
        except Exception as e:
            print(f"  ❌ [{base_url.replace('https://','')[:25]}] {desc}: {type(e).__name__} {str(e)[:80]}")

print("\n=== 完成 ===")
