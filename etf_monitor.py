import os
import base64
import json
import requests
from playwright.sync_api import sync_playwright

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN")

if not DASHSCOPE_API_KEY or not PUSHPLUS_TOKEN:
    raise EnvironmentError("请设置 DASHSCOPE_API_KEY 和 PUSHPLUS_TOKEN")

SCREENSHOT_PATH = "/tmp/cmc_etf.png"
CMC_URL = "https://coinmarketcap.com/etf/bitcoin/"

def take_screenshot():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
            ]
        )

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )

        # 移除自动化痕迹
        context.add_init_script("""
            delete navigator.__proto__.webdriver;
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)

        page = context.new_page()
        print("🌐 加载 CoinMarketCap...")
        page.goto(CMC_URL, timeout=60000)
        page.wait_for_timeout(8000)  # 等待基础渲染

        # ✅ 关键：不再等待 visible，只等待元素存在
        try:
            print("🔍 等待 'Total Net Flow' 元素存在（不要求可见）...")
            page.wait_for_selector("text=Total Net Flow", timeout=30000, state="attached")
        except Exception as e:
            print(f"❌ 元素未出现: {e}")
            page.screenshot(path=SCREENSHOT_PATH)
            browser.close()
            return False

        # ✅ 强制让所有包含 "Total Net Flow" 的元素可见
        print("✨ 强制显示隐藏元素...")
        page.evaluate("""
            [...document.querySelectorAll('*')].forEach(el => {
                if (el.textContent && el.textContent.includes('Total Net Flow')) {
                    el.style.visibility = 'visible';
                    el.style.opacity = '1';
                    el.style.display = 'block';
                    // 滚动到该元素
                    el.scrollIntoView({ behavior: 'auto', block: 'center' });
                }
            });
        """)
        page.wait_for_timeout(2000)

        # 截图
        print("📸 截图...")
        page.screenshot(path=SCREENSHOT_PATH, full_page=False)
        browser.close()
        return True

def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def analyze_with_qwen_vl(image_b64):
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation"
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-vl-plus",
        "input": {
            "messages": [{
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{image_b64}"},
                    {"text": (
                        "从这张 CoinMarketCap ETF 页面截图中提取最新一天的 Net Flow 数值和日期。\n"
                        "只返回纯 JSON：{\"date\": \"Dec 22, 2025\", \"net_flow\": \"+$123M\"}\n"
                        "如无法识别，返回 {\"error\": \"not found\"}"
                    )}
                ]
            }]
        },
        "parameters": {"max_tokens": 150}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Qwen-VL 错误: {resp.text}")
    text = resp.json()["output"]["choices"][0]["message"]["content"][0]["text"]
    return text

def send_pushplus(title, content):
    requests.post("http://www.pushplus.plus/send", json={
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html"
    })

def main():
    print("🚀 启动 CoinMarketCap ETF 监控（高级反反爬模式）...")
    try:
        if not take_screenshot():
            send_pushplus("❌ 截图失败", "CoinMarketCap 页面未加载出可见的 Net Flow 数据（可能被反爬）")
            return

        b64 = image_to_base64(SCREENSHOT_PATH)
        result = analyze_with_qwen_vl(b64)

        # 清理并解析 JSON
        clean = result.strip().strip('`')
        if clean.startswith("json"): clean = clean[4:].strip()
        data = json.loads(clean)

        if "error" in data:
            send_pushplus("🔍 识别失败", "Qwen-VL 未能提取数据")
        else:
            msg = f"<b>📅 日期:</b> {data['date']}<br><b>💰 Net Flow:</b> {data['net_flow']}"
            send_pushplus("📊 CMC Bitcoin ETF 数据", msg)
    except Exception as e:
        send_pushplus("💥 程序异常", f"<pre>{str(e)}</pre>")
    finally:
        if os.path.exists(SCREENSHOT_PATH):
            os.remove(SCREENSHOT_PATH)

if __name__ == "__main__":
    main()