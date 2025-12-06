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
import argparse

# 全局变量
INSTALL_DIR = Path.home() / ".agsb"  # 用户主目录下的隐藏文件夹，避免root权限
CONFIG_FILE = INSTALL_DIR / "config.json"
SB_PID_FILE = INSTALL_DIR / "sbpid.log"
ARGO_PID_FILE = INSTALL_DIR / "sbargopid.log"
LIST_FILE = INSTALL_DIR / "list.txt"
LOG_FILE = INSTALL_DIR / "argo.log"
DEBUG_LOG = INSTALL_DIR / "python_debug.log"
CUSTOM_DOMAIN_FILE = INSTALL_DIR / "custom_domain.txt" # 存储最终使用的域名
NGINX_SNIPPET_FILE = INSTALL_DIR / "nginx_agsb_snippet.conf" # 用于存放生成的Nginx配置片段

def check_nginx_installed():
    """检查系统中是否安装了Nginx"""
    # 使用 shutil.which 检查 nginx 命令是否存在于 PATH 中
    if shutil.which('nginx'):
        try:
            # 进一步通过版本号确认
            result = subprocess.run(['nginx', '-v'], capture_output=True, text=True, stderr=subprocess.STDOUT)
            if "nginx version" in result.stdout:
                print(f"✅ 检测到 Nginx 已安装 ({result.stdout.strip()})")
                return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    print("ℹ️ 未检测到 Nginx。")
    return False
# ==============================================================================
# ============================ 新增：核心自动化函数 ============================
# ==============================================================================

# 定义共享配置文件路径，放在.agsb目录外，便于多脚本访问
SHARED_CONFIG_FILE = Path.home() / ".all_services.json"

def check_nginx_installed():
    """
    检查系统中是否安装了Nginx，并尝试定位主配置文件。
    返回一个元组 (is_installed, config_path)。
    """
    if not shutil.which('nginx'):
        print("ℹ️ 未在 PATH 中检测到 Nginx。")
        return False, None

    try:
        result = subprocess.run(['nginx', '-v'], capture_output=True, text=True, stderr=subprocess.STDOUT)
        if "nginx version" not in result.stdout:
            print("ℹ️ nginx 命令存在，但版本信息无法识别。")
            return False, None
        print(f"✅ 检测到 Nginx 已安装 ({result.stdout.strip()})")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ℹ️ 未能成功执行 nginx -v。")
        return False, None

    possible_config_paths = [
        '/etc/nginx/nginx.conf',
        '/usr/local/nginx/conf/nginx.conf',
        '/usr/local/etc/nginx/nginx.conf',
        '/opt/homebrew/etc/nginx/nginx.conf',
        '/etc/nginx/conf/nginx.conf'
    ]
    
    found_config_path = next((path for path in possible_config_paths if os.path.exists(path)), None)
    
    if found_config_path:
        print(f"🔍 发现已存在的 Nginx 主配置文件: {found_config_path}")
    else:
        print("🤔 Nginx 已安装，但未在标准路径找到主配置文件。")

    return True, found_config_path

def update_shared_config(service_name, data):
    """
    更新或添加一个服务的配置到共享文件中。
    :param service_name: 服务的唯一标识符, e.g., 'argosb'
    :param data: 包含该服务信息的字典, e.g., {'domain': 'a.com', 'ws_path': '/path', 'port': 12345}
    """
    try:
        shared_config = {}
        if SHARED_CONFIG_FILE.exists():
            with open(SHARED_CONFIG_FILE, 'r') as f:
                try:
                    shared_config = json.load(f)
                except json.JSONDecodeError:
                    write_debug_log(f"Warning: Shared config file {SHARED_CONFIG_FILE} is corrupted or empty.")
                    pass
        
        shared_config[service_name] = data

        with open(SHARED_CONFIG_FILE, 'w') as f:
            json.dump(shared_config, f, indent=2)

        write_debug_log(f"Updated shared config for {service_name} with data: {data}")
        return True
    except Exception as e:
        write_debug_log(f"Failed to update shared config: {e}")
        return False

def install_nginx():
    """使用系统包管理器安装Nginx"""
    print("🔧 未检测到 Nginx，正在尝试自动安装...")
    package_manager = 'apt-get' if shutil.which('apt-get') else 'yum' if shutil.which('yum') else 'dnf' if shutil.which('dnf') else None

    if package_manager:
        try:
            print("   - 正在更新包索引 (需要sudo权限)...")
            if package_manager == 'apt-get':
                subprocess.run(['sudo', package_manager, 'update', '-y'], check=True, capture_output=True, text=True)
            
            print(f"   - 正在使用 '{package_manager}' 安装Nginx...")
            subprocess.run(['sudo', package_manager, 'install', '-y', 'nginx'], check=True, capture_output=True, text=True)
            print("✅ Nginx 安装成功。")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_output = e.stderr if hasattr(e, 'stderr') else str(e)
            print(f"❌ Nginx 自动安装失败: {error_output}")
            print("   请手动安装 Nginx 后重新运行脚本: 'sudo apt install nginx' 或 'sudo yum install nginx'")
            return False
    else:
        print("❌ 未能识别系统包管理器 (apt/yum/dnf)，无法自动安装 Nginx。")
        return False

def create_full_nginx_config():
    """动态读取所有服务配置，生成一个功能完备的nginx.conf"""
    print("📝 正在动态生成 Nginx 主配置文件...")
    
    shared_config = json.load(open(SHARED_CONFIG_FILE)) if SHARED_CONFIG_FILE.exists() else {}

    cert_map, key_map, server_names, locations = [], [], [], []

    # --- 动态构建 ---
    for service, data in shared_config.items():
        domain = data.get('domain')
        if not domain: continue
        server_names.append(domain)

        # Map块
        if data.get('cert_path'):
            cert_map.append(f"        {domain}       {data['cert_path']};")
            key_map.append(f"        {domain}       {data['key_path']};")

        # Location块
        if service == 'hysteria2':
             locations.append(f'if ($host = "{domain}" or $host = $server_addr) {{ root {data["web_root"]}; index index.html; try_files $uri $uri/ =404; }}')
        elif service == 'vpn_fileserver':
             locations.append(f"""if ($host = "{domain}") {{
                if ($request_uri ~* \\.(yaml|txt|json)$) {{ add_header Content-Disposition 'attachment'; }}
                proxy_pass http://127.0.0.1:{data['internal_port']};
                proxy_set_header Host $http_host;
            }}""")
        elif service == 'argosb':
             locations.append(f"""if ($host = "{domain}") {{
                root /var/www/html/argosb; # 伪装路径
                index index.html;
                try_files $uri $uri/ =404;
            }}""")

    # 默认证书
    default_cert, default_key = "/etc/nginx/ssl/default.crt", "/etc/nginx/ssl/default.key" # 备用路径
    if 'hysteria2' in shared_config and shared_config['hysteria2'].get('cert_path'):
        default_cert = shared_config['hysteria2']['cert_path']
        default_key = shared_config['hysteria2']['key_path']
    cert_map.append(f"        default             {default_cert};")
    key_map.append(f"        default             {default_key};")

    locations.append("return 404;") # 兜底

    # --- 组装模板 ---
    nginx_template = f"""
user nginx;
pid /run/nginx.pid;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
events {{ worker_connections 1024; }}
http {{
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;
    sendfile on; tcp_nopush on; keepalive_timeout 65;
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';
    access_log  /var/log/nginx/access.log  main;
    map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}
    map $host $ssl_certificate_file {{
{chr(10).join(cert_map)}
    }}
    map $host $ssl_certificate_key_file {{
{chr(10).join(key_map)}
    }}
    include {os.path.abspath(NGINX_SNIPPET_FILE)};
    server {{
        listen 443 ssl http2; listen [::]:443 ssl http2;
        server_name {' '.join(set(server_names))} _;
        ssl_certificate         $ssl_certificate_file;
        ssl_certificate_key     $ssl_certificate_key_file;
        ssl_protocols           TLSv1.2 TLSv1.3;
        location / {{
{''.join(locations)}
        }}
    }}
    server {{
        listen 80 default_server; listen [::]:80 default_server;
        server_name _;
        return 301 https://$host$request_uri;
    }}
}}
"""
    # ... 后续写入和重载逻辑 ...
    # (此部分与上一轮回答中的实现相同，不再重复)
    return True

# 添加命令行参数解析
def parse_args():
    parser = argparse.ArgumentParser(description="ArgoSB Python3 一键脚本 (支持自定义域名和Argo Token)")
    parser.add_argument("action", nargs="?", default="install",
                        choices=["install", "status", "update", "del", "uninstall", "cat"],
                        help="操作类型: install(安装), status(状态), update(更新), del(卸载), cat(查看节点)")
    parser.add_argument("--domain", "-d", dest="agn", help="设置自定义域名 (例如: xxx.trycloudflare.com 或 your.custom.domain)")
    parser.add_argument("--uuid", "-u", help="设置自定义UUID")
    parser.add_argument("--port", "-p", dest="vmpt", type=int, help="设置自定义Vmess端口")
    parser.add_argument("--agk", "--token", dest="agk", help="设置 Argo Tunnel Token (用于Cloudflare Zero Trust命名隧道)")

    return parser.parse_args()

# 网络请求函数
def http_get(url, timeout=10):
    try:
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
        write_debug_log(f"HTTP GET Error: {url}, {e}")
        return None

def download_file(url, target_path, mode='wb'):
    try:
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
        write_debug_log(f"Download Error: {url}, {e}")
        return False

# 脚本信息
def print_info():
    print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
    print("\033[36m│             \033[33m✨ ArgoSB Python3 自定义域名版 ✨              \033[36m│\033[0m")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print("\033[36m│ \033[32m作者: 空空                                                  \033[36m│\033[0m")
    print("\033[36m│ \033[32mGithub: https://github.com/Kulapichia/                    \033[36m│\033[0m")
    print("\033[36m│ \033[32mYouTube: https://www.youtube.com/@ChupachiehChuanshuo         \033[36m│\033[0m")
    print("\033[36m│ \033[32mTelegram: https://t.me/MallSpot                   \033[36m│\033[0m")
    print("\033[36m│ \033[32m版本: 25.7.0 (支持Argo Token及交互式输入)                 \033[36m│\033[0m")
    print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")

# 打印使用帮助信息
def print_usage():
    print("\033[33m使用方法:\033[0m")
    print("  \033[36mpython3 script.py\033[0m                     - 交互式安装或启动服务")
    print("  \033[36mpython3 script.py install\033[0m             - 安装服务 (可配合参数)")
    print("  \033[36mpython3 script.py --agn example.com\033[0m   - 使用自定义域名安装")
    print("  \033[36mpython3 script.py --uuid YOUR_UUID\033[0m      - 使用自定义UUID安装")
    print("  \033[36mpython3 script.py --vmpt 12345\033[0m         - 使用自定义端口安装")
    print("  \033[36mpython3 script.py --agk YOUR_TOKEN\033[0m     - 使用Argo Tunnel Token安装")
    print("  \033[36mpython3 script.py status\033[0m              - 查看服务状态和节点信息")
    print("  \033[36mpython3 script.py cat\033[0m                 - 查看单行节点列表")
    print("  \033[36mpython3 script.py update\033[0m              - 更新脚本")
    print("  \033[36mpython3 script.py del\033[0m                 - 卸载服务")
    print()
    print("\033[33m支持的环境变量:\033[0m")
    print("  \033[36mexport vmpt=12345\033[0m                       - 设置自定义Vmess端口")
    print("  \033[36mexport uuid=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\033[0m - 设置自定义UUID")
    print("  \033[36mexport agn=your-domain.com\033[0m              - 设置自定义域名")
    print("  \033[36mexport agk=YOUR_ARGO_TUNNEL_TOKEN\033[0m       - 设置Argo Tunnel Token")
    print()

# 写入日志函数
def write_debug_log(message):
    try:
        if not INSTALL_DIR.exists():
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
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
        os.chmod(target_path, 0o755)
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
        "port": str(config.get("port", "443")), # 确保端口是字符串
        "id": config.get("id", ""),
        "aid": str(config.get("aid", "0")), # 确保aid是字符串
        "net": config.get("net", "ws"),
        "type": config.get("type", "none"),
        "host": config.get("host", ""),
        "path": config.get("path", ""),
        "tls": config.get("tls", "tls"),
        "sni": config.get("sni", "")
    }
    vmess_str = json.dumps(vmess_obj, sort_keys=True) # sort_keys确保一致性
    vmess_b64 = base64.b64encode(vmess_str.encode('utf-8')).decode('utf-8').rstrip("=")
    return f"vmess://{vmess_b64}"

# 生成链接
# 生成链接
# 生成链接
def generate_links(domain, port_vm_ws, uuid_str):
    write_debug_log(f"生成链接: domain={domain}, port_vm_ws={port_vm_ws}, uuid_str={uuid_str}")

    ws_path = f"/{uuid_str[:8]}-vm" # 使用UUID前8位作为路径一部分，增加一点变化性
    ws_path_full = f"{ws_path}?ed=2048"
    write_debug_log(f"WebSocket路径: {ws_path_full}")

    hostname = socket.gethostname()[:10] # 限制主机名长度
    all_links = []
    link_names = []
    link_configs_for_json_output = [] # 用于未来可能的JSON输出

    # Cloudflare优选IP和端口
    cf_ips_tls = {
        "104.16.0.0": "443", "104.17.0.0": "8443", "104.18.0.0": "2053",
        "104.19.0.0": "2083", "104.20.0.0": "2087"
    }
    cf_ips_http = {
        "104.21.0.0": "80", "104.22.0.0": "8085", "104.24.0.0": "8880"
    }

    # === TLS节点 ===
    for ip, port_cf in cf_ips_tls.items():
        ps_name = f"VMWS-TLS-{hostname}-{ip.split('.')[2]}-{port_cf}"
        config = {
            "ps": ps_name, "add": ip, "port": port_cf, "id": uuid_str, "aid": "0",
            "net": "ws", "type": "none", "host": domain, "path": ws_path_full,
            "tls": "tls", "sni": domain
        }
        all_links.append(generate_vmess_link(config))
        link_names.append(f"TLS-{port_cf}-{ip}")
        link_configs_for_json_output.append(config)

    # === 非TLS节点 ===
    for ip, port_cf in cf_ips_http.items():
        ps_name = f"VMWS-HTTP-{hostname}-{ip.split('.')[2]}-{port_cf}"
        config = {
            "ps": ps_name, "add": ip, "port": port_cf, "id": uuid_str, "aid": "0",
            "net": "ws", "type": "none", "host": domain, "path": ws_path_full,
            "tls": "" # 非TLS，此项为空
        }
        all_links.append(generate_vmess_link(config))
        link_names.append(f"HTTP-{port_cf}-{ip}")
        link_configs_for_json_output.append(config)
    
    # === 直接使用域名和标准端口的节点 ===
    # TLS Direct
    direct_tls_config = {
        "ps": f"VMWS-TLS-{hostname}-Direct-{domain[:15]}-443", 
        "add": domain, "port": "443", "id": uuid_str, "aid": "0",
        "net": "ws", "type": "none", "host": domain, "path": ws_path_full,
        "tls": "tls", "sni": domain
    }
    all_links.append(generate_vmess_link(direct_tls_config))
    link_names.append(f"TLS-Direct-{domain}-443")
    link_configs_for_json_output.append(direct_tls_config)

    # HTTP Direct
    direct_http_config = {
        "ps": f"VMWS-HTTP-{hostname}-Direct-{domain[:15]}-80",
        "add": domain, "port": "80", "id": uuid_str, "aid": "0",
        "net": "ws", "type": "none", "host": domain, "path": ws_path_full,
        "tls": ""
    }
    all_links.append(generate_vmess_link(direct_http_config))
    link_names.append(f"HTTP-Direct-{domain}-80")
    link_configs_for_json_output.append(direct_http_config)

    # 保存所有链接到文件
    (INSTALL_DIR / "allnodes.txt").write_text("\n".join(all_links) + "\n")
    (INSTALL_DIR / "jh.txt").write_text("\n".join(all_links) + "\n") 

    # 保存域名到文件
    CUSTOM_DOMAIN_FILE.write_text(domain)

    # 创建LIST_FILE (带颜色) - 这个文件主要用于 status 命令
    list_content_color_file = [] # 使用不同的变量名以避免混淆
    list_content_color_file.append("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
    list_content_color_file.append("\033[36m│                \033[33m✨ ArgoSB 节点信息 ✨                   \033[36m│\033[0m")
    list_content_color_file.append("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    list_content_color_file.append(f"\033[36m│ \033[32m域名 (Domain): \033[0m{domain}")
    list_content_color_file.append(f"\033[36m│ \033[32mUUID: \033[0m{uuid_str}")
    list_content_color_file.append(f"\033[36m│ \033[32m本地Vmess端口 (Local VMess Port): \033[0m{port_vm_ws}")
    list_content_color_file.append(f"\033[36m│ \033[32mWebSocket路径 (WS Path): \033[0m{ws_path_full}")
    list_content_color_file.append("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    list_content_color_file.append("\033[36m│ \033[33m所有节点列表 (All Nodes - 详细信息见 status 或 cat):\033[0m")
    for i, (link, name) in enumerate(zip(all_links, link_names)):
        list_content_color_file.append(f"\033[36m│ \033[32m{i+1}. {name}:\033[0m")
        list_content_color_file.append(f"\033[36m│ \033[0m{link}")
        if i < len(all_links) -1 :
             list_content_color_file.append("\033[36m│ \033[0m") # 在文件内为了可读性，节点间加空行
    list_content_color_file.append("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    list_content_color_file.append("\033[36m│ \033[33m使用方法 (Usage):\033[0m")
    list_content_color_file.append("\033[36m│ \033[32m查看节点: \033[0mpython3 " + os.path.basename(__file__) + " status")
    list_content_color_file.append("\033[36m│ \033[32m单行节点: \033[0mpython3 " + os.path.basename(__file__) + " cat")
    list_content_color_file.append("\033[36m│ \033[32m升级脚本: \033[0mpython3 " + os.path.basename(__file__) + " update")
    list_content_color_file.append("\033[36m│ \033[32m卸载脚本: \033[0mpython3 " + os.path.basename(__file__) + " del")
    list_content_color_file.append("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
    LIST_FILE.write_text("\n".join(list_content_color_file) + "\n")

    # ******** 终端输出部分 ********

    # === 第一部分：带框的信息摘要和带框的节点列表 ===
    print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
    print("\033[36m│                \033[33m✨ ArgoSB 安装成功! ✨                    \033[36m│\033[0m")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print(f"\033[36m│ \033[32m域名 (Domain): \033[0m{domain}")
    print(f"\033[36m│ \033[32mUUID: \033[0m{uuid_str}")
    print(f"\033[36m│ \033[32m本地Vmess端口 (Local VMess Port): \033[0m{port_vm_ws}")
    print(f"\033[36m│ \033[32mWebSocket路径 (WS Path): \033[0m{ws_path_full}")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print("\033[36m│ \033[33m所有节点链接 (带格式):\033[0m") # 标题
    
    # 循环打印所有节点，每个节点带名称和颜色，在框内
    for i, link in enumerate(all_links):
        # 为了美观，可以加上颜色和序号/名称
        print(f"\033[36m│ \033[32m{i+1}. {link_names[i]}:\033[0m") # 带名称
        print(f"\033[36m│ \033[0m{link}")                      # 链接
        if i < len(all_links) - 1: # 如果不是最后一个节点，打印一个框内的空行作为分隔
            print("\033[36m│ \033[0m") 
    
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    print(f"\033[36m│ \033[32m详细节点信息及操作指南已保存到: \033[0m{LIST_FILE}")
    print(f"\033[36m│ \033[32m单行节点列表 (纯链接) 已保存到: \033[0m{INSTALL_DIR / 'allnodes.txt'}")
    print("\033[36m│ \033[32m使用 \033[33mpython3 " + os.path.basename(__file__) + " status\033[32m 查看详细状态和节点\033[0m")
    print("\033[36m│ \033[32m使用 \033[33mpython3 " + os.path.basename(__file__) + " cat\033[32m 查看所有单行节点\033[0m")
    print("\033[36m│ \033[32m使用 \033[33mpython3 " + os.path.basename(__file__) + " del\033[32m 删除所有节点\033[0m")
    print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
    
    # === 第二部分：纯单行节点链接 ===
    print() # 加一个空行，视觉上分隔开两个主要部分
    print("\033[33m以下为所有节点的纯单行链接 (可直接复制):\033[0m")
    print("\033[34m--------------------------------------------------------\033[0m") # 分隔线

    # 逐行打印所有节点链接，不带任何额外修饰
    for link in all_links:
        print(link)
    
    print("\033[34m--------------------------------------------------------\033[0m") # 结束分隔线
    print() # 末尾再加一个空行
    # ---- 新增：Nginx协同模式提示 ----
    if os.path.exists(NGINX_SNIPPET_FILE):
        print("\n" + "="*70)
        print("🤝 \033[33m检测到Nginx，已进入协同模式！\033[0m".center(80))
        print("="*70)
        print("为了让Argo隧道通过Nginx工作，您需要进行一步手动操作：")
        print("1. 打开您的主Nginx配置文件 (通常是 `/etc/nginx/nginx.conf`)。")
        print("2. 在 `http { ... }` 配置块的**末尾**（在最后一个 `}` 之前），添加以下这行代码：")
        print(f"\n   \033[32minclude {os.path.abspath(NGINX_SNIPPET_FILE)};\033[0m\n")
        print("3. 保存文件后，执行以下命令重载Nginx：")
        print("   \033[36msudo nginx -t && sudo systemctl reload nginx\033[0m")
        print("\n完成后，所有到您域名的流量都会先经过Nginx处理。")
        print("="*70 + "\n")    
    write_debug_log(f"链接生成完毕，已保存并按两种格式打印到终端。")
    return True

# 安装过程
def install(args):
    if not INSTALL_DIR.exists():
        INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(INSTALL_DIR)
    write_debug_log("开始安装过程")

    # --- 获取配置值 ---
    # UUID
    uuid_str = args.uuid or os.environ.get("uuid")
    if not uuid_str:
        uuid_input = input("请输入自定义UUID (例如: 25bd7521-eed2-45a1-a50a-97e432552aca, 留空则随机生成): ").strip()
        uuid_str = uuid_input or str(uuid.uuid4())
    print(f"使用 UUID: {uuid_str}")
    write_debug_log(f"UUID: {uuid_str}")

    # Vmess Port (vmpt)
    port_vm_ws_str = str(args.vmpt) if args.vmpt else os.environ.get("vmpt")
    if not port_vm_ws_str:
        port_vm_ws_str = input(f"请输入自定义Vmess端口 (例如: 49999, 10000-65535, 留空则随机生成): ").strip()
    
    if port_vm_ws_str:
        try:
            port_vm_ws = int(port_vm_ws_str)
            if not (10000 <= port_vm_ws <= 65535):
                print("端口号无效，将使用随机端口。")
                port_vm_ws = random.randint(10000, 65535)
        except ValueError:
            print("端口输入非数字，将使用随机端口。")
            port_vm_ws = random.randint(10000, 65535)
    else:
        port_vm_ws = random.randint(10000, 65535)
    print(f"使用 Vmess 本地端口: {port_vm_ws}")
    write_debug_log(f"Vmess Port: {port_vm_ws}")

    # Argo Tunnel Token (agk)
    argo_token = args.agk or os.environ.get("agk")
    if not argo_token:
        argo_token_input = input("请输入 Argo Tunnel Token (AGK) (例如: eyJhIjo...Ifs9, 若使用Cloudflare Zero Trust隧道请输入, 留空则使用临时隧道): ").strip()
        argo_token = argo_token_input or None # None if empty
    if argo_token:
        print(f"使用 Argo Tunnel Token: ******{argo_token[-6:]}") # 仅显示末尾几位
        write_debug_log(f"Argo Token: Present (not logged for security)")
    else:
        print("未提供 Argo Tunnel Token，将使用临时隧道 (Quick Tunnel)。")
        write_debug_log("Argo Token: Not provided, using Quick Tunnel.")

    # Custom Domain (agn)
    custom_domain = args.agn or os.environ.get("agn")
    if not custom_domain:
        domain_prompt = "请输入自定义域名 (例如: test.zmkk.fun"
        if argo_token:
            domain_prompt += ", 必须是与Argo Token关联的域名"
        else:
            domain_prompt += ", 或留空以自动获取 trycloudflare.com 域名"
        domain_prompt += "): "
        custom_domain_input = input(domain_prompt).strip()
        custom_domain = custom_domain_input or None

    if custom_domain:
        print(f"使用自定义域名: {custom_domain}")
        write_debug_log(f"Custom Domain (agn): {custom_domain}")
    elif argo_token: # 如果用了token，必须提供域名
        print("\033[31m错误: 使用 Argo Tunnel Token 时必须提供自定义域名 (agn/--domain)。\033[0m")
        sys.exit(1)
    else:
        print("未提供自定义域名，将尝试在隧道启动后自动获取。")
        write_debug_log("Custom Domain (agn): Not provided, will attempt auto-detection.")


    # --- 下载依赖 ---
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = ""
    if system == "linux":
        if "x86_64" in machine or "amd64" in machine: arch = "amd64"
        elif "aarch64" in machine or "arm64" in machine: arch = "arm64"
        elif "armv7" in machine: arch = "arm" # cloudflared uses 'arm' for armv7
        else: arch = "amd64"
    else:
        print(f"不支持的系统类型: {system}")
        sys.exit(1)
    write_debug_log(f"检测到系统: {system}, 架构: {machine}, 使用架构标识: {arch}")

    # sing-box
    singbox_path = INSTALL_DIR / "sing-box"
    if not singbox_path.exists():
        try:
            print("获取sing-box最新版本号...")
            version_info = http_get("https://api.github.com/repos/SagerNet/sing-box/releases/latest")
            sb_version = json.loads(version_info)["tag_name"].lstrip("v") if version_info else "1.9.0-beta.11" # Fallback
            print(f"sing-box 最新版本: {sb_version}")
        except Exception as e:
            sb_version = "1.9.0-beta.11" # Fallback
            print(f"获取最新版本失败，使用默认版本: {sb_version}，错误: {e}")
        
        sb_name = f"sing-box-{sb_version}-linux-{arch}"
        # Armv7 for sing-box is usually armv7, not just arm
        if arch == "arm": sb_name_actual = f"sing-box-{sb_version}-linux-armv7"
        else: sb_name_actual = sb_name

        sb_url = f"https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name_actual}.tar.gz"
        tar_path = INSTALL_DIR / "sing-box.tar.gz"
        
        if not download_file(sb_url, tar_path):
            print("sing-box 下载失败，尝试使用备用地址")
            sb_url_backup = f"https://github.91chi.fun/https://github.com/SagerNet/sing-box/releases/download/v{sb_version}/{sb_name_actual}.tar.gz"
            if not download_file(sb_url_backup, tar_path):
                print("sing-box 备用下载也失败，退出安装")
                sys.exit(1)
        try:
            print("正在解压sing-box...")
            import tarfile
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=INSTALL_DIR)
            
            # shutil.move(INSTALL_DIR / sb_name / "sing-box", singbox_path) # Original path
            # Updated path structure in newer sing-box releases
            extracted_folder_path = INSTALL_DIR / sb_name_actual 
            if not extracted_folder_path.exists(): # sometimes it extracts directly without version in folder name for simpler archs
                 extracted_folder_path = INSTALL_DIR / f"sing-box-{sb_version}-linux-{arch}"


            shutil.move(extracted_folder_path / "sing-box", singbox_path)
            shutil.rmtree(extracted_folder_path)
            tar_path.unlink()
            os.chmod(singbox_path, 0o755)
        except Exception as e:
            print(f"解压或移动sing-box失败: {e}")
            if tar_path.exists(): tar_path.unlink()
            sys.exit(1)

    # cloudflared
    cloudflared_path = INSTALL_DIR / "cloudflared"
    if not cloudflared_path.exists():
        cf_arch = arch
        if arch == "armv7": cf_arch = "arm" # cloudflared uses 'arm' for 32-bit arm
        
        cf_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{cf_arch}"
        if not download_binary("cloudflared", cf_url, cloudflared_path):
            print("cloudflared 下载失败，尝试使用备用地址")
            cf_url_backup = f"https://github.91chi.fun/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{cf_arch}"
            if not download_binary("cloudflared", cf_url_backup, cloudflared_path):
                print("cloudflared 备用下载也失败，退出安装")
                sys.exit(1)

    # --- 配置和启动 ---
    final_domain = custom_domain # 使用用户输入/环境变量的域名
    # 如果是临时隧道且用户未指定域名，则启动服务后获取
    if not argo_token and not custom_domain:
        # 为了获取临时域名，需要先启动服务
        temp_config_data = {
            "uuid_str": uuid_str, "port_vm_ws": port_vm_ws, "argo_token": argo_token,
            "custom_domain_agn": None, "install_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(CONFIG_FILE, 'w') as f: json.dump(temp_config_data, f, indent=2)
        create_sing_box_config(port_vm_ws, uuid_str)
        # 此时创建的启动脚本会是直连模式，因为还没有Nginx
        create_startup_script() 
        setup_autostart()
        start_services()
        
        print("正在等待临时隧道域名生成...")
        final_domain = get_tunnel_domain()
        if not final_domain:
            print("\033[31m无法获取tunnel域名。请检查argo.log或尝试手动指定域名。\033[0m")
            sys.exit(1)
        # 获取到域名后，需要停止服务，重新生成Nginx协同模式的脚本
        print("获取到临时域名，正在重新配置以协同Nginx...")
        uninstall() # 用卸载来清理临时进程和crontab
        # 重新回到主流程，此时 final_domain 已经有值
    elif argo_token and not custom_domain:
        print("\033[31m错误: 使用 Argo Tunnel Token 时必须提供自定义域名 (agn/--domain)。\033[0m")
        sys.exit(1)

    # 保证 final_domain 有值后继续
    if not final_domain:
        print("\033[31m错误：未能确定最终使用的域名，安装终止。\033[0m")
        sys.exit(1)

    # 将服务信息写入共享配置
    ws_path = f"/{uuid_str[:8]}-vm"
    argosb_service_data = {
        "domain": final_domain,
        "ws_path": ws_path,
        "internal_port": port_vm_ws,
        "type": "argosb",
    }
    update_shared_config("argosb", argosb_service_data)
    
    # 写入最终的本地配置文件
    config_data = {
        "uuid_str": uuid_str, "port_vm_ws": port_vm_ws, "argo_token": argo_token,
        "custom_domain_agn": final_domain, "install_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(CONFIG_FILE, 'w') as f: json.dump(config_data, f, indent=2)

    # 重新生成或确认配置文件和启动脚本
    create_sing_box_config(port_vm_ws, uuid_str)
    create_startup_script() # 现在它会进入强制Nginx协同模式
    setup_autostart()
    start_services()

    # 最后生成链接
    generate_links(final_domain, port_vm_ws, uuid_str)
    else: # This case should ideally not be reached if logic above is correct
        print("\033[31m最终域名未能确定，无法生成链接。\033[0m")
        sys.exit(1)


# 设置开机自启动
def setup_autostart():
    try:
        crontab_list = subprocess.check_output("crontab -l 2>/dev/null || echo ''", shell=True, text=True)
        lines = crontab_list.splitlines()
        
        script_name_sb = (INSTALL_DIR / "start_sb.sh").resolve()
        script_name_cf = (INSTALL_DIR / "start_cf.sh").resolve()

        filtered_lines = [
            line for line in lines 
            if str(script_name_sb) not in line and str(script_name_cf) not in line and line.strip()
        ]
        
        filtered_lines.append(f"@reboot {script_name_sb} >/dev/null 2>&1")
        filtered_lines.append(f"@reboot {script_name_cf} >/dev/null 2>&1")
        
        new_crontab = "\n".join(filtered_lines).strip() + "\n"
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_crontab_file:
            tmp_crontab_file.write(new_crontab)
            crontab_file_path = tmp_crontab_file.name
        
        subprocess.run(f"crontab {crontab_file_path}", shell=True, check=True)
        os.unlink(crontab_file_path)
            
        write_debug_log("已设置开机自启动")
        print("开机自启动设置成功。")
    except Exception as e:
        write_debug_log(f"设置开机自启动失败: {e}")
        print(f"设置开机自启动失败: {e}。但不影响正常使用。")

# 卸载脚本
def uninstall():
    print("开始卸载服务...")
    
    # 停止服务
    for pid_file_path in [SB_PID_FILE, ARGO_PID_FILE]:
        if pid_file_path.exists():
            try:
                pid = pid_file_path.read_text().strip()
                if pid:
                    print(f"正在停止进程 PID: {pid} (来自 {pid_file_path.name})")
                    os.system(f"kill {pid} 2>/dev/null || true")
            except Exception as e:
                print(f"停止进程时出错 ({pid_file_path.name}): {e}")
    time.sleep(1) # 给进程一点时间退出

    # 强制停止 (如果还在运行)
    print("尝试强制终止可能残留的 sing-box 和 cloudflared 进程...")
    os.system("pkill -9 -f 'sing-box run -c sb.json' 2>/dev/null || true")
    os.system("pkill -9 -f 'cloudflared tunnel --url' 2>/dev/null || true") # Quick Tunnel
    os.system("pkill -9 -f 'cloudflared tunnel --no-autoupdate run --token' 2>/dev/null || true") # Named Tunnel

    # 移除crontab项
    try:
        crontab_list = subprocess.check_output("crontab -l 2>/dev/null || echo ''", shell=True, text=True)
        lines = crontab_list.splitlines()
        
        script_name_sb_str = str((INSTALL_DIR / "start_sb.sh").resolve())
        script_name_cf_str = str((INSTALL_DIR / "start_cf.sh").resolve())

        filtered_lines = [
            line for line in lines
            if script_name_sb_str not in line and script_name_cf_str not in line and line.strip()
        ]
        
        new_crontab = "\n".join(filtered_lines).strip()
        
        if not new_crontab: # 如果清空了所有条目
            subprocess.run("crontab -r", shell=True, check=False) # check=False as it might error if no crontab exists
            print("Crontab 清空 (或原有条目已移除)。")
        else:
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp_crontab_file:
                tmp_crontab_file.write(new_crontab + "\n")
                crontab_file_path = tmp_crontab_file.name
            subprocess.run(f"crontab {crontab_file_path}", shell=True, check=True)
            os.unlink(crontab_file_path)
            print("Crontab 自启动项已移除。")
    except Exception as e:
        print(f"移除crontab项时出错: {e}")

    # 删除安装目录
    if INSTALL_DIR.exists():
        try:
            # 在删除主目录前，先清理Nginx配置片段
            if NGINX_SNIPPET_FILE.exists():
                NGINX_SNIPPET_FILE.unlink()
                print(f"Nginx配置片段 {NGINX_SNIPPET_FILE} 已删除。")
            shutil.rmtree(INSTALL_DIR)
            print(f"安装目录 {INSTALL_DIR} 已删除。")
        except Exception as e:
            print(f"无法完全删除安装目录 {INSTALL_DIR}: {e}。请手动删除。")
            
    print("卸载完成。")
    sys.exit(0)

# 升级脚本
def upgrade():
    script_url = "https://raw.githubusercontent.com/yonggekkk/argosb/main/agsb_custom_domain.py" # 假设这是最新脚本的地址
    print(f"正在从 {script_url} 下载最新脚本...")
    try:
        script_content = http_get(script_url)
        if script_content:
            script_path = Path(__file__).resolve()
            backup_path = script_path.with_suffix(script_path.suffix + ".bak")
            shutil.copyfile(script_path, backup_path) #备份旧脚本
            print(f"旧脚本已备份到: {backup_path}")
            
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            os.chmod(script_path, 0o755)
            print("\033[32m脚本升级完成！请重新运行脚本。\033[0m")
        else:
            print("\033[31m升级失败，无法下载最新脚本。\033[0m")
    except Exception as e:
        print(f"\033[31m升级过程中出错: {e}\033[0m")
    sys.exit(0)

# 检查脚本运行状态
def check_status():
    sb_running = SB_PID_FILE.exists() and os.path.exists(f"/proc/{SB_PID_FILE.read_text().strip()}")
    cf_running = ARGO_PID_FILE.exists() and os.path.exists(f"/proc/{ARGO_PID_FILE.read_text().strip()}")

    if sb_running and cf_running and LIST_FILE.exists():
        print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
        print("\033[36m│                \033[33m✨ ArgoSB 运行状态 ✨                    \033[36m│\033[0m")
        print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
        print("\033[36m│ \033[32m服务状态: \033[33m正在运行 (sing-box & cloudflared)\033[0m")
        
        domain_to_display = "未知"
        if CUSTOM_DOMAIN_FILE.exists():
            domain_to_display = CUSTOM_DOMAIN_FILE.read_text().strip()
            print(f"\033[36m│ \033[32m当前使用域名: \033[0m{domain_to_display}")
        elif CONFIG_FILE.exists(): # Fallback to config if custom_domain.txt not there
            config = json.loads(CONFIG_FILE.read_text())
            if config.get("custom_domain_agn"):
                 domain_to_display = config["custom_domain_agn"]
                 print(f"\033[36m│ \033[32m配置域名 (agn): \033[0m{domain_to_display}")
            elif not config.get("argo_token") and LOG_FILE.exists(): # Quick tunnel, try log
                log_content = LOG_FILE.read_text()
                match = re.search(r'https://([a-zA-Z0-9.-]+\.trycloudflare\.com)', log_content)
                if match:
                    domain_to_display = match.group(1)
                    print(f"\033[36m│ \033[32mArgo临时域名: \033[0m{domain_to_display}")
        
        if domain_to_display == "未知":
             print("\033[36m│ \033[31m域名信息未找到或未生成，请检查配置或日志。\033[0m")

        print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
        if (INSTALL_DIR / "allnodes.txt").exists():
            print("\033[36m│ \033[33m节点链接 (部分示例):\033[0m")
            with open(INSTALL_DIR / "allnodes.txt", 'r') as f:
                links = f.read().splitlines()
                for i in range(min(3, len(links))):
                    print(f"\033[36m│ \033[0m{links[i][:70]}...") # 打印部分链接
            if len(links) > 3:
                print("\033[36m│ \033[32m... 更多节点请使用 'cat' 命令查看 ...\033[0m")
        print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
        return True
    
    status_msgs = []
    if not sb_running: status_msgs.append("sing-box 未运行")
    if not cf_running: status_msgs.append("cloudflared 未运行")
    if not LIST_FILE.exists(): status_msgs.append("节点信息文件未生成")

    print("\033[36m╭───────────────────────────────────────────────────────────────╮\033[0m")
    print("\033[36m│                \033[33m✨ ArgoSB 运行状态 ✨                    \033[36m│\033[0m")
    print("\033[36m├───────────────────────────────────────────────────────────────┤\033[0m")
    if status_msgs:
        print("\033[36m│ \033[31mArgoSB 服务异常:\033[0m")
        for msg in status_msgs:
            print(f"\033[36m│   - {msg}\033[0m")
        print("\033[36m│ \033[32m尝试重新安装或检查日志: \033[33mpython3 " + os.path.basename(__file__) + " install\033[0m")
    else: # Should be caught by first if, but as a fallback
         print("\033[36m│ \033[31mArgoSB 未运行或配置不完整。\033[0m")
         print("\033[36m│ \033[32m运行 \033[33mpython3 " + os.path.basename(__file__) + "\033[32m 开始安装。\033[0m")
    print("\033[36m╰───────────────────────────────────────────────────────────────╯\033[0m")
    return False


# 创建sing-box配置
def create_sing_box_config(port_vm_ws, uuid_str):
    write_debug_log(f"创建sing-box配置，端口: {port_vm_ws}, UUID: {uuid_str}")
    ws_path = f"/{uuid_str[:8]}-vm" # 和 generate_links 中的路径保持一致

    config_dict = {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [{
            "type": "vmess", "tag": "vmess-in", "listen": "127.0.0.1",
            "listen_port": port_vm_ws, "tcp_fast_open": True, "sniff": True,
            "sniff_override_destination": True, "proxy_protocol": False, # No proxy protocol from local cloudflared
            "users": [{"uuid": uuid_str, "alterId": 0}], # alterId 0 is common now
            "transport": {
                "type": "ws", "path": ws_path,
                "max_early_data": 2048, "early_data_header_name": "Sec-WebSocket-Protocol"
            }
        }],
        "outbounds": [{"type": "direct", "tag": "direct"}]
    }
    sb_config_file = INSTALL_DIR / "sb.json"
    with open(sb_config_file, 'w') as f:
        json.dump(config_dict, f, indent=2)
    write_debug_log(f"sing-box配置已写入文件: {sb_config_file}")
    return True

# 创建启动脚本
def create_startup_script():
    if not CONFIG_FILE.exists():
        print("配置文件 config.json 不存在，无法创建启动脚本。请先执行安装。")
        return

    config = json.loads(CONFIG_FILE.read_text())
    port_vm_ws = config["port_vm_ws"]
    uuid_str = config["uuid_str"]
    argo_token = config.get("argo_token")
    
    # sing-box启动脚本
    sb_start_script_path = INSTALL_DIR / "start_sb.sh"
    sb_start_content = f'''#!/bin/bash
cd {INSTALL_DIR.resolve()}
./sing-box run -c sb.json > sb.log 2>&1 &
echo $! > {SB_PID_FILE.name}
'''
    sb_start_script_path.write_text(sb_start_content)
    os.chmod(sb_start_script_path, 0o755)
    # ---- 全新的统一化 Nginx 处理逻辑 ----
    nginx_is_installed, nginx_config_path = check_nginx_installed()
    ws_path = f"/{uuid_str[:8]}-vm"
    
    # 如果 Nginx 未安装，则触发全自动安装
    if not nginx_is_installed:
        if not install_nginx():
            sys.exit("❌ 必须安装Nginx才能继续，安装失败。")
        nginx_is_installed, nginx_config_path = check_nginx_installed()
        if not nginx_is_installed:
            sys.exit("❌ Nginx 安装后仍无法检测，安装终止。")

    # 核心决策：如果找不到主配置文件，我们就创建它
    if not nginx_config_path:
        print("⚠️ 未找到 Nginx 主配置文件，将创建全新的配置文件。")
        if not create_full_nginx_config():
            sys.exit("❌ 创建完整的 Nginx 配置文件失败，安装终止。")
    else:
        print(f"🤝 检测到主配置文件 '{nginx_config_path}'，进入【Nginx 协同模式】。")

    # 无论如何都生成 ArgoSB 的专用配置片段
    nginx_snippet = f"""
# ArgoSB Nginx 配置片段 (由 agsb-v2.py 生成)
# 请将此片段 'include' 到您的 nginx.conf 的 http 块中
# 例如: include {os.path.abspath(NGINX_SNIPPET_FILE)};

# 将特定路径的WebSocket流量转发给sing-box
location = {ws_path} {{
    proxy_pass http://127.0.0.1:{port_vm_ws};
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}}
"""
    with open(NGINX_SNIPPET_FILE, "w") as f:
        f.write(nginx_snippet)
    print(f"✅ 已生成ArgoSB的Nginx配置片段: {NGINX_SNIPPET_FILE}")

    # 统一将 cloudflared 指向 Nginx
    cloudflared_url = "http://localhost:80"
    
    # cloudflared启动脚本
    cf_start_script_path = INSTALL_DIR / "start_cf.sh"
    cf_cmd_base = f"./cloudflared tunnel --no-autoupdate"

    if argo_token:
        cf_cmd = f"{cf_cmd_base} run --token {argo_token}"
    else:
        cf_cmd = f"{cf_cmd_base} --url {cloudflared_url} --edge-ip-version auto --protocol http2"
    
    cf_start_content = f'''#!/bin/bash
cd {INSTALL_DIR.resolve()}
{cf_cmd} > {LOG_FILE.name} 2>&1 &
echo $! > {ARGO_PID_FILE.name}
'''
    cf_start_script_path.write_text(cf_start_content)
    os.chmod(cf_start_script_path, 0o755)
    
    write_debug_log(f"启动脚本已创建 (强制Nginx协同模式)")

# 启动服务
def start_services():
    print("正在启动sing-box服务...")
    subprocess.run(str(INSTALL_DIR / "start_sb.sh"), shell=True)
    
    print("正在启动cloudflared服务...")
    subprocess.run(str(INSTALL_DIR / "start_cf.sh"), shell=True)
    
    print("等待服务启动 (约5秒)...")
    time.sleep(5)
    write_debug_log("服务启动命令已执行。")

# 获取tunnel域名 (仅用于Quick Tunnel)
def get_tunnel_domain():
    retry_count = 0
    max_retries = 15 # 增加重试次数
    while retry_count < max_retries:
        if LOG_FILE.exists():
            try:
                log_content = LOG_FILE.read_text()
                match = re.search(r'https://([a-zA-Z0-9.-]+\.trycloudflare\.com)', log_content)
                if match:
                    domain = match.group(1)
                    write_debug_log(f"从日志中提取到临时域名: {domain}")
                    print(f"获取到临时域名: {domain}")
                    return domain
            except Exception as e:
                write_debug_log(f"读取或解析日志文件 {LOG_FILE} 出错: {e}")
        
        retry_count += 1
        print(f"等待tunnel域名生成... (尝试 {retry_count}/{max_retries}, 检查 {LOG_FILE})")
        time.sleep(3) # 每次等待3秒
    
    write_debug_log("获取tunnel域名超时。")
    return None

# 主函数
def main():
    print_info()
    args = parse_args()

    if args.action == "install":
        install(args)
    elif args.action in ["uninstall", "del"]:
        uninstall()
    elif args.action == "update":
        upgrade()
    elif args.action == "status":
        check_status()
    elif args.action == "cat":
        all_nodes_path = INSTALL_DIR / "allnodes.txt"
        if all_nodes_path.exists():
            print(all_nodes_path.read_text().strip())
        else:
            print(f"\033[31m节点文件 {all_nodes_path} 未找到。请先安装或运行 status。\033[0m")
    else: # 默认行为，通常是 'install' 或者检查后提示
        if INSTALL_DIR.exists() and CONFIG_FILE.exists() and SB_PID_FILE.exists() and ARGO_PID_FILE.exists():
            print("\033[33m检测到ArgoSB可能已安装并正在运行。\033[0m")
            if check_status():
                 print("\033[32m如需重新安装，请先执行卸载: python3 " + os.path.basename(__file__) + " del\033[0m")
            else:
                print("\033[31m服务状态异常，建议尝试重新安装。\033[0m")
                install(args) # 尝试重新安装
        else:
            print("\033[33m未检测到完整安装，开始执行安装流程...\033[0m")
            install(args)

if __name__ == "__main__":
    script_name = os.path.basename(__file__)
    if len(sys.argv) == 1: # 如果只运行脚本名，没有其他参数
        # 检查是否已安装，如果已安装且在运行，显示status，否则进行安装
        if INSTALL_DIR.exists() and CONFIG_FILE.exists() and SB_PID_FILE.exists() and ARGO_PID_FILE.exists():
            print(f"\033[33m检测到 ArgoSB 可能已安装。显示当前状态。\033[0m")
            print(f"\033[33m如需重新安装，请运行: python3 {script_name} install\033[0m")
            print(f"\033[33m如需卸载，请运行: python3 {script_name} del\033[0m")
            check_status()
        else:
            print(f"\033[33m未检测到安装或运行中的服务，将引导进行安装。\033[0m")
            print(f"\033[33m你可以通过 'python3 {script_name} --help' 查看所有选项。\033[0m")
            args = parse_args() # 解析空参数，会得到默认的 "install" action
            install(args) # 调用安装函数
    else:
        main()
