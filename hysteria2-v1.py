#!/usr/bin/env python3
import os
import sys
import json
import ssl
import shutil
import platform
import urllib.request
import urllib.parse
import subprocess
import socket
import time
import argparse
from pathlib import Path

def get_user_home():
    """获取用户主目录"""
    return str(Path.home())

def get_system_info():
    """获取系统信息"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    # 系统映射
    os_map = {
        'linux': 'linux',
        'darwin': 'darwin',  # macOS
        'windows': 'windows'
    }
    
    # 架构映射
    arch_map = {
        'x86_64': 'amd64',
        'amd64': 'amd64',
        'aarch64': 'arm64',
        'arm64': 'arm64',
        'i386': '386',
        'i686': '386'
    }
    
    os_name = os_map.get(system, 'linux')
    arch = arch_map.get(machine, 'amd64')
    
    return os_name, arch

def check_port_available(port):
    """检查端口是否可用（仅使用socket）"""
    try:
        # 同时测试 TCP 和 UDP
        # TCP 检查
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', port))
            if result == 0:  # 端口已被占用
                return False
                
        # UDP 检查
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            try:
                s.bind(('', port))
                return True
            except:
                return False
                
        return True
    except:
        # 如果有任何异常，保守起见返回端口不可用
        return False

def is_port_listening(port):
    """检查端口是否已经在监听（服务是否已启动）"""
    try:
        # 尝试连接到端口
        # 由于 Hysteria 使用 UDP，我们检查 UDP 端口
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        
        # 尝试发送一个数据包到端口
        # 如果端口打开，send不会抛出异常
        try:
            sock.sendto(b"ping", ('127.0.0.1', port))
            try:
                sock.recvfrom(1024)  # 尝试接收响应
                return True
            except socket.timeout:
                # 没收到响应但也没报错，可能仍在监听
                return True
        except:
            pass
            
        # 另一种检查方式：尝试绑定端口，如果失败说明端口已被占用
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.bind(('', port))
            test_sock.close()
            return False  # 能成功绑定说明端口未被占用
        except:
            return True  # 无法绑定说明端口已被占用
            
        return False
    except:
        return False
    finally:
        try:
            sock.close()
        except:
            pass

def check_process_running(pid_file):
    """检查进程是否在运行"""
    if not os.path.exists(pid_file):
        return False
        
    try:
        with open(pid_file, 'r') as f:
            pid = f.read().strip()
            
        if not pid:
            return False
            
        # 尝试发送信号0检查进程是否存在
        try:
            os.kill(int(pid), 0)
            return True
        except:
            return False
    except:
        return False

def create_directories():
    """创建必要的目录"""
    home = get_user_home()
    dirs = [
        f"{home}/.hysteria2",
        f"{home}/.hysteria2/cert",
        f"{home}/.hysteria2/config",
        f"{home}/.hysteria2/logs"
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
    return dirs[0]

def download_file(url, save_path, max_retries=3):
    """下载文件，带重试机制"""
    for i in range(max_retries):
        try:
            print(f"正在下载... (尝试 {i+1}/{max_retries})")
            urllib.request.urlretrieve(url, save_path)
            return True
        except Exception as e:
            print(f"下载失败: {e}")
            if i < max_retries - 1:
                time.sleep(2)  # 等待2秒后重试
            continue
    return False

def get_latest_version():
    """返回固定的最新版本号 v2.6.1"""
    return "v2.6.1"

def get_download_filename(os_name, arch):
    """根据系统和架构返回正确的文件名"""
    # windows 需要 .exe
    if os_name == 'windows':
        if arch == 'amd64':
            return 'hysteria-windows-amd64.exe'
        elif arch == '386':
            return 'hysteria-windows-386.exe'
        elif arch == 'arm64':
            return 'hysteria-windows-arm64.exe'
        else:
            return f'hysteria-windows-{arch}.exe'
    else:
        return f'hysteria-{os_name}-{arch}'

def verify_binary(binary_path):
    """验证二进制文件是否有效（简化版）"""
    try:
        # 检查文件是否存在
        if not os.path.exists(binary_path):
            return False
            
        # 检查文件大小（至少5MB - hysteria一般大于10MB）
        if os.path.getsize(binary_path) < 5 * 1024 * 1024:
            return False
            
        # 设置文件为可执行
        os.chmod(binary_path, 0o755)
        
        # 返回成功
        return True
    except:
        return False

def download_hysteria2(base_dir):
    """下载Hysteria2二进制文件，使用简化链接和验证方式"""
    try:
        version = get_latest_version()
        os_name, arch = get_system_info()
        filename = get_download_filename(os_name, arch)
        
        # 只使用原始GitHub链接，避免镜像问题
        url = f"https://github.com/apernet/hysteria/releases/download/app/{version}/{filename}"
        
        binary_path = f"{base_dir}/hysteria"
        if os_name == 'windows':
            binary_path += '.exe'
        
        print(f"正在下载 Hysteria2 {version}...")
        print(f"系统类型: {os_name}, 架构: {arch}, 文件名: {filename}")
        print(f"下载链接: {url}")
        
        # 使用wget下载
        try:
            has_wget = shutil.which('wget') is not None
            has_curl = shutil.which('curl') is not None
            
            if has_wget:
                print("使用wget下载...")
                subprocess.run(['wget', '--tries=3', '--timeout=15', '-O', binary_path, url], check=True)
            elif has_curl:
                print("使用curl下载...")
                subprocess.run(['curl', '-L', '--connect-timeout', '15', '-o', binary_path, url], check=True)
            else:
                print("系统无wget/curl，尝试使用Python下载...")
                urllib.request.urlretrieve(url, binary_path)
                
            # 验证下载
            if not verify_binary(binary_path):
                raise Exception("下载的文件无效")
                
            print(f"下载成功: {binary_path}, 大小: {os.path.getsize(binary_path)/1024/1024:.2f}MB")
            return binary_path, version
            
        except Exception as e:
            print(f"自动下载失败: {e}")
            print("请按照以下步骤手动下载:")
            print(f"1. 访问 https://github.com/apernet/hysteria/releases/tag/app/{version}")
            print(f"2. 下载 {filename} 文件")
            print(f"3. 将文件重命名为 hysteria (不要加后缀) 并移动到 {base_dir}/ 目录")
            print(f"4. 执行: chmod +x {base_dir}/hysteria")
            
            # 询问用户文件是否已放置
            while True:
                user_input = input("已完成手动下载和放置? (y/n): ").lower()
                if user_input == 'y':
                    # 检查文件是否存在
                    if os.path.exists(binary_path) and verify_binary(binary_path):
                        print("文件验证成功，继续安装...")
                        return binary_path, version
                    else:
                        print(f"文件不存在或无效，请确保放在 {binary_path} 位置。")
                elif user_input == 'n':
                    print("中止安装。")
                    sys.exit(1)
    
    except Exception as e:
        print(f"下载错误: {e}")
        sys.exit(1)

def get_ip_address():
    """获取本机IP地址（优先获取公网IP，如果失败则使用本地IP）"""
    # 首先尝试获取公网IP
    try:
        # 尝试从公共API获取公网IP
        with urllib.request.urlopen('https://api.ipify.org', timeout=5) as response:
            public_ip = response.read().decode('utf-8')
            if public_ip and len(public_ip) > 0:
                return public_ip
    except:
        try:
            # 备选API
            with urllib.request.urlopen('https://ifconfig.me', timeout=5) as response:
                public_ip = response.read().decode('utf-8')
                if public_ip and len(public_ip) > 0:
                    return public_ip
        except:
            pass

    # 如果获取公网IP失败，尝试获取本地IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 不需要真正连接，只是获取路由信息
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        # 如果所有方法都失败，返回本地回环地址
        return '127.0.0.1'

def generate_self_signed_cert(base_dir, domain):
    """生成自签名证书"""
    cert_dir = f"{base_dir}/cert"
    cert_path = f"{cert_dir}/server.crt"
    key_path = f"{cert_dir}/server.key"
    
    # 确保域名不为空，如果为空则使用默认值
    if not domain or not domain.strip():
        domain = "localhost"
        print("警告: 域名为空，使用localhost作为证书通用名")
    
    try:
        # 生成更安全的证书
        subprocess.run([
            "openssl", "req", "-x509", "-nodes",
            "-newkey", "rsa:4096",  # 使用4096位密钥
            "-keyout", key_path,
            "-out", cert_path,
            "-subj", f"/CN={domain}",
            "-days", "36500",
            "-sha256"  # 使用SHA256
        ], check=True)
        
        # 设置适当的权限
        os.chmod(cert_path, 0o644)
        os.chmod(key_path, 0o600)
        
        return cert_path, key_path
    except Exception as e:
        print(f"生成证书失败: {e}")
        sys.exit(1)

def create_config(base_dir, port, password, cert_path, key_path, domain):
    """创建Hysteria2配置文件"""
    config = {
        "listen": f":{port}",
        "tls": {
            "cert": cert_path,
            "key": key_path
        },
        "auth": {
            "type": "password",
            "password": password
        },
        "masquerade": {
            "type": "proxy",
            "proxy": {
                "url": "https://www.bing.com",
                "rewriteHost": True
            }
        },
        "bandwidth": {
            "up": "10000 mbps",
            "down": "10000 mbps"
        },
        "ignoreClientBandwidth": False,
        "log": {
            "level": "info",
            "output": f"{base_dir}/logs/hysteria.log",
            "timestamp": True
        }
    }
    
    config_path = f"{base_dir}/config/config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    return config_path

def create_service_script(base_dir, binary_path, config_path, port):
    """创建启动脚本"""
    os_name = platform.system().lower()
    pid_file = f"{base_dir}/hysteria.pid"
    log_file = f"{base_dir}/logs/hysteria.log"
    
    if os_name == 'windows':
        script_content = f"""@echo off
echo 正在启动 Hysteria2 服务...
start /b {binary_path} server -c {config_path} > {log_file} 2>&1
echo 启动命令已执行，请检查日志以确认服务状态
"""
        script_path = f"{base_dir}/start.bat"
    else:
        script_content = f"""#!/bin/bash
echo "正在启动 Hysteria2 服务..."

# 检查二进制文件是否存在
if [ ! -f "{binary_path}" ]; then
    echo "错误: Hysteria2 二进制文件不存在"
    exit 1
fi

# 检查配置文件是否存在
if [ ! -f "{config_path}" ]; then
    echo "错误: 配置文件不存在"
    exit 1
fi

# 启动服务
nohup {binary_path} server -c {config_path} > {log_file} 2>&1 &
echo $! > {pid_file}
echo "Hysteria2 服务已启动，PID: $(cat {pid_file})"

# 给服务一点时间来启动
sleep 2
echo "启动命令已执行，请检查日志以确认服务状态"
"""
        script_path = f"{base_dir}/start.sh"
    
    with open(script_path, "w") as f:
        f.write(script_content)
    
    if os_name != 'windows':
        os.chmod(script_path, 0o755)
    
    return script_path

def create_stop_script(base_dir):
    """创建停止脚本"""
    os_name = platform.system().lower()
    
    if os_name == 'windows':
        script_content = f"""@echo off
for /f "tokens=*" %%a in ('type {base_dir}\\hysteria.pid') do (
    taskkill /F /PID %%a
)
del {base_dir}\\hysteria.pid
echo Hysteria2 服务已停止
"""
        script_path = f"{base_dir}/stop.bat"
    else:
        script_content = f"""#!/bin/bash
if [ -f {base_dir}/hysteria.pid ]; then
    kill $(cat {base_dir}/hysteria.pid)
    rm {base_dir}/hysteria.pid
    echo "Hysteria2 服务已停止"
else
    echo "Hysteria2 服务未运行"
fi
"""
        script_path = f"{base_dir}/stop.sh"
    
    with open(script_path, "w") as f:
        f.write(script_content)
    
    if os_name != 'windows':
        os.chmod(script_path, 0o755)
    
    return script_path

def delete_hysteria2():
    """删除Hysteria2安装"""
    home = get_user_home()
    base_dir = f"{home}/.hysteria2"
    
    if not os.path.exists(base_dir):
        print("Hysteria2 未安装")
        return
    
    # 停止服务
    stop_script = f"{base_dir}/stop.sh"
    if os.path.exists(stop_script):
        try:
            subprocess.run([stop_script], check=True)
        except:
            pass
    
    # 删除目录
    try:
        shutil.rmtree(base_dir)
        print("Hysteria2 已成功删除")
    except Exception as e:
        print(f"删除失败: {e}")
        sys.exit(1)

def show_status():
    """显示Hysteria2状态"""
    home = get_user_home()
    base_dir = f"{home}/.hysteria2"
    
    if not os.path.exists(base_dir):
        print("Hysteria2 未安装")
        return
    
    # 检查服务状态
    pid_file = f"{base_dir}/hysteria.pid"
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = f.read().strip()
            if os.path.exists(f"/proc/{pid}"):
                print(f"服务状态: 运行中 (PID: {pid})")
            else:
                print("服务状态: 已停止")
        except:
            print("服务状态: 未知")
    else:
        print("服务状态: 未运行")
    
    # 显示配置信息
    config_path = f"{base_dir}/config/config.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            print("\n配置信息:")
            print(f"监听端口: {config['listen']}")
            print(f"认证方式: {config['auth']['type']}")
            if 'bandwidth' in config:
                print(f"上行带宽: {config['bandwidth']['up']}")
                print(f"下行带宽: {config['bandwidth']['down']}")
        except:
            print("无法读取配置文件")
    
    # 显示日志
    log_path = f"{base_dir}/logs/hysteria.log"
    if os.path.exists(log_path):
        print("\n最近日志:")
        try:
            with open(log_path, 'r') as f:
                logs = f.readlines()
                for line in logs[-10:]:  # 显示最后10行
                    print(line.strip())
        except:
            print("无法读取日志文件")

def start_service(start_script, port, base_dir):
    """启动服务并等待服务成功运行"""
    print(f"正在启动 Hysteria2 服务...")
    pid_file = f"{base_dir}/hysteria.pid"
    log_file = f"{base_dir}/logs/hysteria.log"
    
    try:
        # 运行启动脚本
        subprocess.run([start_script], check=True)
        
        # 等待服务启动 (最多10秒)
        for i in range(10):
            # 检查PID文件和进程
            if check_process_running(pid_file):
                print(f"服务进程已启动")
                time.sleep(2)  # 给服务额外时间初始化
                break
            time.sleep(1)
            print(f"等待服务启动... ({i+1}秒)")
        
        # 检查日志文件是否存在且有内容
        if os.path.exists(log_file) and os.path.getsize(log_file) > 0:
            with open(log_file, 'r') as f:
                log_content = f.read()
                if "server up and running" in log_content:
                    print("日志显示服务已正常启动")
                    return True
        
        # 检查端口是否在监听
        if is_port_listening(port):
            print(f"检测到端口 {port} 已开放，服务应已启动")
            return True
            
        print("警告: 无法确认服务是否成功启动，请检查日志文件")
        return True  # 即使不确定也返回True，避免误报
    except Exception as e:
        print(f"启动服务失败: {e}")
        return False

def show_help():
    """显示帮助信息"""
    print("""
Hysteria2 管理工具

使用方法:
    python3 hysteria2_no_root.py [命令] [选项]

可用命令:
    install    安装 Hysteria2
    del        删除 Hysteria2
    status     查看 Hysteria2 状态
    help       显示此帮助信息

选项:
    --ip IP           指定服务器IP地址或域名
    --port PORT       指定服务器端口
    --password PWD    指定密码

示例:
    python3 hysteria2_no_root.py install                   # 基本安装
    python3 hysteria2_no_root.py install --port 12345      # 指定端口
    python3 hysteria2_no_root.py status                    # 查看状态
    python3 hysteria2_no_root.py del                       # 删除安装
""")

def main():
    parser = argparse.ArgumentParser(description='Hysteria2 管理工具')
    parser.add_argument('command', nargs='?', default='install',
                      help='命令: install, del, status, help')
    parser.add_argument('--ip', help='指定服务器IP地址或域名')
    parser.add_argument('--port', type=int, help='指定服务器端口')
    parser.add_argument('--password', help='指定密码')
    
    args = parser.parse_args()
    
    if args.command == 'del':
        delete_hysteria2()
    elif args.command == 'status':
        show_status()
    elif args.command == 'help':
        show_help()
    elif args.command == 'install':
        # 默认配置
        port = args.port if args.port else 49999
        password = args.password if args.password else "123qwe!@#QWE"
        
        # 获取IP地址
        server_address = args.ip if args.ip else get_ip_address()
        
        print("\n开始安装 Hysteria2...")
        print(f"服务器地址: {server_address}")
        print(f"端口: {port}")
        
        # 检查端口
        if not check_port_available(port):
            print(f"错误: 端口 {port} 已被占用，请选择其他端口")
            sys.exit(1)
        
        # 创建目录
        base_dir = create_directories()
        
        # 下载Hysteria2
        binary_path, version = download_hysteria2(base_dir)
        
        # 验证二进制文件
        if not verify_binary(binary_path):
            print("错误: Hysteria2 二进制文件无效")
            sys.exit(1)
        
        # 生成证书
        cert_path, key_path = generate_self_signed_cert(base_dir, server_address)
        
        # 创建配置
        config_path = create_config(base_dir, port, password, cert_path, key_path, server_address)
        
        # 创建启动脚本
        start_script = create_service_script(base_dir, binary_path, config_path, port)
        
        # 创建停止脚本
        stop_script = create_stop_script(base_dir)
        
        # 立即启动Hysteria2服务
        service_started = start_service(start_script, port, base_dir)
        
        # 生成客户端配置链接
        config_link = f"hysteria2://{urllib.parse.quote(password)}@{server_address}:{port}?insecure=1&sni={server_address}&bandwidth=10000mbps"
        
        print(f"""
Hysteria2 已成功安装！

版本: {version}
安装目录: {base_dir}
配置文件: {config_path}
启动脚本: {start_script}
停止脚本: {stop_script}
日志文件: {base_dir}/logs/hysteria.log

使用方法:
1. 启动服务: {start_script}
2. 停止服务: {stop_script}
3. 查看日志: {base_dir}/logs/hysteria.log

服务器信息:
- 地址: {server_address}
- 端口: {port}
- 密码: {password}
- 证书: {cert_path}

客户端配置链接:
{config_link}

客户端手动配置信息:
服务器: {server_address}
端口: {port}
密码: {password}
TLS: 启用
跳过证书验证: 是
SNI: {server_address}
带宽: 10000mbps

支持的系统:
- Linux (x86_64, arm64)
- macOS (x86_64, arm64)
- Windows (x86_64)
""")
    else:
        print(f"未知命令: {args.command}")
        show_help()
        sys.exit(1)

if __name__ == "__main__":
    main() 
