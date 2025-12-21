import os
import base64
import json
import requests
from playwright.sync_api import sync_playwright

# 从环境变量读取密钥
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN")

if not DASHSCOPE_API_KEY or not PUSHPLUS_TOKEN:
    raise EnvironmentError("请设置 DASHSCOPE_API_KEY 和 PUSHPLUS_TOKEN 环境变量")

SCREENSHOT_PATH = "/tmp/screenshot.png"
CMC_URL = "https://coinmarketcap.com/etf/bitcoin/"


def take_screenshot():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu"
        ])
        page = browser.new_page()
        page.set_viewport_size({"width": 1920, "height": 1200})
        print("🌐 正在加载 CoinMarketCap...")
        page.goto(CMC_URL, timeout=60000)
        page.wait_for_selector("text=Total Net Flow", timeout=30000)
        print("📸 截图中...")
        page.screenshot(path=SCREENSHOT_PATH, full_page=False)
        browser.close()
        return os.path.exists(SCREENSHOT_PATH)


def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analyze_with_qwen_vl(image_b64):
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "qwen-vl-plus",
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{image_b64}"},
                    {"text": (
                        "请从这张网页截图中提取 Bitcoin ETF 的最新净流入（Net Flow）和对应日期。"
                        "只返回纯 JSON 格式，包含字段：date（字符串，格式 YYYY-MM-DD）、net_flow（数字，单位为美元，不要$和逗号）。"
                        "如果无法识别，返回 {\"error\": \"not found\"}"
                    )}
                ]
            }]
        },
        "parameters": {"max_tokens": 300}
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Qwen-VL API 错误: {resp.text}")

    content = resp.json()["output"]["choices"][0]["message"]["content"][0]["text"]
    print("🤖 Qwen-VL 响应:", content)
    return content


def send_pushplus(title, content):
    requests.post(
        "http://www.pushplus.plus/send",
        json={
            "token": PUSHPLUS_TOKEN,
            "title": title,
            "content": content,
            "template": "html"
        },
        timeout=10
    )


def main():
    print("🚀 启动 Bitcoin ETF 监控任务...")
    try:
        if not take_screenshot():
            send_pushplus("❌ 截图失败", "无法加载 CoinMarketCap 页面")
            return

        image_b64 = image_to_base64(SCREENSHOT_PATH)
        response_text = analyze_with_qwen_vl(image_b64)

        # 解析 JSON
        try:
            data = json.loads(response_text.strip())
        except Exception:
            send_pushplus("⚠️ JSON 解析失败", f"原始响应：<br>{response_text}")
            return

        if "error" in data:
            send_pushplus("🔍 未识别数据", "Qwen-VL 未能提取有效信息")
        else:
            date = data.get("date", "未知")
            net_flow = data.get("net_flow", 0)
            try:
                net_str = f"${float(net_flow):,.2f}"
            except:
                net_str = str(net_flow)
            content = f"""
            <b>📅 日期:</b> {date}<br>
            <b>💰 净流入 (Net Flow):</b> {net_str}<br>
            <hr>
            <i>✅ 通过 GitHub Actions + Qwen-VL 自动分析</i>
            """
            send_pushplus("📊 Bitcoin ETF 最新数据", content)

    except Exception as e:
        send_pushplus("💥 程序异常", f"错误详情：<br>{str(e)}")
    finally:
        if os.path.exists(SCREENSHOT_PATH):
            os.remove(SCREENSHOT_PATH)


if __name__ == "__main__":
    main()