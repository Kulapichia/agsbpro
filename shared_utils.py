# shared_utils.py
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
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path

# 全局变量，也可在此定义，但建议在主脚本中定义并传入
# INSTALL_DIR = Path.home() / ".agsb"

def check_nginx_installed():
    """检查系统中是否安装了Nginx"""
    if shutil.which('nginx'):
        try:
            result = subprocess.run(['nginx', '-v'], capture_output=True, text=True, stderr=subprocess.STDOUT)
            if "nginx version" in result.stdout:
                print(f"✅ 检测到 Nginx 已安装 ({result.stdout.strip()})")
                return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    print("ℹ️ 未检测到 Nginx。")
    return False

def http_get(url, timeout=10):
    """更健壮的HTTP GET请求，优先使用requests库"""
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        # verify=False 忽略SSL证书验证
        response = requests.get(url, headers=headers, timeout=timeout, verify=False)
        response.raise_for_status() # 如果状态码不是200-299，则抛出异常
        return response.text
    except ImportError:
        # Fallback to urllib if requests is not installed
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
            print(f"HTTP请求失败 (urllib): {url}, 错误: {e}")
            return None
    except Exception as e:
        print(f"HTTP请求失败 (requests): {url}, 错误: {e}")
        return None


def download_file(url, target_path, mode='wb'):
    """更健壮的文件下载，优先使用requests库"""
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        with requests.get(url, headers=headers, stream=True, verify=False) as r:
            r.raise_for_status()
            with open(target_path, mode) as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except ImportError:
        # Fallback to urllib
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
            print(f"下载文件失败 (urllib): {url}, 错误: {e}")
            return False
    except Exception as e:
        print(f"下载文件失败 (requests): {url}, 错误: {e}")
        return False

def download_binary(name, download_url, target_path):
    print(f"正在下载 {name}...")
    if download_file(download_url, target_path):
        print(f"{name} 下载成功!")
        os.chmod(target_path, 0o755)  # 设置可执行权限
        return True
    else:
        print(f"{name} 下载失败!")
        return False

def generate_vmess_link(config):
    """
    生成标准化的VMess链接。
    注意：port和aid应为字符串类型以符合V2RayN等客户端的规范。
    """
    vmess_obj = {
        "v": "2",
        "ps": config.get("ps", "ArgoSB"),
        "add": config.get("add", ""),
        "port": str(config.get("port", "443")),
        "id": config.get("id", ""),
        "aid": str(config.get("aid", "0")),
        "net": config.get("net", "ws"),
        "type": "none", # "type" 字段在Vmess over WS中通常为"none"
        "host": config.get("host", ""),
        "path": config.get("path", ""),
        "tls": config.get("tls", ""),
        "sni": config.get("sni", "")
    }
    # 清理空值字段，使链接更简洁
    vmess_obj_cleaned = {k: v for k, v in vmess_obj.items() if v}
    vmess_str = json.dumps(vmess_obj_cleaned, sort_keys=True, separators=(',', ':'))
    vmess_b64 = base64.b64encode(vmess_str.encode('utf-8')).decode('utf-8').rstrip("=")
    return f"vmess://{vmess_b64}"

def get_system_arch():
    """获取并标准化系统架构"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = "amd64" # 默认值

    if system == "linux":
        if "x86_64" in machine or "amd64" in machine:
            arch = "amd64"
        elif "aarch64" in machine or "arm64" in machine:
            arch = "arm64"
        elif "armv7" in machine:
            arch = "armv7"
    else:
        print(f"警告: 不完全支持的系统类型: {system}，将尝试使用默认架构 {arch}")

    return arch
