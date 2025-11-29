import time
import random
import requests
import logging
from datetime import datetime
import uuid
import platform
import json
import os
import sys
import signal
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("requests.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# 定义默认URL
DEFAULT_URL = "https://seemly-organized-thing.glitch.me/"
URL = DEFAULT_URL

# 创建cookies目录
COOKIES_DIR = "cookies"
os.makedirs(COOKIES_DIR, exist_ok=True)

# 创建会话管理器
class SessionManager:
    def __init__(self):
        self.sessions = {}
        self.url_sessions = {}  # 用于存储URL和会话ID的映射
        self.load_cookies()
        
    def load_cookies(self):
        """从文件加载已保存的cookie"""
        if not os.path.exists(COOKIES_DIR):
            return
            
        for file in os.listdir(COOKIES_DIR):
            if file.endswith('.json'):
                session_id = file.split('.')[0]
                try:
                    with open(os.path.join(COOKIES_DIR, file), 'r') as f:
                        data = json.load(f)
                        cookies = data.get('cookies', []) if isinstance(data, dict) else data
                        url = data.get('url', '') if isinstance(data, dict) else ''
                        
                        session = requests.Session()
                        for cookie in cookies:
                            session.cookies.set(cookie['name'], cookie['value'])
                            
                        self.sessions[session_id] = {
                            'session': session,
                            'user_agent': '',
                            'last_used': datetime.now(),
                            'visit_count': 0,
                            'url': url
                        }
                        
                        # 添加URL到会话ID的映射
                        if url:
                            if url not in self.url_sessions:
                                self.url_sessions[url] = []
                            self.url_sessions[url].append(session_id)
                            
                        logger.info(f"已加载会话: {session_id} (URL: {url})")
                except Exception as e:
                    logger.error(f"加载cookie文件出错: {e}")
    
    def save_cookies(self, session_id, url=''):
        """保存会话cookie到文件"""
        if session_id not in self.sessions:
            return
            
        session = self.sessions[session_id]['session']
        cookies = []
        for cookie in session.cookies:
            cookies.append({
                'name': cookie.name,
                'value': cookie.value,
                'domain': cookie.domain,
                'path': cookie.path
            })
        
        # 保存会话数据，包括URL    
        data = {
            'cookies': cookies,
            'url': url
        }
            
        try:
            with open(os.path.join(COOKIES_DIR, f"{session_id}.json"), 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"保存cookie出错: {e}")
    
    def get_session(self, user_agent, headers, url=''):
        """获取或创建会话"""
        # 70%概率复用已有会话，30%概率创建新会话
        existing_sessions = []
        
        # 如果有URL对应的会话，优先使用
        if url in self.url_sessions:
            for session_id in self.url_sessions[url]:
                if session_id in self.sessions:
                    session_data = self.sessions[session_id]
                    if (datetime.now() - session_data['last_used']).total_seconds() < 86400:  # 24小时内的会话
                        existing_sessions.append((session_id, session_data))
        
        # 如果没有找到URL对应的会话，尝试使用任何可用会话
        if not existing_sessions:
            existing_sessions = [s for s in self.sessions.items() 
                                if (datetime.now() - s[1]['last_used']).total_seconds() < 86400]  # 24小时内的会话
        
        if existing_sessions and random.random() < 0.7:
            # 选择一个现有会话
            session_id, session_data = random.choice(existing_sessions)
            session_data['last_used'] = datetime.now()
            session_data['visit_count'] += 1
            session_data['url'] = url  # 更新URL
            
            # 更新User-Agent以保持一致性
            headers['user-agent'] = session_data['user_agent'] if session_data['user_agent'] else headers['user-agent']
            
            # 更新URL到会话ID的映射
            if url:
                if url not in self.url_sessions:
                    self.url_sessions[url] = []
                if session_id not in self.url_sessions[url]:
                    self.url_sessions[url].append(session_id)
                    
            logger.info(f"复用会话: {session_id} (访问次数: {session_data['visit_count']})")
            return session_id, session_data['session']
        else:
            # 创建新会话
            session_id = str(uuid.uuid4())[:8]
            session = requests.Session()
            
            # 配置重试策略
            retry_strategy = Retry(
                total=3,
                backoff_factor=0.3,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            self.sessions[session_id] = {
                'session': session,
                'user_agent': headers['user-agent'],
                'last_used': datetime.now(),
                'visit_count': 1,
                'url': url
            }
            
            # 添加URL到会话ID的映射
            if url:
                if url not in self.url_sessions:
                    self.url_sessions[url] = []
                self.url_sessions[url].append(session_id)
                
            logger.info(f"创建新会话: {session_id}")
            return session_id, session

# 初始化会话管理器
session_manager = SessionManager()

# 预定义的真实User-Agent列表
REAL_USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    # Chrome Android
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Firefox macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    # Safari iOS
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
]

# 模拟真人的请求头
def get_headers():
    # 从预定义列表中随机选择User-Agent
    user_agent = random.choice(REAL_USER_AGENTS)
    
    # 从UA检测浏览器类型
    browser_info = detect_browser_from_ua(user_agent)
    browser_name = browser_info["browser"]
    platform_name = browser_info["platform"]
    browser_version = extract_version_from_ua(user_agent)
    
    # 生成sec-ch-ua值
    sec_ch_ua = generate_sec_ch_ua(browser_name, browser_version)
    
    # 根据平台设置移动标识
    is_mobile = platform_name in ["Android", "iPhone", "iPad"] or "Mobile" in user_agent or "Android" in user_agent
    mobile_flag = "?1" if is_mobile else "?0"
    
    # 构建请求头
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": random.choice(["zh-CN,zh;q=0.9", "en-US,en;q=0.9", "en-US,en;q=0.8,zh-CN;q=0.6,zh;q=0.4", "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3"]),
        "cache-control": random.choice(["max-age=0", "no-cache", "max-age=0, private"]),
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": mobile_flag,
        "sec-ch-ua-platform": f'"{platform_name}"',
        "sec-fetch-dest": random.choice(["document", "empty"]),
        "sec-fetch-mode": random.choice(["navigate", "cors", "no-cors"]),
        "sec-fetch-site": random.choice(["none", "same-origin", "same-site"]),
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": user_agent
    }
    
    # 随机添加额外头信息
    if random.random() < 0.3:
        headers["referer"] = random.choice([
            "https://www.google.com/",
            "https://www.bing.com/",
            "https://search.yahoo.com/",
            "https://duckduckgo.com/"
        ])
    
    if random.random() < 0.2:
        headers["dnt"] = "1"  # Do Not Track
        
    if random.random() < 0.1:
        headers["pragma"] = "no-cache"
        
    if random.random() < 0.05:
        headers["x-requested-with"] = "XMLHttpRequest"
    
    # 随机添加客户端提示
    if random.random() < 0.3:
        viewport_width = random.choice([1280, 1366, 1440, 1536, 1600, 1920, 2560, 3440, 3840])
        viewport_height = int(viewport_width * random.uniform(0.5, 0.7))
        headers["viewport-width"] = str(viewport_width)
        headers["viewport-height"] = str(viewport_height)
        headers["device-memory"] = random.choice(["4", "8", "16"])
        headers["sec-ch-device-memory"] = random.choice(["4", "8", "16"])
        headers["sec-ch-viewport-width"] = str(viewport_width)
        headers["sec-ch-viewport-height"] = str(viewport_height)
        
    return headers

def extract_version_from_ua(user_agent):
    """从User-Agent提取版本号"""
    ua = user_agent.lower()
    version = "120"  # 默认版本
    
    # 尝试提取Chrome版本
    if "chrome/" in ua:
        try:
            chrome_part = ua.split("chrome/")[1]
            version = chrome_part.split(".")[0]
        except:
            pass
    # 尝试提取Firefox版本
    elif "firefox/" in ua:
        try:
            ff_part = ua.split("firefox/")[1]
            version = ff_part.split(".")[0]
        except:
            pass
    # 尝试提取Edge版本
    elif "edg/" in ua:
        try:
            edge_part = ua.split("edg/")[1]
            version = edge_part.split(".")[0]
        except:
            pass
    # 尝试提取Safari版本
    elif "version/" in ua and "safari" in ua:
        try:
            safari_part = ua.split("version/")[1]
            version = safari_part.split(".")[0]
        except:
            pass
            
    return version

def detect_browser_from_ua(user_agent):
    """从User-Agent检测浏览器类型和平台"""
    ua = user_agent.lower()
    browser = "Chrome"
    platform = "Windows"
    
    if "firefox" in ua:
        browser = "Firefox"
    elif "edg/" in ua:
        browser = "Edge"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    
    if "windows" in ua:
        platform = "Windows"
    elif "macintosh" in ua or "mac os" in ua:
        platform = "Macintosh"
    elif "linux" in ua and "android" not in ua:
        platform = "Linux"
    elif "android" in ua:
        platform = "Android"
    elif "iphone" in ua:
        platform = "iPhone"
    elif "ipad" in ua:
        platform = "iPad"
        
    return {"browser": browser, "platform": platform}

def generate_sec_ch_ua(browser, version):
    """生成适合浏览器的sec-ch-ua值"""
    if browser == "Chrome":
        return f'"Google Chrome";v="{version}", "Chromium";v="{version}", "Not/A)Brand";v="{random.randint(8, 99)}"'
    elif browser == "Firefox":
        return f'"Firefox";v="{version}", "Not)A;Brand";v="8"'
    elif browser == "Edge":
        return f'"Microsoft Edge";v="{version}", "Chromium";v="{int(version)-10}", "Not/A)Brand";v="{random.randint(8, 99)}"'
    elif browser == "Safari":
        return f'"Safari";v="{version}", "Not)A;Brand";v="8"'
    else:
        return f'"Google Chrome";v="{version}", "Chromium";v="{version}", "Not/A)Brand";v="{random.randint(8, 99)}"'

# 存储ETag以模拟浏览器缓存行为
etag = None

def simulate_human_behavior():
    """模拟人类浏览行为"""
    # 模拟页面加载后的行为
    behaviors = [
        {"action": "scroll_down", "probability": 0.7},
        {"action": "click_element", "probability": 0.3},
        {"action": "move_mouse", "probability": 0.5},
        {"action": "idle", "probability": 0.2}
    ]
    
    # 随机选择1-3个行为执行
    num_actions = random.randint(1, 3)
    selected_behaviors = random.sample(behaviors, num_actions)
    
    for behavior in selected_behaviors:
        if random.random() <= behavior["probability"]:
            action = behavior["action"]
            duration = random.uniform(0.5, 3.0)
            
            if action == "scroll_down":
                scroll_amount = random.randint(300, 1500)
                logger.info(f"模拟行为: 向下滚动 {scroll_amount}px ({duration:.1f}秒)")
            elif action == "click_element":
                logger.info(f"模拟行为: 点击页面元素 ({duration:.1f}秒)")
            elif action == "move_mouse":
                logger.info(f"模拟行为: 移动鼠标 ({duration:.1f}秒)")
            elif action == "idle":
                idle_time = random.uniform(2.0, 10.0)
                logger.info(f"模拟行为: 停留页面 ({idle_time:.1f}秒)")
                duration = idle_time
                
            time.sleep(duration)

def send_request():
    """发送请求并模拟真人行为"""
    global etag
    headers = get_headers()
    
    # 获取会话
    session_id, session = session_manager.get_session(headers['user-agent'], headers, URL)
    
    # 如果有ETag，添加到请求头中
    if etag and random.random() < 0.9:  # 90%的概率使用缓存
        headers["if-none-match"] = etag
    
    # 随机添加指纹特征
    if random.random() < 0.1:
        # 模拟不同的网络条件
        headers["downlink"] = str(random.randint(5, 50))
        headers["rtt"] = str(random.randint(50, 250))
        headers["ect"] = random.choice(["4g", "3g"])
    
    try:
        # 模拟网络延迟
        network_delay = random.uniform(0.05, 0.3)  # 50-300ms的网络延迟
        time.sleep(network_delay)
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 发送请求
        response = session.get(URL, headers=headers, timeout=10)
        
        # 计算请求时间
        request_time = time.time() - start_time
        
        # 记录ETag以便下次请求使用
        if 'etag' in response.headers:
            etag = response.headers['etag']
        
        # 保存会话cookies
        session_manager.save_cookies(session_id, URL)
        
        # 记录请求信息
        logger.info(f"请求发送到 {URL}")
        logger.info(f"会话ID: {session_id}")
        logger.info(f"状态码: {response.status_code}")
        logger.info(f"响应时间: {request_time:.2f}秒")
        logger.info(f"User-Agent: {headers['user-agent']}")
        logger.info(f"Platform: {headers['sec-ch-ua-platform']}")
        logger.info(f"Cookie数量: {len(session.cookies)}")
        
        # 只在状态码变化或非304状态时打印详细信息
        if response.status_code != 304:
            logger.info(f"响应头: {dict(response.headers)}")
            logger.info(f"响应内容: {response.text[:100]}..." if len(response.text) > 100 else f"响应内容: {response.text}")
        else:
            logger.info("内容未修改 (304 Not Modified)")
        
        # 模拟人类浏览行为
        if response.status_code == 200:
            simulate_human_behavior()
            
    except requests.exceptions.Timeout:
        logger.warning("请求超时")
    except requests.exceptions.ConnectionError:
        logger.warning("连接错误")
    except Exception as e:
        logger.error(f"发送请求时出错: {e}")

# 后台运行相关函数
def run_in_background():
    """将进程放入后台运行"""
    # 创建PID文件
    pid = os.getpid()
    with open('glitch.pid', 'w') as f:
        f.write(str(pid))
    
    # 设置日志输出到文件
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    file_handler = logging.FileHandler('glitch.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    logger.info(f"进程已在后台运行，PID: {pid}")
    
    # 忽略终端信号
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

# 主循环，以随机间隔发送请求
def main():
    global URL
    
    # 解析命令行参数
    background = False
    
    # 简单的参数解析
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        
        if arg == '-u' or arg == '--url':
            if i + 1 < len(sys.argv):
                URL = sys.argv[i + 1]
                i += 2
            else:
                print("错误: URL参数需要一个值")
                sys.exit(1)
        elif arg == '-b' or arg == '--background':
            background = True
            i += 1
        else:
            i += 1
    
    # 如果指定后台运行
    if background:
        print(f"正在后台启动，访问URL: {URL}")
        print("日志将写入 glitch.log 文件")
        run_in_background()
    else:
        logger.info("开始运行脚本，模拟真人访问...")
        logger.info(f"目标URL: {URL}")
    
    try:
        while True:
            # 确保每1-4分钟发送一次请求，防止Glitch休眠
            # 60%的概率在1-3分钟之间
            # 40%的概率在3-4分钟之间
            rand = random.random()
            if rand < 0.6:  # 60%的概率
                wait_time = random.randint(60, 180)  # 1-3分钟
            else:  # 40%的概率
                wait_time = random.randint(180, 240)  # 3-4分钟
                
            current_time = datetime.now().strftime("%H:%M:%S")
            logger.info(f"当前时间: {current_time}, 等待 {wait_time} 秒...")
            
            # 不是精确等待，而是在目标时间上下浮动一点
            jitter = random.uniform(-3, 3)
            actual_wait = max(1, wait_time + jitter)
            time.sleep(actual_wait)
            
            send_request()
            
    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except Exception as e:
        logger.error(f"程序出错: {e}")
        
if __name__ == "__main__":
    main()
