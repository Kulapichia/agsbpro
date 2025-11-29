#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import random
import time
import shutil
import re
import base64
import socket
import subprocess
import platform
from datetime import datetime
import uuid
from pathlib import Path
import urllib.request
import ssl
import tempfile

# 检查requests库是否安装，如果未安装则尝试安装
try:
    import requests
except ImportError:
    print("检测到未安装requests库，正在尝试安装...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        print("requests库安装成功")
    except Exception as e:
        print(f"安装requests库失败: {e}")
        print("请手动执行: pip install requests")
        # 继续执行，但API上传功能将不可用

# 全局变量
INSTALL_DIR = Path.home() / ".agsb"  # 用户主目录下的隐藏文件夹，避免root权限
CONFIG_FILE = INSTALL_DIR / "config.json"
SB_PID_FILE = INSTALL_DIR / "sbpid.log"
ARGO_PID_FILE = INSTALL_DIR / "sbargopid.log"
LIST_FILE = INSTALL_DIR / "list.txt"
LOG_FILE = INSTALL_DIR / "argo.log"
DEBUG_LOG = INSTALL_DIR / "python_debug.log"
UPLOAD_API = "https://file.zmkk.fun/api/upload"  # 文件上传API

# 网络请求函数
def http_get(url, timeout=10):
    try:
        # 创建一个上下文来忽略SSL证书验证
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"HTTP请求失败: {url}, 错误: {e}")
        return None

def download_file(url, target_path, mode='wb'):
    try:
        # 创建一个上下文来忽略SSL证书验证
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ctx) as response, open(target_path, mode) as out_file:
            shutil.copyfileobj(response, out_file)
        return True
    except Exception as e:
        print(f"下载文件失败: {url}, 错误: {e}")
        return False

# 上传订阅到API服务器
def upload_to_api(subscription_content):
    """
    将订阅内容上传到API服务器
    :param subscription_content: 订阅内容
    :return: 成功返回True，失败返回False
    """
    try:
        # 确保requests库已导入
        if 'requests' not in sys.modules:
            print("\033[36m│ \033[31m未能导入requests库，跳过上传\033[0m")
            return False
            
        write_debug_log("开始上传订阅内容到API服务器")
        
        # 生成当前时间作为文件名（精确到秒）
        current_time = datetime.now().strftime('%Y%m%d%H%M%S')
        temp_file = INSTALL_DIR / f"{current_time}.txt"
        
        # 将订阅内容写入临时文件
        try:
            with open(str(temp_file), 'w') as f:
                f.write(subscription_content)
        except Exception as e:
            write_debug_log(f"创建临时文件失败: {e}")
            print(f"\033[36m│ \033[31m创建临时文件失败: {e}\033[0m")
            return False
            
        # 构建multipart表单数据
        try:
            files = {
                'file': (f"{current_time}.txt", open(str(temp_file), 'rb'))
            }
            
            # 发送请求
            write_debug_log(f"正在上传文件到API: {UPLOAD_API}")
            response = requests.post(UPLOAD_API, files=files)
            
            # 关闭文件
            files['file'][1].close()
            
            # 删除临时文件
            if os.path.exists(str(temp_file)):
                os.remove(str(temp_file))
            
            # 检查响应
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get('success') or result.get('url'):
                        url = result.get('url', '')
                        write_debug_log(f"上传成功，URL: {url}")
                        print(f"\033[36m│ \033[32m订阅已成功上传，URL: {url}\033[0m")
                        
                        # 保存URL到文件
                        url_file = INSTALL_DIR / "subscription_url.txt"
                        with open(str(url_file), 'w') as f:
                            f.write(url)
                            
                        return True
                    else:
                        write_debug_log(f"API返回错误: {result}")
                        print(f"\033[36m│ \033[31mAPI返回错误: {result}\033[0m")
                        return False
                except Exception as e:
                    write_debug_log(f"解析API响应失败: {e}")
                    print(f"\033[36m│ \033[31m解析API响应失败: {e}\033[0m")
                    return False
            else:
                write_debug_log(f"上传失败，状态码: {response.status_code}")
                print(f"\033[36m│ \033[31m上传失败，状态码: {response.status_code}\033[0m")
                return False
                
        except Exception as e:
            write_debug_log(f"上传过程中出错: {e}")
            print(f"\033[36m│ \033[31m上传过程中出错: {e}\033[0m")
            
            # 清理临时文件
            if os.path.exists(str(temp_file)):
                try:
                    os.remove(str(temp_file))
                except:
                    pass
                    
            return False
            
    except Exception as e:
        write_debug_log(f"上传订阅到API服务器失败: {e}")
        print(f"\033[36m│ \033[31m上传订阅到API服务器失败: {e}\033[0m")
        return False

# 测试API连接
def test_api_connection():
    """
    测试API服务器连接
    :return: 连接正常返回True，异常返回False
    """
    try:
        if 'requests' not in sys.modules:
            print("\033[31m未安装requests库，请先安装: pip install requests\033[0m")
            return False
            
        print("正在测试API服务器连接...")
        
        # 尝试访问API服务器
        response = requests.get(UPLOAD_API.rsplit('/', 1)[0])  # 获取API基础URL
        
        if response.status_code == 200:
            print(f"\033[32mAPI服务器连接正常，状态码: {response.status_code}\033[0m")
            return True
        else:
            print(f"\033[31mAPI服务器连接异常，状态码: {response.status_code}\033[0m")
            return False
    except Exception as e:
        print(f"\033[31m测试API服务器连接出错: {e}\033[0m")
        return False

# 脚本信息
def print_info():
    print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
    print("\033[36m│                \033[33m✨ ArgoSB Python3 一键脚本 ✨               \033[36m│\033[0m")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print("\033[36m│ \033[32m作者: 康康                                                  \033[36m│\033[0m")
    print("\033[36m│ \033[32mGithub: https://github.com/zhumengkang/                    \033[36m│\033[0m")
    print("\033[36m│ \033[32mYouTube: https://www.youtube.com/@康康的V2Ray与Clash         \033[36m│\033[0m")
    print("\033[36m│ \033[32mTelegram: https://t.me/+WibQp7Mww1k5MmZl                   \033[36m│\033[0m")
    print("\033[36m│ \033[32m版本: 25.5.30 (仅支持Python 3)                             \033[36m│\033[0m")
    print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")

# 打印使用帮助信息
def print_usage():
    print("\033[33m使用方法:\033[0m")
    print("  \033[36mpython3 agsb.py\033[0m              - 安装并启动服务")
    print("  \033[36mpython3 agsb.py install\033[0m      - 安装服务")
    print("  \033[36mpython3 agsb.py status\033[0m       - 查看服务状态和节点信息")
    print("  \033[36mpython3 agsb.py cat\033[0m          - 查看单行节点列表")
    print("  \033[36mpython3 agsb.py update\033[0m       - 更新脚本")
    print("  \033[36mpython3 agsb.py del\033[0m          - 卸载服务")
    print("  \033[36mpython3 agsb.py testapi\033[0m      - 测试API服务器连接")
    print()

# 写入日志函数
def write_debug_log(message):
    try:
        if not os.path.exists(str(INSTALL_DIR)):
            os.makedirs(str(INSTALL_DIR), exist_ok=True)
        
        with open(str(DEBUG_LOG), 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"写入日志失败: {e}")

# 下载二进制文件
def download_binary(name, download_url, target_path):
    print(f"正在下载 {name}...")
    success = download_file(download_url, target_path)
    if success:
        print(f"{name} 下载成功!")
        os.chmod(target_path, 0o755)  # 设置可执行权限
        return True
    else:
        print(f"{name} 下载失败!")
        return False

# 生成VMess链接
def generate_vmess_link(config):
    vmess_obj = {
        "v": "2",
        "ps": config.get("ps", "ArgoSB"),
        "add": config.get("add", ""),
        "port": config.get("port", "443"),
        "id": config.get("id", ""),
        "aid": config.get("aid", "0"),
        "net": config.get("net", "ws"),
        "type": config.get("type", "none"),
        "host": config.get("host", ""),
        "path": config.get("path", ""),
        "tls": config.get("tls", "tls"),
        "sni": config.get("sni", "")
    }
    
    vmess_str = json.dumps(vmess_obj)
    vmess_b64 = base64.b64encode(vmess_str.encode()).decode()
    
    return f"vmess://{vmess_b64}"

# 生成链接
def generate_links(domain, port_vm_ws, uuid_str):
    write_debug_log(f"生成链接: domain={domain}, port_vm_ws={port_vm_ws}, uuid_str={uuid_str}")
    
    # VMess WebSocket 配置
    ws_path = f"/{uuid_str}-vm"  # WebSocket路径和前面保持一致
    ws_path_full = f"{ws_path}?ed=2048" # 添加额外参数
    write_debug_log(f"WebSocket路径: {ws_path_full}")
    
    hostname = socket.gethostname()
    all_links = []  # 存储所有链接
    link_names = []  # 存储链接名称
    link_configs = []  # 存储节点配置信息
    
    # === TLS节点 ===
    # 443端口 - 104.16.0.0
    config1 = {
        "ps": f"vmess-ws-tls-argo-{hostname}-443",
        "add": "104.16.0.0",
        "port": "443",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": "tls",
        "sni": domain
    }
    vmatls_link1 = generate_vmess_link(config1)
    all_links.append(vmatls_link1)
    link_names.append("TLS-443-104.16.0.0")
    link_configs.append(config1)
    
    # 8443端口 - 104.17.0.0
    config2 = {
        "ps": f"vmess-ws-tls-argo-{hostname}-8443",
        "add": "104.17.0.0",
        "port": "8443",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": "tls",
        "sni": domain
    }
    vmatls_link2 = generate_vmess_link(config2)
    all_links.append(vmatls_link2)
    link_names.append("TLS-8443-104.17.0.0")
    link_configs.append(config2)
    
    # 2053端口 - 104.18.0.0
    config3 = {
        "ps": f"vmess-ws-tls-argo-{hostname}-2053",
        "add": "104.18.0.0",
        "port": "2053",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": "tls",
        "sni": domain
    }
    vmatls_link3 = generate_vmess_link(config3)
    all_links.append(vmatls_link3)
    link_names.append("TLS-2053-104.18.0.0")
    link_configs.append(config3)
    
    # 2083端口 - 104.19.0.0
    config4 = {
        "ps": f"vmess-ws-tls-argo-{hostname}-2083",
        "add": "104.19.0.0",
        "port": "2083",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": "tls",
        "sni": domain
    }
    vmatls_link4 = generate_vmess_link(config4)
    all_links.append(vmatls_link4)
    link_names.append("TLS-2083-104.19.0.0")
    link_configs.append(config4)
    
    # 2087端口 - 104.20.0.0
    config5 = {
        "ps": f"vmess-ws-tls-argo-{hostname}-2087",
        "add": "104.20.0.0",
        "port": "2087",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": "tls",
        "sni": domain
    }
    vmatls_link5 = generate_vmess_link(config5)
    all_links.append(vmatls_link5)
    link_names.append("TLS-2087-104.20.0.0")
    link_configs.append(config5)
    
    # === 非TLS节点 ===
    # 80端口 - 104.21.0.0
    config6 = {
        "ps": f"vmess-ws-argo-{hostname}-80",
        "add": "104.21.0.0",
        "port": "80",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": ""
    }
    vma_link7 = generate_vmess_link(config6)
    all_links.append(vma_link7)
    link_names.append("WS-80-104.21.0.0")
    link_configs.append(config6)
    
    # 8080端口 - 104.22.0.0
    config7 = {
        "ps": f"vmess-ws-argo-{hostname}-8080",
        "add": "104.22.0.0",
        "port": "8080",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": ""
    }
    vma_link8 = generate_vmess_link(config7)
    all_links.append(vma_link8)
    link_names.append("WS-8080-104.22.0.0")
    link_configs.append(config7)
    
    # 8880端口 - 104.24.0.0
    config8 = {
        "ps": f"vmess-ws-argo-{hostname}-8880",
        "add": "104.24.0.0",
        "port": "8880",
        "id": uuid_str,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": domain,
        "path": ws_path_full,
        "tls": ""
    }
    vma_link9 = generate_vmess_link(config8)
    all_links.append(vma_link9)
    link_names.append("WS-8880-104.24.0.0")
    link_configs.append(config8)
    
    # 保存所有链接到临时文件
    jh_file = INSTALL_DIR / "jh.txt"
    with open(str(jh_file), 'w') as f:
        for link in all_links:
            f.write(f"{link}\n")
    
    # 生成一个所有节点的纯文本文件，一行一个节点，没有任何分割
    all_nodes_file = INSTALL_DIR / "allnodes.txt"
    with open(str(all_nodes_file), 'w') as f:
        for link in all_links:
            f.write(f"{link}\n")
    
    # 创建一个合并的订阅内容
    all_content = "\n".join(all_links)
    all_links_b64 = base64.b64encode(all_content.encode()).decode()
    
    # 上传订阅内容到API服务器
    upload_to_api(all_links_b64)
    
    # 创建简单的 LIST_FILE - 直接打印所有节点而不使用base64
    with open(str(LIST_FILE), 'w') as f:
        f.write("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m\n")
        f.write("\033[36m│                    \033[33m✨ ArgoSB 节点信息 ✨                   \033[36m│\033[0m\n")
        f.write("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m\n")
        f.write(f"\033[36m│ \033[32m域名: \033[0m{domain}\n")
        f.write(f"\033[36m│ \033[32mUUID: \033[0m{uuid_str}\n")
        f.write(f"\033[36m│ \033[32mVMess端口: \033[0m{port_vm_ws}\n")
        f.write(f"\033[36m│ \033[32mWebSocket路径: \033[0m{ws_path_full}\n")
        f.write("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m\n")
        f.write("\033[36m│ \033[33m所有节点列表:\033[0m\n")
        
        for i, (link, name) in enumerate(zip(all_links, link_names)):
            f.write(f"\033[36m│ \033[32m{i+1}. {name}:\033[0m\n")
            f.write(f"\033[36m│ \033[0m{link}\n\n")
        
        f.write("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m\n")
        f.write("\033[36m│ \033[33m订阅链接(所有节点):\033[0m\n")
        f.write(f"\033[36m│ \033[0m{all_links_b64}\n\n")
        
        f.write("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m\n")
        f.write("\033[36m│ \033[33m使用方法:\033[0m\n")
        f.write("\033[36m│ \033[32m查看节点信息: \033[0mpython3 agsb.py status\n")
        f.write("\033[36m│ \033[32m查看所有节点(一行一个): \033[0mpython3 agsb.py cat\n")
        f.write("\033[36m│ \033[32m升级脚本: \033[0mpython3 agsb.py update\n")
        f.write("\033[36m│ \033[32m卸载脚本: \033[0mpython3 agsb.py del\n")
        f.write("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m\n")
    
    # 创建简单的文本版本，没有颜色代码
    with open(str(LIST_FILE) + ".txt", 'w') as f:
        f.write("---------------------------------------------------------\n")
        f.write("                    ArgoSB 节点信息                       \n")
        f.write("---------------------------------------------------------\n")
        f.write(f"域名: {domain}\n")
        f.write(f"UUID: {uuid_str}\n")
        f.write(f"VMess端口: {port_vm_ws}\n")
        f.write(f"WebSocket路径: {ws_path_full}\n")
        f.write("---------------------------------------------------------\n")
        f.write("所有节点列表:\n\n")
        
        for i, (link, name) in enumerate(zip(all_links, link_names)):
            f.write(f"{i+1}. {name}:\n")
            f.write(f"{link}\n\n")
        
        f.write("---------------------------------------------------------\n")
        f.write("订阅链接(所有节点):\n")
        f.write(f"{all_links_b64}\n\n")
        
        f.write("---------------------------------------------------------\n")
        f.write("单行节点文件路径: ~/.agsb/allnodes.txt\n")
        f.write("使用方法:\n")
        f.write("查看节点信息: python3 agsb.py status\n")
        f.write("查看所有节点(一行一个): python3 agsb.py cat\n")
        f.write("升级脚本: python3 agsb.py update\n")
        f.write("卸载脚本: python3 agsb.py del\n")
        f.write("---------------------------------------------------------\n")
    
    # 创建README.md文件
    readme_file = INSTALL_DIR / "README.md"
    with open(str(readme_file), 'w') as f:
        f.write("# ArgoSB 节点信息\n\n")
        f.write("## 基本信息\n\n")
        f.write(f"- **域名**: {domain}\n")
        f.write(f"- **UUID**: {uuid_str}\n")
        f.write(f"- **VMess端口**: {port_vm_ws}\n")
        f.write(f"- **WebSocket路径**: {ws_path_full}\n\n")
        
        f.write("## 所有节点列表\n\n")
        for i, (link, name) in enumerate(zip(all_links, link_names)):
            f.write(f"### {i+1}. {name}\n")
            f.write(f"```\n{link}\n```\n\n")
        
        f.write("## 订阅链接\n\n")
        f.write("所有节点订阅链接:\n\n")
        f.write("```\n")
        f.write(f"{all_links_b64}\n")
        f.write("```\n\n")
        
        f.write("## 单行格式节点文件\n\n")
        f.write("如果您需要每行一个节点的格式，可以查看文件: `~/.agsb/allnodes.txt`\n\n")
        f.write("```bash\ncat ~/.agsb/allnodes.txt\n```\n\n")
        
        f.write("## 使用方法\n\n")
        f.write("- 查看节点信息: `python3 agsb.py status`\n")
        f.write("- 查看所有节点(一行一个): `python3 agsb.py cat`\n")
        f.write("- 升级脚本: `python3 agsb.py update`\n")
        f.write("- 卸载脚本: `python3 agsb.py del`\n\n")
        
        f.write("## 注意事项\n\n")
        f.write("- 该脚本由康康开发，更多信息请访问 [GitHub项目](https://github.com/zhumengkang/)\n")
        f.write("- YouTube频道: [康康的V2Ray与Clash](https://www.youtube.com/@康康的V2Ray与Clash)\n")
        f.write("- Telegram频道: [https://t.me/+WibQp7Mww1k5MmZl](https://t.me/+WibQp7Mww1k5MmZl)\n")
    
    # 打印节点信息
    print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
    print("\033[36m│                \033[33m✨ ArgoSB 安装成功! ✨                    \033[36m│\033[0m")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print(f"\033[36m│ \033[32m域名: \033[0m{domain}")
    print(f"\033[36m│ \033[32mUUID: \033[0m{uuid_str}")
    print(f"\033[36m│ \033[32mVMess端口: \033[0m{port_vm_ws}")
    print(f"\033[36m│ \033[32mWebSocket路径: \033[0m{ws_path_full}")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print("\033[36m│ \033[33m所有节点列表 (一行一个版本保存在: ~/.agsb/allnodes.txt):\033[0m")
    
    # 直接连续打印所有节点，中间没有分隔
    for link in all_links:
        print(f"\033[36m│ \033[0m{link}")
    
    # 添加以下代码，直接输出节点链接，没有任何前缀
    print("\033[36m│ \033[0m")
    print("\033[36m│ \033[33m直接格式节点链接:\033[0m")
    # 直接打印所有节点链接，不带任何前缀
    for link in all_links:
        print(link)
    
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print(f"\033[36m│ \033[32m节点信息已保存到: \033[0m{LIST_FILE}")
    print(f"\033[36m│ \033[32m单行节点列表保存到: \033[0m{all_nodes_file}")
    print(f"\033[36m│ \033[32mREADME文件保存到: \033[0m{readme_file}")
    print("\033[36m│ \033[32m使用 \033[33mpython3 agsb.py status\033[32m 查看节点信息\033[0m")
    print("\033[36m│ \033[32m使用 \033[33mpython3 agsb.py del\033[32m 删除节点\033[0m")
    print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
    
    write_debug_log(f"链接生成完毕，已保存到: {LIST_FILE}, {all_nodes_file}")
    
    return True

# 安装过程
def install():
    # 创建安装目录
    if not os.path.exists(str(INSTALL_DIR)):
        os.makedirs(str(INSTALL_DIR), exist_ok=True)
    
    # 切换到安装目录
    os.chdir(str(INSTALL_DIR))
    
    # 初始化日志
    write_debug_log("开始安装过程")
    
    # 检测系统架构
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    write_debug_log(f"检测到系统: {system}, 架构: {machine}")
    
    # 判断架构类型
    if system == "linux":
        if "x86_64" in machine or "amd64" in machine:
            arch = "amd64"
        elif "aarch64" in machine or "arm64" in machine:
            arch = "arm64"
        elif "armv7" in machine:
            arch = "armv7"
        else:
            arch = "amd64"  # 默认
    else:
        print("不支持的系统类型: {}".format(system))
        sys.exit(1)
    
    write_debug_log(f"确定架构类型为: {arch}")
    
    # 获取sing-box最新版本号
    try:
        print("获取sing-box最新版本号...")
        version_info = http_get("https://api.github.com/repos/SagerNet/sing-box/releases/latest")
        if version_info:
            version_data = json.loads(version_info)
            sbcore = version_data.get("tag_name", "v1.6.0").lstrip("v")
            print(f"sing-box 最新版本: {sbcore}")
        else:
            sbcore = "1.6.0"  # 默认版本
            print(f"无法获取最新版本，使用默认版本: {sbcore}")
    except Exception as e:
        sbcore = "1.6.0"  # 默认版本
        print(f"获取最新版本失败，使用默认版本: {sbcore}，错误: {e}")
    
    # 下载 sing-box
    singbox_path = str(INSTALL_DIR / "sing-box")
    if not os.path.exists(singbox_path):
        sbname = f"sing-box-{sbcore}-linux-{arch}"
        singbox_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sbcore}/{sbname}.tar.gz"
        
        print(f"下载sing-box版本: {sbcore}")
        write_debug_log(f"下载链接: {singbox_url}")
        
        # 下载压缩包
        tar_path = str(INSTALL_DIR / "sing-box.tar.gz")
        if not download_file(singbox_url, tar_path):
            print("sing-box 下载失败，尝试使用备用地址")
            
            # 尝试使用备用地址
            backup_url = f"https://github.91chi.fun/https://github.com//SagerNet/sing-box/releases/download/v{sbcore}/{sbname}.tar.gz"
            if not download_file(backup_url, tar_path):
                print("sing-box 备用下载也失败，退出安装")
                sys.exit(1)
        
        # 解压缩
        try:
            print("正在解压sing-box...")
            import tarfile
            tar = tarfile.open(tar_path)
            tar.extractall(path=str(INSTALL_DIR))
            tar.close()
            
            # 移动可执行文件
            shutil.move(str(INSTALL_DIR / sbname / "sing-box"), singbox_path)
            
            # 清理解压后的文件
            if os.path.exists(str(INSTALL_DIR / sbname)):
                shutil.rmtree(str(INSTALL_DIR / sbname))
            
            # 删除压缩包
            if os.path.exists(tar_path):
                os.remove(tar_path)
            
            # 设置执行权限
            os.chmod(singbox_path, 0o755)
        except Exception as e:
            print(f"解压sing-box失败: {e}")
            sys.exit(1)
    
    # 下载 cloudflared
    cloudflared_path = str(INSTALL_DIR / "cloudflared")
    if not os.path.exists(cloudflared_path):
        cloudflared_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
        
        print("下载cloudflared...")
        write_debug_log(f"下载链接: {cloudflared_url}")
        
        if not download_binary("cloudflared", cloudflared_url, cloudflared_path):
            print("cloudflared 下载失败，尝试使用备用地址")
            
            # 尝试使用备用地址
            backup_url = f"https://github.91chi.fun/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            if not download_binary("cloudflared", backup_url, cloudflared_path):
                print("cloudflared 备用下载也失败，退出安装")
                sys.exit(1)
    
    # 生成配置
    uuid_str = str(uuid.uuid4())
    port_vm_ws = random.randint(10000, 65535)  # 随机生成端口
    
    # 创建配置文件
    config_data = {
        "uuid_str": uuid_str,
        "port_vm_ws": port_vm_ws,
        "install_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    with open(str(CONFIG_FILE), 'w') as f:
        json.dump(config_data, f, indent=2)
    
    write_debug_log(f"生成配置文件: {CONFIG_FILE}")
    write_debug_log(f"UUID: {uuid_str}, 端口: {port_vm_ws}")
    
    # 创建 sing-box 配置
    create_sing_box_config(port_vm_ws, uuid_str)
    
    # 创建启动脚本
    create_startup_script(port_vm_ws)
    
    # 设置开机自启动
    setup_autostart()
    
    # 启动服务
    start_services()
    
    # 尝试获取域名和生成链接
    domain = get_tunnel_domain()
    if domain:
        generate_links(domain, port_vm_ws, uuid_str)
        
    else:
        print("无法获取tunnel域名，请检查log文件 {}".format(LOG_FILE))
        sys.exit(1)

# 设置开机自启动
def setup_autostart():
    try:
        crontab_list = subprocess.check_output("crontab -l 2>/dev/null || echo ''", shell=True).decode()
        lines = crontab_list.split('\n')
        
        # 过滤掉已有的相关crontab条目
        filtered_lines = []
        for line in lines:
            if ".agsb/start_sb.sh" not in line and ".agsb/start_cf.sh" not in line:
                filtered_lines.append(line)
        
        # 添加新的开机自启动条目
        filtered_lines.append("@reboot {} {}".format(INSTALL_DIR / "start_sb.sh", ">/dev/null 2>&1"))
        filtered_lines.append("@reboot {} {}".format(INSTALL_DIR / "start_cf.sh", ">/dev/null 2>&1"))
        
        new_crontab = '\n'.join(filtered_lines).strip() + '\n'
        crontab_file = tempfile.mktemp()
        with open(crontab_file, 'w') as f:
            f.write(new_crontab)
        
        subprocess.call("crontab {}".format(crontab_file), shell=True)
        if os.path.exists(crontab_file):
            os.unlink(crontab_file)
            
        write_debug_log("已设置开机自启动")
    except Exception as e:
        write_debug_log(f"设置开机自启动失败: {e}")
        print("设置开机自启动失败，但不影响正常使用")

# 卸载脚本
def uninstall():
    print("开始卸载服务")
    
    # 停止服务，使用更温和的方式先
    try:
        print("正在停止sing-box服务...")
        if os.path.exists(str(SB_PID_FILE)):
            with open(str(SB_PID_FILE), 'r') as f:
                pid = f.read().strip()
                if pid:
                    os.system("kill {} 2>/dev/null || true".format(pid))
            
        print("正在停止cloudflared服务...")
        if os.path.exists(str(ARGO_PID_FILE)):
            with open(str(ARGO_PID_FILE), 'r') as f:
                pid = f.read().strip()
                if pid:
                    os.system("kill {} 2>/dev/null || true".format(pid))
        
        # 等待1秒让进程有机会终止
        time.sleep(1)
        
        # 如果进程还在运行，尝试强制终止
        sing_box_running = subprocess.run("pgrep -f 'sing-box'", shell=True, stdout=subprocess.PIPE).returncode == 0
        cloudflared_running = subprocess.run("pgrep -f 'cloudflared'", shell=True, stdout=subprocess.PIPE).returncode == 0
            
        if sing_box_running:
            print("尝试强制终止sing-box进程...")
            os.system("pkill -9 -f 'sing-box' 2>/dev/null || true")
        
        if cloudflared_running:
            print("尝试强制终止cloudflared进程...")
            os.system("pkill -9 -f 'cloudflared' 2>/dev/null || true")
    except Exception as e:
        print("停止服务时出错: {}，但将继续卸载...".format(e))
    
    # 移除crontab项
    try:
        crontab_list = subprocess.check_output("crontab -l 2>/dev/null || echo ''", shell=True).decode()
        lines = crontab_list.split('\n')
        filtered_lines = []
        for line in lines:
            if ".agsb/start_sb.sh" not in line and ".agsb/start_cf.sh" not in line:
                filtered_lines.append(line)
        
        new_crontab = '\n'.join(filtered_lines).strip() + '\n'
        crontab_file = tempfile.mktemp()
        with open(crontab_file, 'w') as f:
            f.write(new_crontab)
        
        subprocess.call("crontab {}".format(crontab_file), shell=True)
        if os.path.exists(crontab_file):
            os.unlink(crontab_file)
    except:
        print("移除crontab项时出错，但将继续卸载...")
    
    # 删除安装目录
    if os.path.exists(str(INSTALL_DIR)):
        try:
            shutil.rmtree(str(INSTALL_DIR), ignore_errors=True)
        except:
            print("无法完全删除安装目录，请手动删除：{}".format(INSTALL_DIR))
    
    # 删除用户主目录下的可执行文件链接
    user_bin_dir = Path.home() / "bin"
    local_bin = user_bin_dir / "agsb"
    if os.path.exists(str(local_bin)):
        try:
            os.remove(str(local_bin))
        except:
            print("无法删除命令链接 {}，请手动删除".format(local_bin))
        
    print("卸载完成")
    sys.exit(0)

# 升级脚本
def upgrade():
    try:
        script_content = http_get("https://raw.githubusercontent.com/yonggekkk/argosb/main/argosb.py")
        if script_content:
            script_path = Path(__file__).resolve()
            with open(str(script_path), 'w') as f:
                f.write(script_content)
            os.chmod(str(script_path), 0o755)
            print("升级完成")
        else:
            print("升级失败，无法下载最新脚本")
    except Exception as e:
        print("升级过程中出错: {}".format(e))
    
    sys.exit(0)

# 检查脚本运行状态
def check_status():
    try:
        # 检查进程是否存在
        sing_box_running = subprocess.run("pgrep -f 'sing-box'", shell=True, stdout=subprocess.PIPE).returncode == 0
        cloudflared_running = subprocess.run("pgrep -f 'cloudflared'", shell=True, stdout=subprocess.PIPE).returncode == 0
        
        if sing_box_running and cloudflared_running and os.path.exists(str(LIST_FILE)):
            print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
            print("\033[36m│                \033[33m✨ ArgoSB 运行状态 ✨                    \033[36m│\033[0m")
            print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
            print("\033[36m│ \033[32m服务状态: \033[33m正在运行\033[0m")
            
            argo_name_file = INSTALL_DIR / "sbargoym.log"
            if os.path.exists(str(argo_name_file)):
                with open(str(argo_name_file), 'r') as f:
                    argoname = f.read().strip()
                print(f"\033[36m│ \033[32mArgo固定域名: \033[0m{argoname}")
                
                token_file = INSTALL_DIR / "sbargotoken.log"
                if os.path.exists(str(token_file)):
                    with open(str(token_file), 'r') as f:
                        print(f"\033[36m│ \033[32mArgo固定域名Token: \033[0m{f.read().strip()}")
            else:
                # 读取临时域名
                if os.path.exists(str(LOG_FILE)):
                    with open(str(LOG_FILE), 'r') as f:
                        log_content = f.read()
                    domain_match = re.search(r'https://([a-zA-Z0-9\-]+\.trycloudflare\.com)', log_content)
                    if domain_match:
                        argodomain = domain_match.group(1)
                        print(f"\033[36m│ \033[32mArgo临时域名: \033[0m{argodomain}")
                    else:
                        print("\033[36m│ \033[31mArgo临时域名未生成，请重新安装\033[0m")
            
            # 显示节点信息
            print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
            
            # 优先使用README.md展示信息（适合终端查看）
            readme_file = INSTALL_DIR / "README.md"
            if os.path.exists(str(readme_file)):
                with open(str(readme_file), 'r') as f:
                    for line in f:
                        if not line.startswith('#'):  # 跳过标题行
                            print(f"\033[36m│ \033[0m{line.strip()}")
            elif os.path.exists(str(LIST_FILE) + ".txt"):
                with open(str(LIST_FILE) + ".txt", 'r') as f:
                    for line in f:
                        print(f"\033[36m│ \033[0m{line.strip()}")
            elif os.path.exists(str(LIST_FILE)):
                with open(str(LIST_FILE), 'r') as f:
                    content = f.read()
                    # 去除ANSI颜色代码
                    content = re.sub(r'\033\[\d+m', '', content)
                    for line in content.split('\n'):
                        print(f"\033[36m│ \033[0m{line}")
            
            # 直接打印所有节点的链接，不添加前缀
            all_nodes_file = INSTALL_DIR / "allnodes.txt"
            if os.path.exists(str(all_nodes_file)):
                print("\033[36m│ \033[0m")
                print("\033[36m│ \033[33m直接格式节点链接:\033[0m")
                with open(str(all_nodes_file), 'r') as f:
                    all_links = f.read().splitlines()
                    for link in all_links:
                        print(link)
            
            print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
            
            return True
        elif not sing_box_running and not cloudflared_running:
            print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
            print("\033[36m│                \033[33m✨ ArgoSB 运行状态 ✨                    \033[36m│\033[0m")
            print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
            print("\033[36m│ \033[31mArgoSB脚本未运行\033[0m")
            print("\033[36m│ \033[32m运行 \033[33mpython3 agsb.py\033[32m 开始安装\033[0m")
            print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
            return False
        else:
            print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
            print("\033[36m│                \033[33m✨ ArgoSB 运行状态 ✨                    \033[36m│\033[0m")
            print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
            print("\033[36m│ \033[31mArgoSB脚本状态异常\033[0m")
            print("\033[36m│ \033[32m建议卸载后重新安装: \033[33mpython3 agsb.py del\033[0m")
            print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
            return False
    except Exception as e:
        print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
        print("\033[36m│                \033[33m✨ ArgoSB 运行状态 ✨                    \033[36m│\033[0m")
        print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
        print(f"\033[36m│ \033[31m检查状态时出错: {e}\033[0m")
        print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
        return False

# 创建sing-box配置
def create_sing_box_config(port_vm_ws, uuid_str):
    write_debug_log(f"创建sing-box配置，端口: {port_vm_ws}, UUID: {uuid_str}")
    
    ws_path = f"/{uuid_str}-vm"  # WebSocket路径
    write_debug_log(f"WebSocket路径: {ws_path}")
    
    # 创建配置字符串 - 保持与原始shell脚本一致的格式
    config_str = '''{
  "log": {
    "level": "info",
    "timestamp": true
  },
  "inbounds": [
    {
      "type": "vmess",
      "tag": "vmess-in",
      "listen": "127.0.0.1",
      "listen_port": %d,
      "tcp_fast_open": true,
      "sniff": true,
      "sniff_override_destination": true,
      "proxy_protocol": false,
      "users": [
        {
          "uuid": "%s",
          "alterId": 0
        }
      ],
      "transport": {
        "type": "ws",
        "path": "%s",
        "max_early_data": 2048,
        "early_data_header_name": "Sec-WebSocket-Protocol"
      }
    }
  ],
  "outbounds": [
    {
      "type": "direct",
      "tag": "direct"
    }
  ]
}''' % (port_vm_ws, uuid_str, ws_path)
    
    # 写入配置文件
    sb_config_file = INSTALL_DIR / "sb.json"
    with open(str(sb_config_file), 'w') as f:
        f.write(config_str)
    
    write_debug_log(f"sing-box配置已写入文件: {sb_config_file}")
    
    return True

# 创建启动脚本
def create_startup_script(port_vm_ws):
    # 创建sing-box启动脚本
    sb_start_script = INSTALL_DIR / "start_sb.sh"
    with open(str(sb_start_script), 'w') as f:
        f.write(f'''#!/bin/bash
cd {INSTALL_DIR}
./sing-box run -c sb.json > sb.log 2>&1 & echo $! > sbpid.log
''')
    os.chmod(str(sb_start_script), 0o755)
    
    # 创建cloudflared启动脚本
    cf_start_script = INSTALL_DIR / "start_cf.sh"
    with open(str(cf_start_script), 'w') as f:
        f.write(f'''#!/bin/bash
cd {INSTALL_DIR}
./cloudflared tunnel --url http://localhost:{port_vm_ws}/$(cat config.json | grep -o '"uuid_str":"[^"]*"' | cut -d'"' -f4)-vm?ed=2048 --edge-ip-version auto --no-autoupdate --protocol http2 > argo.log 2>&1 & echo $! > sbargopid.log
''')
    os.chmod(str(cf_start_script), 0o755)
    
    write_debug_log("启动脚本已创建")

# 启动服务
def start_services():
    print("正在启动sing-box服务...")
    sb_start_script = INSTALL_DIR / "start_sb.sh"
    subprocess.run(str(sb_start_script), shell=True)
    
    print("正在启动cloudflared服务...")
    cf_start_script = INSTALL_DIR / "start_cf.sh"
    subprocess.run(str(cf_start_script), shell=True)
    
    print("等待服务启动...")
    time.sleep(3)  # 等待服务完全启动
    
    write_debug_log("服务已启动")

# 获取tunnel域名
def get_tunnel_domain():
    retry_count = 0
    domain = None
    
    while retry_count < 10:
        if os.path.exists(str(LOG_FILE)):
            try:
                with open(str(LOG_FILE), 'r') as f:
                    log_content = f.read()
                
                domain_match = re.search(r'https://([a-zA-Z0-9\-]+\.trycloudflare\.com)', log_content)
                if domain_match:
                    domain = domain_match.group(1)
                    write_debug_log(f"从日志中提取到域名: {domain}")
                    print(f"获取到临时域名: {domain}")
                    return domain
            except Exception as e:
                write_debug_log(f"读取日志文件出错: {e}")
        
        retry_count += 1
        print(f"正在等待tunnel域名生成 (尝试 {retry_count}/10)...")
        time.sleep(3)
    
    return None

# 主函数
def main():
    print_info()
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        action = sys.argv[1].lower()
        if action == "install":
            install()
            sys.exit(0)
        elif action in ["uninstall", "del", "delete", "remove"]:
            uninstall()
            sys.exit(0)
        elif action == "update" or action == "upgrade":
            upgrade()
            sys.exit(0)
        elif action == "status":
            if not check_status():
                pass
            sys.exit(0)
        elif action == "cat":
            # 新增cat命令，直接输出所有节点
            all_nodes_file = INSTALL_DIR / "allnodes.txt"
            if os.path.exists(str(all_nodes_file)):
                with open(str(all_nodes_file), 'r') as f:
                    all_links = f.read().splitlines()
                    for link in all_links:
                        print(link)
            else:
                print("\033[31m找不到节点文件，请先安装或运行status命令\033[0m")
            sys.exit(0)
        elif action == "testapi":
            # 测试API服务器连接
            test_api_connection()
            sys.exit(0)
        else:
            print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
            print("\033[36m│                \033[33m✨ 未知命令 ✨                          \033[36m│\033[0m")
            print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
            print(f"\033[36m│ \033[31m未知命令: {action}\033[0m")
            print_usage()
            print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
            sys.exit(1)
    else:
        if check_status():
            print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
            print("\033[36m│                \033[33m✨ ArgoSB 已在运行 ✨                    \033[36m│\033[0m")
            print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
            print("\033[36m│ \033[32mArgoSB脚本已在运行，如需重新安装请先卸载\033[0m")
            print("\033[36m│ \033[32m卸载命令: \033[33mpython3 agsb.py del\033[0m")
            print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
            sys.exit(0)
        else:
            print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
            print("\033[36m│               \033[33m✨ 开始安装 ArgoSB ✨                    \033[36m│\033[0m")
            print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
            install()

# 如果是主程序运行，执行main函数
if __name__ == "__main__":
    main() 
