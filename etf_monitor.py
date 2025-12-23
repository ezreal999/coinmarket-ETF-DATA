import os
import base64
import json
import requests
from playwright.sync_api import sync_playwright

# === 配置 ===
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN")
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
                "--lang=en-US",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        )

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
        )

        context.add_init_script("""
            delete navigator.__proto__.webdriver;
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'connection', {
                get: () => ({ effectiveType: '4g', rtt: 100, downlink: 10 })
            });
        """)

        page = context.new_page()
        print("🌐 加载 CoinMarketCap...")
        page.goto(CMC_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        # 模拟真人滚动
        print("🖱️ 模拟真人滚动...")
        for i in range(1, 6):
            page.evaluate(f"window.scrollTo(0, {i * 300})")
            page.wait_for_timeout(800)

        # 安全强制显示（修复 innerText null 错误）
        print("✨ 强制激活数据区域（安全版）...")
        page.evaluate("""
            [...document.querySelectorAll('*')].forEach(el => {
                const text = el.innerText;
                if (typeof text === 'string' && text.includes('Total Net Flow')) {
                    let node = el;
                    while (node && node !== document.body) {
                        node.style.visibility = 'visible';
                        node.style.opacity = '1';
                        node.style.display = 'block';
                        node = node.parentElement;
                    }
                    el.scrollIntoView({block: 'center', behavior: 'auto'});
                }
            });
        """)
        page.wait_for_timeout(3000)

        # 全页截图
        print("📸 全页截图...")
        page.screenshot(path=SCREENSHOT_PATH, full_page=True)
        browser.close()

        # 验证截图有效性
        if os.path.exists(SCREENSHOT_PATH) and os.path.getsize(SCREENSHOT_PATH) > 3072:
            return True
        else:
            print("❌ 截图无效（文件太小）")
            return False


def image_to_base64(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"截图文件不存在: {path}")
    size = os.path.getsize(path)
    if size < 1000:
        raise ValueError("图片文件过小，可能为空")
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
                        "你是一个金融数据提取器。请从这张 CoinMarketCap Bitcoin ETF 页面中：\n"
                        "1. 找到最新日期（通常是表格第一行，格式如 'Dec 22, 2025'）\n"
                        "2. 提取对应的 'Net Flow' 数值（如 '+$123M' 或 '-$45M'）\n"
                        "只返回纯 JSON：{\"date\": \"...\", \"net_flow\": \"...\"}\n"
                        "如果找不到，返回 {\"error\": \"data not found\"}"
                    )}
                ]
            }]
        },
        "parameters": {"max_tokens": 150}
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Qwen-VL API 错误 ({resp.status_code}): {resp.text}")
    try:
        text = resp.json()["output"]["choices"][0]["message"]["content"][0]["text"]
        return text
    except KeyError:
        raise Exception(f"Qwen-VL 响应格式异常: {resp.text}")


def send_pushplus(title, content):
    try:
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
    except Exception as e:
        print(f"⚠️ PushPlus 发送失败: {e}")


def main():
    print("🚀 启动 CMC Bitcoin ETF 监控（权威源 | 真人模拟）...")
    try:
        success = take_screenshot()

        # 总是推送截图用于调试（关键！）
        if os.path.exists(SCREENSHOT_PATH):
            with open(SCREENSHOT_PATH, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            send_pushplus(
                "🖼️ CMC 截图（调试）",
                f'<img src="data:image/png;base64,{b64}" style="max-width:100%; height:auto;">'
            )

        if not success:
            send_pushplus("❌ 截图失败", "无法生成有效截图（可能页面未加载或被拦截）")
            return

        image_b64 = image_to_base64(SCREENSHOT_PATH)
        result = analyze_with_qwen_vl(image_b64)

        # 清理 LLM 输出
        clean = result.strip().strip('`')
        if clean.startswith("json"):
            clean = clean[4:].strip()
        data = json.loads(clean)

        if "error" in data:
            send_pushplus("🔍 数据未识别", "Qwen-VL 未能从截图中提取 Net Flow 数据")
        else:
            msg = (
                f"<b>📅 日期:</b> {data['date']}<br>"
                f"<b>💰 Net Flow:</b> {data['net_flow']}<br>"
                f"<i>来源: CoinMarketCap (官方)</i>"
            )
            send_pushplus("📊 Bitcoin ETF 数据", msg)

    except Exception as e:
        send_pushplus("💥 程序异常", f"<pre>{str(e)}</pre>")
    finally:
        if os.path.exists(SCREENSHOT_PATH):
            os.remove(SCREENSHOT_PATH)


if __name__ == "__main__":
    main()