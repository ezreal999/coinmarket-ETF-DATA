import os
import base64
import json
import requests
from playwright.sync_api import sync_playwright

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
                "--disable-features=IsolateOrigins,site-per-process",  # 减少沙箱隔离
            ]
        )

        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
            java_script_enabled=True,
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

        # 拦截并等待关键 API（可选，提升可靠性）
        api_loaded = False
        def on_response(response):
            nonlocal api_loaded
            if "/v1/cryptocurrency/etf/" in response.url and response.status == 200:
                api_loaded = True
                print("✅ ETF 数据 API 已加载")

        page.on("response", on_response)

        print("🌐 正在加载 CoinMarketCap...")
        page.goto(CMC_URL, wait_until="domcontentloaded", timeout=60000)

        # 等待基础结构
        page.wait_for_timeout(5000)

        # 👁️ 模拟真人行为：缓慢滚动 + 鼠标移动
        print("🖱️ 模拟真人交互...")
        for i in range(1, 6):
            scroll_y = i * 300
            page.evaluate(f"window.scrollTo(0, {scroll_y})")
            page.wait_for_timeout(800)

            # 鼠标移动到可能的数据区域
            try:
                elements = page.query_selector_all("text=Total Net Flow")
                if elements:
                    elements[0].hover(timeout=2000)
                    print("✅ 悬停到 Net Flow 区域")
            except:
                pass

        # 等待 API 加载或超时
        for _ in range(20):
            if api_loaded:
                print("📡 确认数据已从 API 加载")
                break
            page.wait_for_timeout(1000)

        # 强制激活所有潜在容器
        page.evaluate("""
            [...document.querySelectorAll('*')].forEach(el => {
                if (el.innerText.includes('Total Net Flow')) {
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

        # 严格验证
        if os.path.exists(SCREENSHOT_PATH) and os.path.getsize(SCREENSHOT_PATH) > 3072:
            return True
        else:
            print("❌ 截图无效（<3KB）")
            return False

def image_to_base64(path):
    with open(path, "rb") as f:
        data = f.read()
        if len(data) < 1000:
            raise ValueError("图片数据过小")
        return base64.b64encode(data).decode("utf-8")

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
    except KeyError as e:
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
    print("🚀 启动 CMC 监控（真人模拟模式）...")
    try:
        success = take_screenshot()

        # 总是推送截图用于诊断
        if os.path.exists(SCREENSHOT_PATH):
            with open(SCREENSHOT_PATH, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            send_pushplus(
                "🖼️ CMC 截图（调试）",
                f'<img src="data:image/png;base64,{b64}" style="max-width:100%; height:auto;">'
            )

        if not success:
            send_pushplus("❌ 截图失败", "文件太小或未生成")
            return

        image_b64 = image_to_base64(SCREENSHOT_PATH)
        result = analyze_with_qwen_vl(image_b64)
        # ...后续处理...

if __name__ == "__main__":
    main()