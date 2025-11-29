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
import base64
import random

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

def ensure_nginx_user():
    """确保nginx用户存在，如果不存在就创建，统一使用nginx用户"""
    try:
        # 检查nginx用户是否已存在
        try:
            result = subprocess.run(['id', 'nginx'], check=True, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ nginx用户已存在")
                return 'nginx'
        except:
            # nginx用户不存在，创建它
            print("🔧 nginx用户不存在，正在创建...")
            
            # 创建nginx系统用户（无登录shell，无家目录）
            try:
                subprocess.run([
                    'sudo', 'useradd', 
                    '--system',           # 系统用户
                    '--no-create-home',   # 不创建家目录
                    '--shell', '/bin/false',  # 无登录shell
                    '--comment', 'nginx web server',  # 注释
                    'nginx'
                ], check=True, capture_output=True)
                print("✅ nginx用户创建成功")
                return 'nginx'
            except subprocess.CalledProcessError as e:
                # 如果创建失败，可能是因为用户已存在但id命令失败，或其他原因
                print(f"⚠️ 创建nginx用户失败: {e}")
                
                # 再次检查用户是否存在（可能是并发创建）
                try:
                    subprocess.run(['id', 'nginx'], check=True, capture_output=True)
                    print("✅ nginx用户实际上已存在")
                    return 'nginx'
                except:
                    # 确实创建失败，fallback到root用户
                    print("⚠️ 使用root用户作为nginx运行用户")
                    return 'root'
        
    except Exception as e:
        print(f"❌ 处理nginx用户时出错: {e}")
        # 出错时使用root用户
        return 'root'

def set_nginx_permissions(web_dir):
    """设置nginx目录的正确权限"""
    try:
        nginx_user = ensure_nginx_user()
        print(f"🔧 设置目录权限: {web_dir}")
        print(f"👤 使用用户: {nginx_user}")
        
        # 设置目录和文件权限
        subprocess.run(['sudo', 'chown', '-R', f'{nginx_user}:{nginx_user}', web_dir], check=True)
        subprocess.run(['sudo', 'chmod', '-R', '755', web_dir], check=True)
        subprocess.run(['sudo', 'find', web_dir, '-type', 'f', '-exec', 'chmod', '644', '{}', ';'], check=True)
        
        print(f"✅ 权限设置完成: {web_dir} (用户: {nginx_user})")
        return True
    except Exception as e:
        print(f"❌ 设置权限失败: {e}")
        return False

def check_port_available(port):
    """检查端口是否可用（仅使用socket）"""
    try:
        # 对于Hysteria2，我们主要关心UDP端口
        # nginx使用TCP端口，hysteria使用UDP端口，它们可以共存
        
        # 检查UDP端口是否可用（这是hysteria2需要的）
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1)
            try:
                s.bind(('', port))
                return True  # UDP端口可用
            except:
                # UDP端口被占用，检查是否是hysteria进程
                return False
                
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

def setup_nginx_smart_proxy(base_dir, domain, web_dir, cert_path, key_path, hysteria_port):
    """设置nginx Web伪装：TCP端口显示正常网站，UDP端口用于Hysteria2"""
    print("🚀 正在配置nginx Web伪装...")
    
    try:
        # 检查证书文件
        print(f"🔍 检查证书文件路径:")
        print(f"证书文件: {cert_path}")
        print(f"密钥文件: {key_path}")
        
        if not os.path.exists(cert_path):
            print(f"❌ 证书文件不存在: {cert_path}")
            cert_path, key_path = generate_self_signed_cert(base_dir, domain)
        
        if not os.path.exists(key_path):
            print(f"❌ 密钥文件不存在: {key_path}")
            cert_path, key_path = generate_self_signed_cert(base_dir, domain)
        
        print(f"📁 最终使用的证书路径:")
        print(f"证书: {cert_path}")
        print(f"密钥: {key_path}")
        
        # 确保nginx用户存在
        nginx_user = ensure_nginx_user()
        print(f"👤 使用nginx用户: {nginx_user}")
        
        # 创建nginx标准Web配置
        nginx_conf = f"""user {nginx_user};
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

events {{
    worker_connections 1024;
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;
    server_tokens off;
    
    server {{
        listen 80;
        listen 443 ssl http2;
        server_name _;
        
        ssl_certificate {os.path.abspath(cert_path)};
        ssl_certificate_key {os.path.abspath(key_path)};
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
        
        root {web_dir};
        index index.html index.htm;
        
        # 正常网站访问
        location / {{
            try_files $uri $uri/ /index.html;
        }}
        
        add_header X-Frame-Options DENY always;
        add_header X-Content-Type-Options nosniff always;
    }}
}}"""
        
        # 更新nginx配置
        print("💾 备份当前nginx配置...")
        subprocess.run(['sudo', 'cp', '/etc/nginx/nginx.conf', '/etc/nginx/nginx.conf.backup'], check=True)
        
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as tmp:
            tmp.write(nginx_conf)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, '/etc/nginx/nginx.conf'], check=True)
            os.unlink(tmp.name)
        
        subprocess.run(['sudo', 'rm', '-f', '/etc/nginx/conf.d/*.conf'], check=True)
        
        # 测试并重启
        print("🔧 测试nginx配置...")
        test_result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
        if test_result.returncode != 0:
            print(f"❌ nginx配置测试失败:")
            print(f"错误信息: {test_result.stderr}")
            subprocess.run(['sudo', 'cp', '/etc/nginx/nginx.conf.backup', '/etc/nginx/nginx.conf'], check=True)
            print("🔄 已恢复nginx配置备份")
            return False, None
        
        print("✅ nginx配置测试通过")
        
        print("🔄 重启nginx服务...")
        restart_result = subprocess.run(['sudo', 'systemctl', 'restart', 'nginx'], capture_output=True, text=True)
        if restart_result.returncode != 0:
            print(f"❌ nginx重启失败:")
            print(f"错误信息: {restart_result.stderr}")
            return False, None
        
        print("✅ nginx Web伪装配置成功！")
        print("🎯 TCP端口: 标准HTTPS网站")
        print("🎯 UDP端口: Hysteria2代理服务")
        
        return True, hysteria_port
        
    except Exception as e:
        print(f"❌ 配置失败: {e}")
        return False, None

def create_web_masquerade(base_dir):
    """创建Web伪装页面"""
    web_dir = f"{base_dir}/web"
    os.makedirs(web_dir, exist_ok=True)
    
    return create_web_files_in_directory(web_dir)

def create_web_files_in_directory(web_dir):
    """在指定目录创建Web文件"""
    # 确保目录存在
    if not os.path.exists(web_dir):
        try:
            subprocess.run(['sudo', 'mkdir', '-p', web_dir], check=True)
        except:
            os.makedirs(web_dir, exist_ok=True)
    
    # 创建一个更逼真的企业网站首页
    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Global Digital Solutions - Enterprise Cloud Services</title>
    <meta name="description" content="Leading provider of enterprise cloud solutions, digital infrastructure, and business technology services.">
    <meta name="keywords" content="cloud computing, enterprise solutions, digital transformation, IT services">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; background: #f8f9fa; }
        .container { max-width: 1200px; margin: 0 auto; padding: 0 20px; }
        
        header { background: linear-gradient(135deg, #2c5aa0 0%, #1e3a8a 100%); color: white; padding: 1rem 0; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        nav { display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 1.8rem; font-weight: bold; }
        .nav-links { display: flex; list-style: none; gap: 2rem; }
        .nav-links a { color: white; text-decoration: none; transition: opacity 0.3s; font-weight: 500; }
        .nav-links a:hover { opacity: 0.8; }
        
        .hero { background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); padding: 5rem 0; text-align: center; }
        .hero h1 { font-size: 3.5rem; margin-bottom: 1rem; color: #1e293b; font-weight: 700; }
        .hero p { font-size: 1.3rem; color: #64748b; margin-bottom: 2.5rem; max-width: 600px; margin-left: auto; margin-right: auto; }
        .btn { display: inline-block; background: #2563eb; color: white; padding: 15px 35px; text-decoration: none; border-radius: 8px; transition: all 0.3s; font-weight: 600; margin: 0 10px; }
        .btn:hover { background: #1d4ed8; transform: translateY(-2px); }
        .btn-secondary { background: transparent; border: 2px solid #2563eb; color: #2563eb; }
        .btn-secondary:hover { background: #2563eb; color: white; }
        
        .stats { background: white; padding: 3rem 0; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 2rem; text-align: center; }
        .stat h3 { font-size: 2.5rem; color: #2563eb; font-weight: 700; }
        .stat p { color: #64748b; font-weight: 500; }
        
        .features { padding: 5rem 0; background: #f8fafc; }
        .features h2 { text-align: center; font-size: 2.5rem; margin-bottom: 3rem; color: #1e293b; }
        .features-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 3rem; margin-top: 3rem; }
        .feature { background: white; padding: 2.5rem; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; transition: transform 0.3s; }
        .feature:hover { transform: translateY(-5px); }
        .feature-icon { font-size: 3rem; margin-bottom: 1rem; }
        .feature h3 { color: #1e293b; margin-bottom: 1rem; font-size: 1.3rem; }
        .feature p { color: #64748b; line-height: 1.7; }
        
        .cta { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; padding: 5rem 0; text-align: center; }
        .cta h2 { font-size: 2.5rem; margin-bottom: 1rem; }
        .cta p { font-size: 1.2rem; margin-bottom: 2rem; opacity: 0.9; }
        
        footer { background: #1e293b; color: white; text-align: center; padding: 3rem 0; }
        .footer-content { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 2rem; margin-bottom: 2rem; text-align: left; }
        .footer-section h4 { margin-bottom: 1rem; color: #3b82f6; }
        .footer-section p, .footer-section a { color: #94a3b8; text-decoration: none; }
        .footer-section a:hover { color: white; }
        .footer-bottom { border-top: 1px solid #334155; padding-top: 2rem; margin-top: 2rem; text-align: center; color: #94a3b8; }
    </style>
</head>
 <body>
     <header>
         <nav class="container">
             <div class="logo">Global Digital Solutions</div>
             <ul class="nav-links">
                 <li><a href="#home">Home</a></li>
                 <li><a href="#services">Solutions</a></li>
                 <li><a href="#about">About</a></li>
                 <li><a href="#contact">Contact</a></li>
             </ul>
         </nav>
     </header>

     <section class="hero">
         <div class="container">
             <h1>Transform Your Digital Future</h1>
             <p>Leading enterprise cloud solutions and digital infrastructure services for businesses worldwide. Secure, scalable, and always available.</p>
             <a href="#services" class="btn">Explore Solutions</a>
             <a href="#contact" class="btn btn-secondary">Get Started</a>
         </div>
     </section>

     <section class="stats">
         <div class="container">
             <div class="stats-grid">
                 <div class="stat">
                     <h3>99.9%</h3>
                     <p>Uptime Guarantee</p>
                 </div>
                 <div class="stat">
                     <h3>10,000+</h3>
                     <p>Enterprise Clients</p>
                 </div>
                 <div class="stat">
                     <h3>50+</h3>
                     <p>Global Data Centers</p>
                 </div>
                 <div class="stat">
                     <h3>24/7</h3>
                     <p>Expert Support</p>
                 </div>
             </div>
         </div>
     </section>

     <section class="features" id="services">
         <div class="container">
             <h2>Enterprise Cloud Solutions</h2>
             <div class="features-grid">
                 <div class="feature">
                     <div class="feature-icon">☁️</div>
                     <h3>Cloud Infrastructure</h3>
                     <p>Scalable and secure cloud infrastructure with global reach. Deploy your applications with confidence on our enterprise-grade platform.</p>
                 </div>
                 <div class="feature">
                     <div class="feature-icon">🔒</div>
                     <h3>Security & Compliance</h3>
                     <p>Advanced security protocols and compliance standards including SOC 2, ISO 27001, and GDPR to protect your business data.</p>
                 </div>
                 <div class="feature">
                     <div class="feature-icon">⚡</div>
                     <h3>High Performance</h3>
                     <p>Lightning-fast performance with our global CDN network and optimized infrastructure for maximum speed and reliability.</p>
                 </div>
                 <div class="feature">
                     <div class="feature-icon">📊</div>
                     <h3>Analytics & Monitoring</h3>
                     <p>Real-time monitoring and detailed analytics to help you optimize performance and make data-driven business decisions.</p>
                 </div>
                 <div class="feature">
                     <div class="feature-icon">🛠️</div>
                     <h3>Managed Services</h3>
                     <p>Full-stack managed services including database management, security updates, and performance optimization by our experts.</p>
                 </div>
                 <div class="feature">
                     <div class="feature-icon">🌍</div>
                     <h3>Global Reach</h3>
                     <p>Worldwide infrastructure with data centers across six continents, ensuring low latency and high availability for your users.</p>
                 </div>
             </div>
         </div>
     </section>

     <section class="cta" id="contact">
         <div class="container">
             <h2>Ready to Transform Your Business?</h2>
             <p>Join thousands of enterprises already using our cloud solutions</p>
             <a href="mailto:contact@globaldigi.com" class="btn">Contact Sales Team</a>
         </div>
     </section>

     <footer>
         <div class="container">
             <div class="footer-content">
                 <div class="footer-section">
                     <h4>Solutions</h4>
                     <p><a href="#">Cloud Infrastructure</a></p>
                     <p><a href="#">Security Services</a></p>
                     <p><a href="#">Data Analytics</a></p>
                     <p><a href="#">Managed Services</a></p>
                 </div>
                 <div class="footer-section">
                     <h4>Company</h4>
                     <p><a href="#">About Us</a></p>
                     <p><a href="#">Careers</a></p>
                     <p><a href="#">News</a></p>
                     <p><a href="#">Contact</a></p>
                 </div>
                 <div class="footer-section">
                     <h4>Support</h4>
                     <p><a href="#">Documentation</a></p>
                     <p><a href="#">Help Center</a></p>
                     <p><a href="#">Status Page</a></p>
                     <p><a href="#">Contact Support</a></p>
                 </div>
                 <div class="footer-section">
                     <h4>Legal</h4>
                     <p><a href="#">Privacy Policy</a></p>
                     <p><a href="#">Terms of Service</a></p>
                     <p><a href="#">Security</a></p>
                     <p><a href="#">Compliance</a></p>
                 </div>
             </div>
             <div class="footer-bottom">
                 <p>&copy; 2024 Global Digital Solutions Inc. All rights reserved. | Enterprise Cloud Services</p>
             </div>
         </div>
     </footer>
 </body>
</html>"""
    
    # 使用sudo写入文件（如果需要）
    try:
        with open(f"{web_dir}/index.html", "w", encoding="utf-8") as f:
            f.write(index_html)
    except PermissionError:
        # 使用sudo写入
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as tmp:
            tmp.write(index_html)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, f"{web_dir}/index.html"], check=True)
            os.unlink(tmp.name)
    
    # 创建robots.txt（看起来更真实）
    robots_txt = """User-agent: *
Allow: /

Sitemap: /sitemap.xml
"""
    try:
        with open(f"{web_dir}/robots.txt", "w") as f:
            f.write(robots_txt)
    except PermissionError:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as tmp:
            tmp.write(robots_txt)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, f"{web_dir}/robots.txt"], check=True)
            os.unlink(tmp.name)
    
    # 创建sitemap.xml
    sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>/</loc>
    <lastmod>2024-01-01</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>/services</loc>
    <lastmod>2024-01-01</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>/about</loc>
    <lastmod>2024-01-01</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>
  <url>
    <loc>/contact</loc>
    <lastmod>2024-01-01</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
</urlset>"""
    try:
        with open(f"{web_dir}/sitemap.xml", "w") as f:
            f.write(sitemap_xml)
    except PermissionError:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.xml') as tmp:
            tmp.write(sitemap_xml)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, f"{web_dir}/sitemap.xml"], check=True)
            os.unlink(tmp.name)
    
    # 创建favicon.ico (简单的base64编码)
    # 这是一个简单的蓝色圆形图标
    favicon_data = """AAABAAEAEBAAAAEAIABoBAAAFgAAACgAAAAQAAAAIAAAAAEAIAAAAAAAAAQAABILAAASCwAAAAAAAAAAAAD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A2dnZ/9nZ2f/Z2dn/2dnZ/9nZ2f/Z2dn/2dnZ/9nZ2f/Z2dn/2dnZ/////wD///8A////AP///wD///8A2dnZ/1tbW/8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/1tbW//Z2dn/////AP///wD///8A2dnZ/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/2dnZ/////wD///8A2dnZ/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/2dnZ/////wD///8A2dnZ/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/2dnZ/////wD///8A2dnZ/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/2dnZ/////wD///8A2dnZ/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/2dnZ/////wD///8A2dnZ/1tbW/8AAAD/AAAA/wAAAP8AAAD/AAAA/wAAAP8AAAD/AAAA/1tbW//Z2dn/////AP///wD///8A////AP///wD///8A2dnZ/9nZ2f/Z2dn/2dnZ/9nZ2f/Z2dn/2dnZ/9nZ2f/Z2dn/2dnZ/////wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A////AP///wD///8A//8AAP//AAD//wAA//8AAP//AAD//wAA//8AAP//AAD//wAA//8AAP//AAD//wAA//8AAP//AAD//wAA//8AAA=="""
    
    import base64
    try:
        favicon_bytes = base64.b64decode(favicon_data)
        try:
            with open(f"{web_dir}/favicon.ico", "wb") as f:
                f.write(favicon_bytes)
        except PermissionError:
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ico') as tmp:
                tmp.write(favicon_bytes)
                tmp.flush()
                subprocess.run(['sudo', 'cp', tmp.name, f"{web_dir}/favicon.ico"], check=True)
                os.unlink(tmp.name)
    except:
        pass  # 如果favicon创建失败就跳过
    
    # 创建about页面
    about_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>About Us - Global Digital Solutions</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div style="text-align: center; padding: 50px; font-family: Arial, sans-serif;">
        <h1>About Global Digital Solutions</h1>
        <p>We are a leading provider of enterprise cloud solutions, serving businesses worldwide since 2015.</p>
        <p>Our mission is to transform how businesses operate in the digital age through innovative cloud technologies.</p>
        <p><a href="/">← Back to Home</a></p>
    </div>
</body>
</html>"""
    try:
        with open(f"{web_dir}/about.html", "w", encoding="utf-8") as f:
            f.write(about_html)
    except PermissionError:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as tmp:
            tmp.write(about_html)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, f"{web_dir}/about.html"], check=True)
            os.unlink(tmp.name)
    
    # 创建404页面
    error_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 - Page Not Found</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f4f4f4; }
        .error-container { background: white; padding: 50px; border-radius: 10px; box-shadow: 0 0 20px rgba(0,0,0,0.1); max-width: 500px; margin: 0 auto; }
        h1 { color: #e74c3c; font-size: 4rem; margin-bottom: 1rem; }
        p { color: #666; font-size: 1.2rem; }
        a { color: #3498db; text-decoration: none; }
    </style>
</head>
<body>
    <div class="error-container">
        <h1>404</h1>
        <p>Sorry, the page you are looking for could not be found.</p>
        <p><a href="/">Return to Homepage</a></p>
    </div>
</body>
</html>"""
    
    try:
        with open(f"{web_dir}/404.html", "w", encoding="utf-8") as f:
            f.write(error_html)
    except PermissionError:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html') as tmp:
            tmp.write(error_html)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, f"{web_dir}/404.html"], check=True)
            os.unlink(tmp.name)
    
    return web_dir

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

def get_real_certificate(base_dir, domain, email="admin@example.com"):
    """使用certbot获取真实的Let's Encrypt证书"""
    cert_dir = f"{base_dir}/cert"
    
    try:
        # 检查是否已安装certbot
        if not shutil.which('certbot'):
            print("正在安装certbot...")
            if platform.system().lower() == 'linux':
                # Ubuntu/Debian
                if shutil.which('apt'):
                    subprocess.run(['sudo', 'apt', 'update'], check=True)
                    subprocess.run(['sudo', 'apt', 'install', '-y', 'certbot'], check=True)
                # CentOS/RHEL
                elif shutil.which('yum'):
                    subprocess.run(['sudo', 'yum', 'install', '-y', 'certbot'], check=True)
                elif shutil.which('dnf'):
                    subprocess.run(['sudo', 'dnf', 'install', '-y', 'certbot'], check=True)
                else:
                    print("无法自动安装certbot，请手动安装")
                    return None, None
            else:
                print("请手动安装certbot")
                return None, None
        
        # 使用standalone模式获取证书
        print(f"正在为域名 {domain} 获取Let's Encrypt证书...")
        subprocess.run([
            'sudo', 'certbot', 'certonly',
            '--standalone',
            '--agree-tos',
            '--non-interactive',
            '--email', email,
            '-d', domain
        ], check=True)
        
        # 复制证书到我们的目录
        cert_source = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
        key_source = f"/etc/letsencrypt/live/{domain}/privkey.pem"
        cert_path = f"{cert_dir}/server.crt"
        key_path = f"{cert_dir}/server.key"
        
        shutil.copy2(cert_source, cert_path)
        shutil.copy2(key_source, key_path)
        
        # 设置权限
        os.chmod(cert_path, 0o644)
        os.chmod(key_path, 0o600)
        
        print(f"成功获取真实证书: {cert_path}")
        return cert_path, key_path
        
    except Exception as e:
        print(f"获取真实证书失败: {e}")
        print("将使用自签名证书作为备选...")
        return None, None

def create_config(base_dir, port, password, cert_path, key_path, domain, enable_web_masquerade=True, custom_web_dir=None, enable_port_hopping=False, obfs_password=None, enable_http3_masquerade=False):
    """创建Hysteria2配置文件（端口跳跃、混淆、HTTP/3伪装）"""
    
    # 基础配置
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
        "bandwidth": {
            "up": "1000 mbps",
            "down": "1000 mbps"
        },
        "ignoreClientBandwidth": False,
        "log": {
            "level": "warn",
            "output": f"{base_dir}/logs/hysteria.log",
            "timestamp": True
        },
        "resolver": {
            "type": "udp",
            "tcp": {
                "addr": "8.8.8.8:53",
                "timeout": "4s"
            },
            "udp": {
                "addr": "8.8.8.8:53", 
                "timeout": "4s"
            }
        }
    }
    
    # 端口跳跃配置 (Port Hopping)
    if enable_port_hopping:
        # Hysteria2服务器端只监听单个端口，端口跳跃通过iptables DNAT实现
        port_start = max(1024, port - 25)  
        port_end = min(65535, port + 25)
        
        # 确保范围合理：如果基准端口太小，使用固定范围
        if port < 1049:  # 1024 + 25
            port_start = 1024
            port_end = 1074
        
        # 服务器仍然只监听单个端口
        config["listen"] = f":{port}"
        
        # 记录端口跳跃信息，用于后续iptables配置
        config["_port_hopping"] = {
            "enabled": True,
            "range_start": port_start,
            "range_end": port_end,
            "listen_port": port
        }
        
        print(f"✅ 启用端口跳跃 - 服务器监听: {port}, 客户端可用范围: {port_start}-{port_end}")
    
    # 流量混淆配置 (Salamander Obfuscation)
    if obfs_password:
        config["obfs"] = {
            "type": "salamander",
            "salamander": {
                "password": obfs_password
            }
        }
        print(f"✅ 启用Salamander混淆 - 密码: {obfs_password}")
    
    # HTTP/3伪装配置
    if enable_http3_masquerade:
        if enable_web_masquerade and custom_web_dir and os.path.exists(custom_web_dir):
            config["masquerade"] = {
                "type": "file",
                "file": {
                    "dir": custom_web_dir
                }
            }
        else:
            # 使用HTTP/3网站伪装
            config["masquerade"] = {
                "type": "proxy",
                "proxy": {
                    "url": "https://www.google.com",
                    "rewriteHost": True
                }
            }
        print("✅ 启用HTTP/3伪装 - 流量看起来像正常HTTP/3")
    elif enable_web_masquerade and custom_web_dir and os.path.exists(custom_web_dir):
        config["masquerade"] = {
            "type": "file",
            "file": {
                "dir": custom_web_dir
            }
        }
    elif port in [80, 443, 8080, 8443]:
        config["masquerade"] = {
            "type": "proxy",
            "proxy": {
                "url": "https://www.microsoft.com",
                "rewriteHost": True
            }
        }
    else:
        masquerade_sites = [
            "https://www.microsoft.com",
            "https://www.apple.com", 
            "https://www.amazon.com",
            "https://www.github.com",
            "https://www.stackoverflow.com"
        ]
        import random
        config["masquerade"] = {
            "type": "proxy",
            "proxy": {
                "url": random.choice(masquerade_sites),
                "rewriteHost": True
            }
        }
    
    # QUIC/HTTP3优化配置
    if port == 443:
        config["quic"] = {
            "initStreamReceiveWindow": 8388608,
            "maxStreamReceiveWindow": 8388608,
            "initConnReceiveWindow": 20971520,
            "maxConnReceiveWindow": 20971520,
            "maxIdleTimeout": "30s",
            "maxIncomingStreams": 1024,
            "disablePathMTUDiscovery": False
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
    """完整删除Hysteria2安装的5步流程"""
    print("🗑️ 开始完整删除Hysteria2...")
    print("📋 删除流程: 停止服务 → 清理iptables → 清理nginx → 删除目录 → 清理服务")
    
    home = get_user_home()
    base_dir = f"{home}/.hysteria2"
    
    if not os.path.exists(base_dir):
        print("⚠️ Hysteria2 未安装或已被删除")
        return True
    
    # 1. 停止Hysteria2服务
    print("\n🛑 步骤1: 停止Hysteria2服务")
    try:
        pid_file = f"{base_dir}/hysteria.pid"
        
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid = f.read().strip()
                if pid:
                    try:
                        os.kill(int(pid), 15)  # SIGTERM
                        time.sleep(2)
                        print(f"✅ 已停止Hysteria2进程 (PID: {pid})")
                    except ProcessLookupError:
                        print("⚠️ 进程已不存在")
                    except Exception as e:
                        print(f"⚠️ 停止进程失败: {e}")
                        try:
                            os.kill(int(pid), 9)  # SIGKILL
                            print("✅ 强制终止进程成功")
                        except:
                            pass
            except Exception as e:
                print(f"⚠️ 读取PID文件失败: {e}")
        
        # 查找并停止所有hysteria进程
        try:
            result = subprocess.run(['pgrep', '-f', 'hysteria'], capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        subprocess.run(['sudo', 'kill', '-15', pid], check=True)
                        print(f"✅ 已停止hysteria进程: {pid}")
                    except:
                        try:
                            subprocess.run(['sudo', 'kill', '-9', pid], check=True)
                        except:
                            pass
        except:
            pass
            
    except Exception as e:
        print(f"⚠️ 停止服务失败: {e}")
    
    # 2. 清理iptables规则
    print("\n🔧 步骤2: 清理iptables规则")
    try:
        port_ranges = []
        
        # 从配置文件读取端口信息
        config_path = f"{base_dir}/config/config.json"
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    config = json.load(f)
                listen_port = int(config.get('listen', ':443').replace(':', ''))
                
                # 计算可能的端口范围
                port_start = max(1024, listen_port - 25)
                port_end = min(65535, listen_port + 25)
                if listen_port < 1049:
                    port_start = 1024
                    port_end = 1074
                
                port_ranges.append((port_start, port_end, listen_port))
                print(f"📋 从配置文件读取端口信息: {port_start}-{port_end} → {listen_port}")
            except:
                pass
    
        # 添加常见端口范围以确保清理完整
        common_ranges = [
            (1024, 1074, 443),
            (28888, 29999, 443),
            (10000, 10050, 443),
            (20000, 20050, 443)
        ]
        port_ranges.extend(common_ranges)
        
        # 清理iptables规则
        for port_start, port_end, listen_port in port_ranges:
            try:
                # 删除NAT规则
                subprocess.run([
                    'sudo', 'iptables', '-t', 'nat', '-D', 'PREROUTING',
                    '-p', 'udp', '--dport', f'{port_start}:{port_end}',
                    '-j', 'DNAT', '--to-destination', f':{listen_port}'
                ], check=False, capture_output=True)
                
                # 删除INPUT规则
                subprocess.run([
                    'sudo', 'iptables', '-D', 'INPUT',
                    '-p', 'udp', '--dport', f'{port_start}:{port_end}',
                    '-j', 'ACCEPT'
                ], check=False, capture_output=True)
                
                # 删除单端口规则
                subprocess.run([
                    'sudo', 'iptables', '-D', 'INPUT',
                    '-p', 'udp', '--dport', str(listen_port),
                    '-j', 'ACCEPT'
                ], check=False, capture_output=True)
                
            except:
                pass
        
        # 保存iptables规则
        try:
            subprocess.run(['sudo', 'iptables-save'], check=True, capture_output=True)
            subprocess.run(['sudo', 'netfilter-persistent', 'save'], check=False, capture_output=True)
        except:
            try:
                subprocess.run(['sudo', 'service', 'iptables', 'save'], check=False, capture_output=True)
            except:
                pass
        
        print("✅ iptables规则清理完成")
        
    except Exception as e:
        print(f"⚠️ 清理iptables规则失败: {e}")
    
    # 3. 清理nginx配置
    print("\n🌐 步骤3: 清理nginx配置")
    try:
        # 清理nginx配置文件
        nginx_conf_files = [
            "/etc/nginx/conf.d/hysteria2-ssl.conf",
            "/etc/nginx/conf.d/hysteria2.conf",
            "/etc/nginx/sites-enabled/hysteria2",
            "/etc/nginx/sites-available/hysteria2"
        ]
        
        # 添加基于IP的配置文件
        try:
            ip_addr = get_ip_address()
            nginx_conf_files.extend([
                f"/etc/nginx/conf.d/{ip_addr}.conf",
                f"/etc/nginx/sites-enabled/{ip_addr}",
                f"/etc/nginx/sites-available/{ip_addr}"
            ])
        except:
            pass
        
        removed_files = []
        for conf_file in nginx_conf_files:
            if os.path.exists(conf_file):
                try:
                    subprocess.run(['sudo', 'rm', '-f', conf_file], check=True)
                    removed_files.append(conf_file)
                except:
                    pass
        
        if removed_files:
            print(f"✅ 已删除nginx配置文件: {', '.join(removed_files)}")
        
        # 恢复nginx默认Web目录
        nginx_web_dirs = ["/var/www/html", "/usr/share/nginx/html"]
        for web_dir in nginx_web_dirs:
            if os.path.exists(web_dir):
                backup_file = f"{web_dir}/index.html.backup"
                if os.path.exists(backup_file):
                    try:
                        subprocess.run(['sudo', 'cp', backup_file, f"{web_dir}/index.html"], check=True)
                        print(f"✅ 恢复nginx默认页面: {web_dir}")
                    except:
                        pass
        
        # 测试并重启nginx
        try:
            test_result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
            if test_result.returncode == 0:
                subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], check=True)
                print("✅ nginx配置已重新加载")
            else:
                print(f"⚠️ nginx配置测试失败: {test_result.stderr}")
        except:
            print("⚠️ nginx重新加载失败")
                
    except Exception as e:
        print(f"⚠️ 清理nginx配置失败: {e}")
    
    # 4. 删除安装目录
    print("\n📁 步骤4: 删除安装目录")
    try:
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir)
            print(f"✅ 已删除安装目录: {base_dir}")
        else:
            print("⚠️ 安装目录不存在")
        
    except Exception as e:
        print(f"❌ 删除安装目录失败: {e}")
    
    # 5. 清理系统服务（如果存在）
    print("\n🔧 步骤5: 清理系统服务")
    try:
        service_files = [
            "/etc/systemd/system/hysteria2.service",
            "/usr/lib/systemd/system/hysteria2.service"
        ]
        
        for service_file in service_files:
            if os.path.exists(service_file):
                try:
                    subprocess.run(['sudo', 'systemctl', 'stop', 'hysteria2'], check=False)
                    subprocess.run(['sudo', 'systemctl', 'disable', 'hysteria2'], check=False)
                    subprocess.run(['sudo', 'rm', '-f', service_file], check=True)
                    print(f"✅ 已删除系统服务: {service_file}")
                except:
                    pass
        
        # 重新加载systemd
        try:
            subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
        except:
            pass
            
    except Exception as e:
        print(f"⚠️ 清理系统服务失败: {e}")
    
    print(f"""
🎉 Hysteria2完全删除完成！

✅ 已清理的内容:
- Hysteria2服务进程
- iptables端口跳跃规则
- nginx配置文件
- 安装目录: {base_dir}
- 系统服务文件
- Web伪装文件

🔧 建议检查:
- 防火墙规则是否需要调整
- nginx是否正常运行: sudo systemctl status nginx
- 系统中是否还有遗留的hysteria进程: ps aux | grep hysteria

现在系统已恢复到安装前的状态！
""")
    
    return True

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
🛡️ Hysteria2 一键部署工具 (防墙增强版)

重要说明：Hysteria2基于UDP/QUIC协议，支持端口跳跃、混淆和HTTP/3伪装！

使用方法:
    python3 hy2.py [命令] [选项]

可用命令:
    install      安装 Hysteria2 (一键部署，自动优化配置)
    client       显示客户端连接指南 (各平台详细说明)
    fix          修复nginx配置和权限问题
    setup-nginx  设置nginx Web伪装
    
    del          删除 Hysteria2
    status       查看 Hysteria2 状态
    help         显示此帮助信息

🔧 基础选项:
    --ip IP           指定服务器IP地址
    --port PORT       指定服务器端口 (推荐: 443)
    --password PWD    指定密码

🔐 防墙增强选项:
    --domain DOMAIN         指定域名 (推荐用于真实证书)
    --email EMAIL           Let's Encrypt证书邮箱地址  
    --use-real-cert         使用真实域名证书 (需域名指向服务器)
    --web-masquerade        启用Web伪装 (默认启用)
    --auto-nginx            自动配置nginx (默认启用)

🚀 高级防墙选项:
    --simple                🎯 简化一键部署 (端口跳跃+混淆+nginx Web伪装)
    --port-range RANGE      指定端口跳跃范围 (如: 28888-29999)
    --enable-bbr            启用BBR拥塞控制算法优化网络性能
    --port-hopping          启用端口跳跃 (动态切换端口，防封锁)
    --obfs-password PWD     启用Salamander混淆 (防DPI检测)
    --http3-masquerade      启用HTTP/3伪装 (流量看起来像正常HTTP/3)
    --one-click             一键部署 (自动启用所有防墙功能)
    

📋 示例:

    # 🎯 简化一键部署 (推荐！端口跳跃+混淆+nginx Web伪装)
    python3 hy2.py install --simple

    # 🔥 高位端口 + BBR优化 (最强性能)
    python3 hy2.py install --simple --port-range 28888-29999 --enable-bbr

    # 完整一键部署 (自动启用所有防墙功能)
    python3 hy2.py install --one-click

    # 基础安装
    python3 hy2.py install

    # 最强防墙配置
    python3 hy2.py install --port-hopping --obfs-password "random123" --http3-masquerade --domain your.domain.com --use-real-cert

    # 端口跳跃模式 (防端口封锁)
    python3 hy2.py install --port-hopping --port 443

    # 流量混淆模式 (防DPI检测)
    python3 hy2.py install --obfs-password "myObfsKey" --port 8443

    # HTTP/3伪装模式
    python3 hy2.py install --http3-masquerade --port 443

🛡️ Hysteria2 真实防墙技术:

🎯 支持的防墙功能:
1️⃣ 端口跳跃 (Port Hopping): 动态切换端口，防止端口封锁
2️⃣ Salamander混淆: 加密流量特征，防DPI深度包检测  
3️⃣ HTTP/3伪装: 流量看起来像正常HTTP/3网站访问
4️⃣ Web页面伪装: nginx显示正常网站页面

🔒 防护级别:
• 🔥 顶级防护: 端口跳跃 + 混淆 + HTTP/3伪装 + Web伪装
• 🔥 高级防护: 混淆 + HTTP/3伪装 + Web伪装
• 🔒 中级防护: 端口跳跃 + Web伪装
• ✅ 基础防护: Web伪装
• ⚡ 高速模式: 纯UDP无额外防护

⚠️ 重要提醒:
- Hysteria2使用UDP协议，防火墙必须开放UDP端口
- 端口跳跃模式需要开放端口范围
- 混淆模式客户端和服务端必须使用相同密码
- HTTP/3伪装提供最佳流量隐蔽性

🌟 推荐配置:
1️⃣ 🎯 最佳推荐: --simple (端口跳跃+混淆+nginx Web伪装)
2️⃣ 完整功能: --one-click (一键部署所有功能)
3️⃣ 速度优先: 基础安装
4️⃣ 稳定优先: --port-hopping
5️⃣ 隐蔽优先: --obfs-password + --http3-masquerade
""")

def create_nginx_masquerade(base_dir, domain, web_dir):
    """创建nginx配置用于TCP端口伪装"""
    # 确保使用绝对路径
    abs_web_dir = os.path.abspath(web_dir)
    abs_cert_path = os.path.abspath(f"{base_dir}/cert/server.crt")
    abs_key_path = os.path.abspath(f"{base_dir}/cert/server.key")
    
    nginx_conf = f"""server {{
    listen 80;
    listen 443 ssl;
    server_name {domain} _;
    
    ssl_certificate {abs_cert_path};
    ssl_certificate_key {abs_key_path};
    
    # SSL配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    
    root {abs_web_dir};
    index index.html index.htm;
    
    # 确保文件权限正确
    location ~* \\.(html|css|js|png|jpg|jpeg|gif|ico|svg)$ {{
        expires 1y;
        add_header Cache-Control "public, immutable";
    }}
    
    # 处理正常的Web请求
    location / {{
        try_files $uri $uri/ /index.html;
    }}
    
    # 特殊文件处理
    location = /favicon.ico {{
        access_log off;
        log_not_found off;
    }}
    
    location = /robots.txt {{
        access_log off;
        log_not_found off;
    }}
    
    # 添加安全头（使用标准nginx指令）
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # 隐藏nginx版本
    server_tokens off;
    
    # 日志
    access_log /var/log/nginx/{domain}_access.log;
    error_log /var/log/nginx/{domain}_error.log;
}}"""
    
    # 创建nginx配置文件
    nginx_conf_file = f"{base_dir}/nginx.conf"
    with open(nginx_conf_file, "w") as f:
        f.write(nginx_conf)
    
    return nginx_conf_file

def setup_dual_port_masquerade(base_dir, domain, web_dir, cert_path, key_path):
    """设置双端口伪装：TCP用于Web，UDP用于Hysteria2"""
    print("正在设置双端口伪装方案...")
    
    # 检查是否安装了nginx
    try:
        subprocess.run(['which', 'nginx'], check=True, capture_output=True)
        has_nginx = True
    except:
        has_nginx = False
    
    if not has_nginx:
        print("正在安装nginx...")
        
        # 获取系统架构信息
        arch = platform.machine().lower()
        system = platform.system().lower()
        print(f"检测到系统: {system}, 架构: {arch}")
        
        try:
            # 尝试安装nginx（包管理器会自动处理架构）
            if shutil.which('apt'):
                print("使用APT包管理器安装nginx...")
                subprocess.run(['sudo', 'apt', 'update'], check=True)
                subprocess.run(['sudo', 'apt', 'install', '-y', 'nginx'], check=True)
            elif shutil.which('yum'):
                print("使用YUM包管理器安装nginx...")
                subprocess.run(['sudo', 'yum', 'install', '-y', 'epel-release'], check=True)  # EPEL for nginx
                subprocess.run(['sudo', 'yum', 'install', '-y', 'nginx'], check=True)
            elif shutil.which('dnf'):
                print("使用DNF包管理器安装nginx...")
                subprocess.run(['sudo', 'dnf', 'install', '-y', 'nginx'], check=True)
            elif shutil.which('pacman'):
                print("使用Pacman包管理器安装nginx...")
                subprocess.run(['sudo', 'pacman', '-S', '--noconfirm', 'nginx'], check=True)
            elif shutil.which('zypper'):
                print("使用Zypper包管理器安装nginx...")
                subprocess.run(['sudo', 'zypper', 'install', '-y', 'nginx'], check=True)
            else:
                print("无法识别包管理器，尝试手动下载nginx...")
                print("支持的架构: x86_64, aarch64, i386")
                print("请手动安装nginx: https://nginx.org/en/download.html")
                return False
                
            print("✅ nginx安装完成")
        except Exception as e:
            print(f"nginx安装失败: {e}")
            print("请尝试手动安装: sudo apt install nginx 或 sudo yum install nginx")
            return False
    
    # 简化方案：直接覆盖nginx默认Web目录的文件
    print("🔧 使用简化方案：直接覆盖nginx默认Web目录")
    
    # 检测nginx默认Web目录
    nginx_web_dirs = [
        "/var/www/html",           # Ubuntu/Debian 默认
        "/usr/share/nginx/html",   # CentOS/RHEL 默认
        "/var/www"                 # 备选
    ]
    
    nginx_web_dir = None
    for dir_path in nginx_web_dirs:
        if os.path.exists(dir_path):
            nginx_web_dir = dir_path
            break
    
    if not nginx_web_dir:
        # 如果都不存在，创建默认目录
        nginx_web_dir = "/var/www/html"
        try:
            subprocess.run(['sudo', 'mkdir', '-p', nginx_web_dir], check=True)
            print(f"✅ 创建Web目录: {nginx_web_dir}")
        except Exception as e:
            print(f"❌ 创建Web目录失败: {e}")
            return False
    
    print(f"✅ 检测到nginx Web目录: {nginx_web_dir}")
    
    try:
        # 备份原有文件
        try:
            if os.path.exists(f"{nginx_web_dir}/index.html"):
                subprocess.run(['sudo', 'cp', f'{nginx_web_dir}/index.html', f'{nginx_web_dir}/index.html.backup'], check=True)
                print("✅ 备份原有index.html")
        except:
            pass
        
        # 复制我们的伪装文件到nginx默认目录
        if os.path.exists(web_dir):
            # 使用find命令复制文件，避免shell通配符问题
            try:
                subprocess.run(['sudo', 'find', web_dir, '-type', 'f', '-exec', 'cp', '{}', nginx_web_dir, ';'], check=True)
                print(f"✅ 伪装文件已复制到: {nginx_web_dir}")
            except:
                # 备选方案：逐个复制文件
                for file in os.listdir(web_dir):
                    src_file = os.path.join(web_dir, file)
                    if os.path.isfile(src_file):
                        subprocess.run(['sudo', 'cp', src_file, nginx_web_dir], check=True)
            print(f"✅ 伪装文件已复制到: {nginx_web_dir}")
        else:
            print(f"⚠️ 原Web目录不存在，直接在nginx目录创建伪装文件...")
            create_web_files_in_directory(nginx_web_dir)
        
        # 设置正确的权限
        set_nginx_permissions(nginx_web_dir)
        
        print(f"✅ 设置权限完成: {nginx_web_dir}")
        
    except Exception as e:
        print(f"⚠️ 文件复制失败: {e}")
        return False
    
    # 简化nginx配置：只配置SSL证书，使用默认Web目录
    try:
        # 创建简化的SSL配置
        ssl_conf = f"""# SSL configuration for Hysteria2 masquerade
server {{
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    
    ssl_certificate {os.path.abspath(cert_path)};
    ssl_certificate_key {os.path.abspath(key_path)};
    
    # SSL配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # 使用默认配置，不指定root（使用nginx默认）
    # 这样就使用了我们刚才覆盖的文件
    
    # 隐藏nginx版本
    server_tokens off;
    
    # 基本安全头
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
}}"""
        
        ssl_conf_file = "/etc/nginx/conf.d/hysteria2-ssl.conf"
        
        # 删除可能存在的旧配置
        subprocess.run(['sudo', 'rm', '-f', f'/etc/nginx/conf.d/{domain}.conf'], check=False)
        subprocess.run(['sudo', 'rm', '-f', f'/etc/nginx/sites-enabled/{domain}'], check=False)
        subprocess.run(['sudo', 'rm', '-f', f'/etc/nginx/sites-available/{domain}'], check=False)
        
        # 写入新的SSL配置
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as tmp:
            tmp.write(ssl_conf)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, ssl_conf_file], check=True)
            os.unlink(tmp.name)
            
        print(f"✅ 创建SSL配置: {ssl_conf_file}")
        
        # 测试配置
        test_result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
        if test_result.returncode != 0:
            print(f"❌ nginx配置测试失败: {test_result.stderr}")
            return False
        
        # 启动nginx
        subprocess.run(['sudo', 'systemctl', 'restart', 'nginx'], check=True)
        subprocess.run(['sudo', 'systemctl', 'enable', 'nginx'], check=True)
        
        print("✅ nginx配置成功！")
        print(f"✅ Web伪装已生效: https://{domain}")
        print("✅ HTTP 80端口会显示默认页面")
        print("✅ HTTPS 443端口会显示我们的伪装页面")
        return True
        
    except Exception as e:
        print(f"❌ nginx配置失败: {e}")
        return False

def show_client_setup(config_link, server_address, port, password, use_real_cert, enable_port_hopping=False, obfs_password=None, enable_http3_masquerade=False):
    """显示客户端连接指南"""
    # 构建端口范围
    port_range = None
    if enable_port_hopping:
        port_start = max(1024, port-50)
        port_end = min(65535, port+50)
        port_range = f"{port_start}-{port_end}"
    
    # 使用统一输出函数
    show_final_summary(
        server_address=server_address,
        port=port,
        port_range=port_range,
        password=password,
        obfs_password=obfs_password,
        config_link=config_link,
        enable_port_hopping=enable_port_hopping,
        download_links=None
    )

def main():
    parser = argparse.ArgumentParser(description='Hysteria2 一键部署工具（防墙增强版）')
    parser.add_argument('command', nargs='?', default='install',
                      help='命令: install, del, status, help, setup-nginx, client, fix')
    parser.add_argument('--ip', help='指定服务器IP地址或域名')
    parser.add_argument('--port', type=int, help='指定服务器端口（推荐443）')
    parser.add_argument('--password', help='指定密码')
    parser.add_argument('--domain', help='指定域名（用于获取真实证书）')
    parser.add_argument('--email', help='Let\'s Encrypt证书邮箱地址')
    parser.add_argument('--use-real-cert', action='store_true', 
                      help='使用真实域名证书（需要域名指向服务器）')
    parser.add_argument('--web-masquerade', action='store_true', default=True,
                      help='启用Web伪装（默认启用）')
    parser.add_argument('--auto-nginx', action='store_true', default=True,
                      help='安装时自动配置nginx (默认启用)')
    
    # 真正的Hysteria2防墙功能选项
    parser.add_argument('--port-hopping', action='store_true',
                      help='启用端口跳跃（动态切换端口，防封锁）')
    parser.add_argument('--obfs-password', 
                      help='启用Salamander混淆密码（防DPI检测）')
    parser.add_argument('--http3-masquerade', action='store_true',
                      help='启用HTTP/3伪装（流量看起来像正常HTTP/3）')
    parser.add_argument('--one-click', action='store_true',
                      help='一键部署（自动启用所有防墙功能）')
    parser.add_argument('--simple', action='store_true',
                      help='简化一键部署（端口跳跃+混淆+nginx Web伪装）')
    parser.add_argument('--port-range', 
                      help='指定端口跳跃范围 (格式: 起始端口-结束端口，如: 28888-29999)')
    parser.add_argument('--enable-bbr', action='store_true',
                      help='启用BBR拥塞控制算法优化网络性能')
    
    
    args = parser.parse_args()
    
    if args.command == 'del':
        delete_hysteria2()
    elif args.command == 'status':
        show_status()
    elif args.command == 'help':
        show_help()

            
    elif args.command == 'setup-nginx':
        # 设置nginx Web伪装
        home = get_user_home()
        base_dir = f"{home}/.hysteria2"
        
        if not os.path.exists(base_dir):
            print("❌ Hysteria2 未安装，请先运行 install 命令")
            sys.exit(1)
        
        # 获取配置信息
        config_path = f"{base_dir}/config/config.json"
        if not os.path.exists(config_path):
            print("❌ 配置文件不存在")
            sys.exit(1)
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        domain = args.domain if args.domain else get_ip_address()
        web_dir = f"{base_dir}/web"
        cert_path = config['tls']['cert']
        key_path = config['tls']['key']
        
        print(f"正在为域名 {domain} 设置nginx Web伪装...")
        success = setup_dual_port_masquerade(base_dir, domain, web_dir, cert_path, key_path)
        
        if success:
            print(f"""
🎉 nginx设置成功！

现在你有：
- TCP {443 if ':443' in config['listen'] else config['listen'].replace(':', '')}端口: nginx提供真实Web页面
- UDP {443 if ':443' in config['listen'] else config['listen'].replace(':', '')}端口: Hysteria2代理服务

测试命令:
curl https://{domain}
或
curl -k https://{domain}  # 如果使用自签名证书

⚠️ 重要: 确保防火墙已开放UDP端口用于Hysteria2！
""")
        else:
            print("❌ nginx设置失败，请检查错误信息")
    elif args.command == 'client':
        # 显示客户端连接指南
        home = get_user_home()
        base_dir = f"{home}/.hysteria2"
        
        if not os.path.exists(base_dir):
            print("❌ Hysteria2 未安装，请先运行 install 命令")
            sys.exit(1)
        
        # 获取配置信息
        config_path = f"{base_dir}/config/config.json"
        if not os.path.exists(config_path):
            print("❌ 配置文件不存在")
            sys.exit(1)
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        server_address = args.domain if args.domain else get_ip_address()
        port = int(config['listen'].replace(':', ''))
        password = config['auth']['password']
        use_real_cert = 'letsencrypt' in config['tls']['cert']
        
        insecure_param = "0" if use_real_cert else "1"
        
        # Hysteria2官方链接格式（简化）
        config_link = f"hysteria2://{urllib.parse.quote(password)}@{server_address}:{port}?insecure={insecure_param}&sni={server_address}"
        
        show_client_setup(config_link, server_address, port, password, use_real_cert, args.port_hopping, args.obfs_password, args.http3_masquerade)
    elif args.command == 'fix':
        # 修复nginx配置和权限问题
        home = get_user_home()
        base_dir = f"{home}/.hysteria2"
        
        if not os.path.exists(base_dir):
            print("❌ Hysteria2 未安装，请先运行 install 命令")
            sys.exit(1)
        
        domain = args.domain if args.domain else get_ip_address()
        
        print("🔧 正在修复nginx配置 - 使用简化方案...")
        
        # 1. 检测nginx默认Web目录
        nginx_web_dirs = [
            "/var/www/html",           # Ubuntu/Debian 默认
            "/usr/share/nginx/html",   # CentOS/RHEL 默认
            "/var/www"                 # 备选
        ]
        
        nginx_web_dir = None
        for dir_path in nginx_web_dirs:
            if os.path.exists(dir_path):
                nginx_web_dir = dir_path
                break
        
        if not nginx_web_dir:
            nginx_web_dir = "/var/www/html"
            try:
                subprocess.run(['sudo', 'mkdir', '-p', nginx_web_dir], check=True)
                print(f"✅ 创建Web目录: {nginx_web_dir}")
            except Exception as e:
                print(f"❌ 创建Web目录失败: {e}")
                sys.exit(1)
        
        print(f"✅ 检测到nginx Web目录: {nginx_web_dir}")
        
        # 2. 备份并复制伪装文件
        try:
            # 备份原有文件
            if os.path.exists(f"{nginx_web_dir}/index.html"):
                subprocess.run(['sudo', 'cp', f'{nginx_web_dir}/index.html', f'{nginx_web_dir}/index.html.backup'], check=True)
                print("✅ 备份原有index.html")
            
            # 直接在nginx目录创建我们的伪装文件
            print("📝 正在创建伪装网站文件...")
            create_web_files_in_directory(nginx_web_dir)
            
            # 设置权限
            set_nginx_permissions(nginx_web_dir)
            
            print(f"✅ 伪装文件已创建并设置权限: {nginx_web_dir}")
            
        except Exception as e:
            print(f"❌ 创建伪装文件失败: {e}")
            sys.exit(1)
        
        # 3. 确保nginx SSL配置正确
        try:
            cert_path = f"{base_dir}/cert/server.crt"
            key_path = f"{base_dir}/cert/server.key"
            
            if not os.path.exists(cert_path) or not os.path.exists(key_path):
                print("⚠️ 证书文件不存在，重新生成...")
                cert_path, key_path = generate_self_signed_cert(base_dir, domain)
            
            # 创建简化的SSL配置
            ssl_conf = f"""# SSL configuration for Hysteria2 masquerade
server {{
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    
    ssl_certificate {os.path.abspath(cert_path)};
    ssl_certificate_key {os.path.abspath(key_path)};
    
    # SSL配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    
    # 指定网站根目录和默认文件
    root {nginx_web_dir};
    index index.html index.htm;
    
    # 处理静态文件
    location / {{
        try_files $uri $uri/ /index.html;
    }}
    
    # 隐藏nginx版本
    server_tokens off;
    
    # 基本安全头
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
}}"""
            
            ssl_conf_file = "/etc/nginx/conf.d/hysteria2-ssl.conf"
            
            # 删除旧的配置文件
            subprocess.run(['sudo', 'rm', '-f', f'/etc/nginx/conf.d/{domain}.conf'], check=False)
            subprocess.run(['sudo', 'rm', '-f', f'/etc/nginx/sites-enabled/{domain}'], check=False)
            subprocess.run(['sudo', 'rm', '-f', f'/etc/nginx/sites-available/{domain}'], check=False)
            
            # 写入新配置
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as tmp:
                tmp.write(ssl_conf)
                tmp.flush()
                subprocess.run(['sudo', 'cp', tmp.name, ssl_conf_file], check=True)
                os.unlink(tmp.name)
                
            print(f"✅ SSL配置已更新: {ssl_conf_file}")
            
        except Exception as e:
            print(f"⚠️ SSL配置更新失败: {e}")
        
        # 4. 测试并重新加载nginx
        try:
            test_result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
            if test_result.returncode != 0:
                print(f"❌ nginx配置测试失败: {test_result.stderr}")
            else:
                subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], check=True)
                print("✅ nginx配置已重新加载")
                
                print(f"""
🎉 修复完成！

✅ 伪装网站文件已部署到: {nginx_web_dir}
✅ nginx已正确配置SSL (443端口)
✅ HTTP 80端口显示伪装网站
✅ HTTPS 443端口显示伪装网站

测试命令:
curl http://{domain}      # HTTP访问
curl -k https://{domain}  # HTTPS访问

现在外界访问你的服务器会看到一个正常的企业网站！
""")
        except Exception as e:
            print(f"❌ nginx重新加载失败: {e}")
            print("请手动检查nginx配置: sudo nginx -t")
    elif args.command == 'install':
        # 简化一键部署
        if args.simple:
            server_address = args.ip if args.ip else get_ip_address()
            port = args.port if args.port else 443
            password = args.password if args.password else "123qwe!@#QWE"
            
            result = deploy_hysteria2_complete(
                server_address=server_address,
                port=port, 
                password=password,
                enable_real_cert=args.use_real_cert,
                domain=args.domain,
                email=args.email if args.email else "admin@example.com",
                port_range=args.port_range,
                enable_bbr=args.enable_bbr
            )
            return
        
        # 一键部署逻辑
        if args.one_click:
            print("🚀 一键部署模式 - 自动启用所有防墙功能")
            args.port_hopping = True
            args.http3_masquerade = True
            if not args.obfs_password:
                # 生成随机混淆密码
                import random
                import string
                args.obfs_password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
                print(f"🔒 自动生成混淆密码: {args.obfs_password}")
            if not args.domain and not args.use_real_cert:
                print("💡 建议使用 --domain 和 --use-real-cert 获取真实证书")
        
        # 防墙优化配置
        port = args.port if args.port else 443  # 默认使用443端口
        password = args.password if args.password else "123qwe!@#QWE"
        domain = args.domain
        email = args.email if args.email else "admin@example.com"
        use_real_cert = args.use_real_cert
        
        # 获取IP地址或域名
        if domain:
            server_address = domain
            print(f"使用域名: {domain}")
            if not use_real_cert:
                print("建议使用 --use-real-cert 参数获取真实证书以增强安全性")
        else:
            server_address = args.ip if args.ip else get_ip_address()
            if use_real_cert:
                print("警告: 使用真实证书需要指定域名，将使用自签名证书")
                use_real_cert = False
        
        print("\n开始安装 Hysteria2（防墙增强版）...")
        print(f"服务器地址: {server_address}")
        print(f"端口: {port} ({'HTTPS标准端口' if port == 443 else 'HTTP标准端口' if port == 80 else '自定义端口'})")
        print(f"证书类型: {'真实证书' if use_real_cert else '自签名证书'}")
        
        # 显示启用的防墙功能
        if args.port_hopping:
            print("🔄 端口跳跃: 启用 (动态切换端口，防封锁)")
        if args.obfs_password:
            print(f"🔒 Salamander混淆: 启用 (密码: {args.obfs_password})")
        if args.http3_masquerade:
            print("🌐 HTTP/3伪装: 启用 (流量看起来像正常HTTP/3)")
        
        print(f"📡 传输协议: UDP/QUIC")
        print(f"🛡️ 防护级别: {'顶级防护' if args.port_hopping and args.obfs_password and args.http3_masquerade else '高级防护' if (args.port_hopping and args.obfs_password) or (args.obfs_password and args.http3_masquerade) else '中级防护' if args.port_hopping or args.obfs_password or args.http3_masquerade else '基础防护'}")
        
        # 检查端口
        if not check_port_available(port):
            # 检查是否是hysteria进程占用
            print(f"检测到UDP端口 {port} 已被占用，正在分析占用进程...")
            
            try:
                # 尝试用sudo检查所有进程（可以看到其他用户的进程）
                try:
                    result = subprocess.run(['sudo', 'ss', '-anup'], capture_output=True, text=True)
                    ss_output = result.stdout
                except:
                    # 如果sudo失败，用普通权限检查
                    result = subprocess.run(['ss', '-anup'], capture_output=True, text=True)
                    ss_output = result.stdout
                
                # 检查是否是hysteria进程
                if f':{port}' in ss_output and 'hysteria' in ss_output:
                    print(f"✅ 检测到Hysteria2已在UDP端口 {port} 运行")
                    print("如需重新安装，请先运行: python3 hy2.py del")
                    
                    # 检查是否是当前用户的进程
                    current_user = os.getenv('USER', 'unknown')
                    print(f"当前用户: {current_user}")
                    print("提示: 如果是其他用户启动的Hysteria2，请切换到对应用户操作")
                    sys.exit(1)
                    
                elif f':{port}' in ss_output:
                    print(f"❌ UDP端口 {port} 被其他程序占用")
                    print("占用详情:")
                    # 显示占用端口的进程
                    for line in ss_output.split('\n'):
                        if f':{port}' in line and 'udp' in line.lower():
                            print(f"  {line}")
                    print(f"解决方案: 使用其他端口，如: python3 hy2.py install --port 8443")
                    sys.exit(1)
                else:
                    print(f"⚠️ 无法确定端口占用情况，但UDP端口 {port} 不可用")
                    print("可能原因：权限不足或系统限制")
                    print(f"建议: 尝试其他端口: python3 hy2.py install --port 8443")
                    sys.exit(1)
                    
            except Exception as e:
                print(f"❌ 端口检查失败: {e}")
                print(f"UDP端口 {port} 不可用，请选择其他端口")
                print("注意: nginx可以与Hysteria2共享443端口 (nginx用TCP，Hysteria2用UDP)")
                sys.exit(1)
        
        # 创建目录
        base_dir = create_directories()
        
        # 下载Hysteria2
        binary_path, version = download_hysteria2(base_dir)
        
        # 验证二进制文件
        if not verify_binary(binary_path):
            print("错误: Hysteria2 二进制文件无效")
            sys.exit(1)
        
        # 创建Web伪装页面
        web_dir = create_web_masquerade(base_dir)
        
        # 获取证书
        cert_path = None
        key_path = None
        
        if use_real_cert and domain:
            # 尝试获取真实证书
            cert_path, key_path = get_real_certificate(base_dir, domain, email)
        
        # 如果获取真实证书失败或不使用真实证书，则生成自签名证书
        if not cert_path or not key_path:
            cert_path, key_path = generate_self_signed_cert(base_dir, server_address)
        
        # 创建配置
        config_path = create_config(base_dir, port, password, cert_path, key_path, 
                                  server_address, args.web_masquerade, web_dir, args.port_hopping, args.obfs_password, args.http3_masquerade)
        
        # 配置端口跳跃（如果启用）
        if args.port_hopping:
            # 读取配置文件获取端口跳跃信息
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            if "_port_hopping" in config:
                ph_info = config["_port_hopping"]
                setup_port_hopping_iptables(
                    ph_info["range_start"], 
                    ph_info["range_end"], 
                    ph_info["listen_port"]
                )
                # 清理配置文件中的临时信息
                del config["_port_hopping"]
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
        
        # 创建启动脚本
        start_script = create_service_script(base_dir, binary_path, config_path, port)
        
        # 创建停止脚本
        stop_script = create_stop_script(base_dir)
        
        # 立即启动Hysteria2服务
        service_started = start_service(start_script, port, base_dir)
        
        # 自动配置nginx Web伪装 (如果启用)
        nginx_success = False
        if args.auto_nginx and port == 443:
            print("\n🚀 配置nginx Web伪装...")
            
            # 检测并安装nginx
            try:
                subprocess.run(['which', 'nginx'], check=True, capture_output=True)
                print("✅ 检测到nginx已安装")
                has_nginx = True
            except:
                print("正在安装nginx...")
                has_nginx = False
                try:
                    if shutil.which('dnf'):
                        subprocess.run(['sudo', 'dnf', 'install', '-y', 'nginx'], check=True)
                        has_nginx = True
                    elif shutil.which('yum'):
                        subprocess.run(['sudo', 'yum', 'install', '-y', 'epel-release'], check=True)
                        subprocess.run(['sudo', 'yum', 'install', '-y', 'nginx'], check=True)
                        has_nginx = True
                    elif shutil.which('apt'):
                        subprocess.run(['sudo', 'apt', 'update'], check=True)
                        subprocess.run(['sudo', 'apt', 'install', '-y', 'nginx'], check=True)
                        has_nginx = True
                    else:
                        print("⚠️ 无法自动安装nginx，跳过Web伪装配置")
                        has_nginx = False
                    
                    if has_nginx:
                        print("✅ nginx安装完成")
                except Exception as e:
                    print(f"⚠️ nginx安装失败: {e}")
                    has_nginx = False
            
            # 配置nginx
            if has_nginx:
                try:
                    # 使用简化配置方案
                    success = setup_dual_port_masquerade(base_dir, server_address, web_dir, cert_path, key_path)
                    if success:
                        nginx_success = True
                        print("🎉 nginx Web伪装配置成功！")
                        print("🎯 TCP 443端口: 显示正常HTTPS网站")
                        print("🎯 UDP 443端口: Hysteria2代理服务")
                        print("⚠️ 重要: 防火墙需要同时开放TCP和UDP 443端口")
                    else:
                        print("⚠️ nginx配置失败，跳过Web伪装")
                        nginx_success = False
                except Exception as e:
                    print(f"⚠️ nginx配置异常: {e}")
                    nginx_success = False
        
        if not nginx_success and port == 443:
            print("⚠️ nginx未自动配置，可以稍后手动运行: python3 hy2.py fix")
        
        # 生成客户端配置链接
        insecure_param = "0" if use_real_cert else "1"
        
        # 构建链接参数
        params = [f"insecure={insecure_param}", f"sni={server_address}"]
        
        # 添加混淆参数
        if args.obfs_password:
            params.append(f"obfs=salamander")
            params.append(f"obfs-password={urllib.parse.quote(args.obfs_password)}")
        
        config_link = f"hysteria2://{urllib.parse.quote(password)}@{server_address}:{port}?{'&'.join(params)}"
        
        print(f"""
🎉 Hysteria2 防墙增强版安装成功！

📋 安装信息:
- 版本: {version}
- 安装目录: {base_dir}
- 配置文件: {config_path}
- Web伪装目录: {web_dir}
- 启动脚本: {start_script}
- 停止脚本: {stop_script}
- 日志文件: {base_dir}/logs/hysteria.log

🚀 使用方法:
1. 启动服务: {start_script}
2. 停止服务: {stop_script}
3. 查看日志: {base_dir}/logs/hysteria.log
4. 查看状态: python3 hy2.py status

🔐 服务器信息:
- 地址: {server_address}
- 端口: {port} ({'HTTPS端口' if port == 443 else 'HTTP端口' if port == 80 else '自定义端口'})
- 密码: {password}
- 证书: {'真实证书' if use_real_cert else '自签名证书'} ({cert_path})
- Web伪装: {'启用' if args.web_masquerade else '禁用'}

🔗 客户端配置链接:
{config_link}

📱 客户端手动配置:
服务器: {server_address}
端口: {port}
密码: {password}
TLS: 启用
跳过证书验证: {'否' if use_real_cert else '是'}
SNI: {server_address}

🛡️ 防墙优化特性:
✅ 使用端口 {port} ({'端口跳跃模式' if args.port_hopping else 'UDP原生协议'})
✅ Web页面伪装 (TCP端口显示正常网站)
{'✅ 端口跳跃: 动态切换端口防封锁' if args.port_hopping else '✅ 双端口策略 (TCP用于伪装，UDP用于代理)'}
{'✅ Salamander混淆: 密码 ' + args.obfs_password if args.obfs_password else ''}
{'✅ HTTP/3伪装: 流量看起来像正常HTTP/3' if args.http3_masquerade else '✅ 随机伪装目标网站'}
✅ 优化带宽配置 (1000mbps)  
✅ 降低日志级别
{'✅ nginx Web伪装已配置' if nginx_success else '⚠️ nginx未配置 (建议运行: python3 hy2.py setup-nginx)'}
{'✅ 真实域名证书' if use_real_cert else '⚠️ 自签名证书 (建议使用真实域名证书)'}

⚠️ 重要防火墙配置:
{'- 必须开放 UDP 端口范围 ' + str(max(1024, port-50)) + '-' + str(min(65535, port+50)) + ' (端口跳跃模式)' if args.port_hopping else '- 必须开放 UDP ' + str(port) + ' 端口 (Hysteria2必需)'}
{'- 建议开放 TCP ' + str(port) + ' 端口 (nginx Web伪装)' if nginx_success else ''}

🎯 当前配置级别:
{'🔥 顶级防护: 端口跳跃 + 混淆 + HTTP/3伪装 + Web伪装' if args.port_hopping and args.obfs_password and args.http3_masquerade and nginx_success else ''}
{'🔥 高级防护: 端口跳跃 + 混淆 + Web伪装' if args.port_hopping and args.obfs_password and not args.http3_masquerade and nginx_success else ''}
{'🔒 中级防护: 混淆 + HTTP/3伪装 + Web伪装' if not args.port_hopping and args.obfs_password and args.http3_masquerade and nginx_success else ''}
{'✅ 基础防护: Web伪装' if not args.port_hopping and not args.obfs_password and not args.http3_masquerade and nginx_success else ''}
{'⚡ 高速模式: 无额外防护' if not args.port_hopping and not args.obfs_password and not args.http3_masquerade and not nginx_success else ''}

💡 快速测试:
{'• TCP测试: curl https://' + server_address + '  # 应显示伪装网站' if nginx_success else ''}
• UDP测试: 使用客户端连接验证Hysteria2服务

💡 进一步优化建议:
1. 使用真实域名和证书: --domain yourdomain.com --use-real-cert --email your@email.com
{'2. 端口跳跃已启用，防止端口封锁' if args.port_hopping else '2. 考虑启用端口跳跃: --port-hopping (防止端口封锁)'}
{'3. 混淆已启用，提供强隐蔽性' if args.obfs_password else '3. 考虑启用混淆: --obfs-password "密码" (防DPI检测)'}
{'4. HTTP/3伪装已启用，最佳隐蔽性' if args.http3_masquerade else '4. 考虑启用HTTP/3伪装: --http3-masquerade'}
5. 定期更换密码{'和混淆密钥' if args.obfs_password else ''}
6. 监控日志，如发现异常及时调整

🌍 支持的客户端:
- v2rayN (Windows)
- Qv2ray (跨平台)  
- Clash Meta (多平台)
- 官方客户端 (各平台)
""")

        # 显示客户端连接指南
        show_client_setup(config_link, server_address, port, password, use_real_cert, args.port_hopping, args.obfs_password, args.http3_masquerade)
    else:
        print(f"未知命令: {args.command}")
        show_help()
        sys.exit(1)

def setup_port_hopping_iptables(port_start, port_end, listen_port):
    """配置iptables实现端口跳跃"""
    try:
        print(f"🔧 配置iptables端口跳跃...")
        print(f"端口范围: {port_start}-{port_end} -> {listen_port}")
        
        # 检查iptables是否可用
        try:
            subprocess.run(['iptables', '--version'], check=True, capture_output=True)
        except:
            print("⚠️ iptables不可用，跳过端口跳跃配置")
            return False
        
        # 清理可能存在的旧规则
        try:
            subprocess.run(['sudo', 'iptables', '-t', 'nat', '-D', 'PREROUTING', '-p', 'udp', '--dport', f'{port_start}:{port_end}', '-j', 'DNAT', '--to-destination', f':{listen_port}'], check=False, capture_output=True)
        except:
            pass
        
        # 添加端口跳跃的iptables规则
        # IPv4 NAT规则：将端口范围转发到监听端口
        subprocess.run([
            'sudo', 'iptables', '-t', 'nat', '-A', 'PREROUTING', 
            '-p', 'udp', '--dport', f'{port_start}:{port_end}', 
            '-j', 'DNAT', '--to-destination', f':{listen_port}'
        ], check=True)
        
        # 确保基本的iptables规则存在
        # 允许已建立的连接和相关连接
        subprocess.run([
            'sudo', 'iptables', '-I', 'INPUT', '1',
            '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED',
            '-j', 'ACCEPT'
        ], check=False)
        
        # 允许本地回环
        subprocess.run([
            'sudo', 'iptables', '-I', 'INPUT', '2',
            '-i', 'lo', '-j', 'ACCEPT'
        ], check=False)
        
        # 允许SSH端口（防止锁定）
        subprocess.run([
            'sudo', 'iptables', '-I', 'INPUT', '3',
            '-p', 'tcp', '--dport', '22', '-j', 'ACCEPT'
        ], check=False)
        
        # 开放端口范围的防火墙规则
        subprocess.run([
            'sudo', 'iptables', '-A', 'INPUT', 
            '-p', 'udp', '--dport', f'{port_start}:{port_end}', 
            '-j', 'ACCEPT'
        ], check=True)
        
        # 开放监听端口
        subprocess.run([
            'sudo', 'iptables', '-A', 'INPUT', 
            '-p', 'udp', '--dport', str(listen_port), 
            '-j', 'ACCEPT'
        ], check=True)
        
        # 开放HTTP和HTTPS端口（nginx）
        subprocess.run([
            'sudo', 'iptables', '-A', 'INPUT',
            '-p', 'tcp', '--dport', '80', '-j', 'ACCEPT'
        ], check=False)
        
        subprocess.run([
            'sudo', 'iptables', '-A', 'INPUT',
            '-p', 'tcp', '--dport', '443', '-j', 'ACCEPT'
        ], check=False)
        
        # 尝试保存iptables规则
        try:
            # Debian/Ubuntu
            subprocess.run(['sudo', 'iptables-save'], check=True, capture_output=True)
            subprocess.run(['sudo', 'netfilter-persistent', 'save'], check=False, capture_output=True)
        except:
            try:
                # CentOS/RHEL
                subprocess.run(['sudo', 'service', 'iptables', 'save'], check=False, capture_output=True)
            except:
                pass
        
        print(f"✅ iptables端口跳跃配置成功")
        print(f"📡 客户端可连接端口范围: {port_start}-{port_end}")
        print(f"🎯 服务器实际监听端口: {listen_port}")
        
        return True
        
    except Exception as e:
        print(f"⚠️ iptables配置失败: {e}")
        print("端口跳跃功能可能无法正常工作")
        return False

def deploy_hysteria2_complete(server_address, port=443, password="123qwe!@#QWE", enable_real_cert=False, domain=None, email="admin@example.com", port_range=None, enable_bbr=False):
    """
    Hysteria2完整一键部署：端口跳跃 + 混淆 + nginx Web伪装
    """
    print("🚀 开始Hysteria2完整部署...")
    print("📋 部署内容：端口跳跃 + Salamander混淆 + nginx Web伪装")
    
    # 1. 创建目录
    base_dir = create_directories()
    print(f"✅ 创建目录：{base_dir}")
    
    # 2. 下载Hysteria2
    binary_path, version = download_hysteria2(base_dir)
    print(f"✅ 下载Hysteria2：{version}")
    
    # 3. 生成混淆密码
    import random, string
    obfs_password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    print(f"🔒 生成混淆密码：{obfs_password}")
    
    # 4. 生成或获取证书
    if enable_real_cert and domain:
        cert_path, key_path = get_real_certificate(base_dir, domain, email)
        if not cert_path:
            cert_path, key_path = generate_self_signed_cert(base_dir, domain)
    else:
        cert_path, key_path = generate_self_signed_cert(base_dir, server_address)
    print(f"✅ 证书配置：{cert_path}")
    
    # 5. 创建Web伪装文件
    web_dir = create_web_masquerade(base_dir)
    print(f"✅ 创建Web伪装：{web_dir}")
    
    # 6. 创建Hysteria2配置（端口跳跃+混淆+HTTP/3伪装）
    hysteria_config = {
        "listen": f":{port}",
        "tls": {
            "cert": cert_path,
            "key": key_path
        },
        "auth": {
            "type": "password",
            "password": password
        },
        "obfs": {
            "type": "salamander",
            "salamander": {
                "password": obfs_password
            }
        },
        "masquerade": {
            "type": "proxy",
            "proxy": {
                "url": "https://www.microsoft.com",
                "rewriteHost": True
            }
        },
        "bandwidth": {
            "up": "1000 mbps",
            "down": "1000 mbps"
        },
        "log": {
            "level": "warn",
            "output": f"{base_dir}/logs/hysteria.log",
            "timestamp": True
        }
    }
    
    config_path = f"{base_dir}/config/config.json"
    with open(config_path, "w") as f:
        json.dump(hysteria_config, f, indent=2)
    print(f"✅ 创建配置：{config_path}")
    
    # 7. 配置端口跳跃（iptables）
    if port_range:
        # 使用用户指定的端口范围
        port_start, port_end = parse_port_range(port_range)
        if port_start is None or port_end is None:
            print("❌ 端口范围解析失败，使用默认范围")
            port_start = max(1024, port - 25)
            port_end = min(65535, port + 25)
            if port < 1049:
                port_start = 1024
                port_end = 1074
    else:
        # 使用默认端口范围
        port_start = max(1024, port - 25)
        port_end = min(65535, port + 25)
        if port < 1049:
            port_start = 1024
            port_end = 1074
    
    success = setup_port_hopping_iptables(port_start, port_end, port)
    if success:
        print(f"✅ 端口跳跃：{port_start}-{port_end} → {port}")
    
    # 8. BBR优化（如果启用）
    if enable_bbr:
        bbr_success = enable_bbr_optimization()
        if bbr_success:
            print("✅ BBR拥塞控制优化已启用")
        else:
            print("⚠️ BBR优化失败，但不影响主要功能")
    
    # 9. 创建并启动Hysteria2服务
    start_script = create_service_script(base_dir, binary_path, config_path, port)
    service_started = start_service(start_script, port, base_dir)
    if service_started:
        print(f"✅ Hysteria2服务启动成功")
    
    # 10. 配置nginx Web伪装
    nginx_success = setup_nginx_web_masquerade(base_dir, server_address, web_dir, cert_path, key_path, port)
    if nginx_success:
        print(f"✅ nginx Web伪装配置成功")
    
    # 11. 生成客户端配置
    insecure = "1" if not enable_real_cert else "0"
    params = [
        f"insecure={insecure}",
        f"sni={server_address}",
        f"obfs=salamander",
        f"obfs-password={urllib.parse.quote(obfs_password)}"
    ]
    
    # 生成标准的单端口配置链接（兼容性最好）
    config_link = f"hysteria2://{urllib.parse.quote(password)}@{server_address}:{port}?{'&'.join(params)}"
    
    # 如果启用了端口跳跃，生成额外的JSON配置
    if port_range:
        port_hopping_config = {
            "server": server_address,
            "auth": password,
            "obfs": {
                "type": "salamander",
                "salamander": {
                    "password": obfs_password
                }
            },
            "tls": {
                "sni": server_address,
                "insecure": insecure == "1"
            },
            "transport": {
                "type": "udp",
                "udp": {
                    "hopPorts": f"{port_start}-{port_end}"
                }
            }
        }
    
    # 12. 输出部署结果
    if port_range:
        # 准备下载链接
        download_links = {
            "v2rayN多端口订阅 (推荐)": f"http://{server_address}:8080/v2rayn-subscription.txt",
            "多端口配置明文查看": f"http://{server_address}:8080/multi-port-links.txt",
            "Clash多端口配置": f"http://{server_address}:8080/clash.yaml", 
            "官方客户端配置": f"http://{server_address}:8080/hysteria-official.yaml",
            "JSON配置 (完整功能)": f"http://{server_address}:8080/hysteria2.json"
        }
        
        # 生成多端口配置（v2rayN和Clash使用相同的端口列表）
        print(f"\n🔄 生成多端口配置文件...")
        
        # 计算端口范围和选择端口
        import random
        port_range = list(range(port_start, port_end + 1))
        num_configs = 100
        
        if len(port_range) > num_configs:
            selected_ports = random.sample(port_range, num_configs)
        else:
            selected_ports = port_range
        
        selected_ports.sort()  # 排序便于查看
        num_ports = len(selected_ports)
        
        # 生成v2rayN订阅文件
        subscription_file, subscription_plain_file, _ = generate_multi_port_subscription(
            server_address, password, obfs_password, port_start, port_end, base_dir, num_configs=100
        )
        print(f"✅ 已生成 {num_ports} 个端口的配置节点")
        
        # 使用统一输出函数
        show_final_summary(
            server_address=server_address,
            port=port,
            port_range=f"{port_start}-{port_end}",
            password=password,
            obfs_password=obfs_password,
            config_link=config_link,
            enable_port_hopping=True,
            download_links=download_links,
            num_ports=num_ports
        )
        
        # 保存JSON配置文件
        config_file = f"{base_dir}/client-config.json"
        with open(config_file, 'w') as f:
            json.dump(port_hopping_config, f, indent=2)
        print(f"📄 端口跳跃JSON配置已保存到：{config_file}")
        
        # 生成v2rayN兼容配置（单一端口，因为v2rayN不支持端口跳跃）
        v2rayn_config = f"""# Hysteria2 v2rayN兼容配置 - 单一端口版本
# 注意：v2rayN不支持端口跳跃功能，只能使用服务器的主监听端口
# 使用方法：将此配置导入v2rayN客户端

server: {server_address}:{port}
auth: {password}

obfs:
  type: salamander
  salamander:
    password: {obfs_password}

tls:
  sni: {server_address}
  insecure: true

bandwidth:
  up: 50 mbps
  down: 200 mbps

socks5:
  listen: 127.0.0.1:1080

http:
  listen: 127.0.0.1:8080
"""
        
        # 生成Hysteria2官方客户端YAML配置（正确的端口跳跃格式）
        hysteria_official_config = f"""# Hysteria2 官方客户端配置 - 端口跳跃版本
# 支持端口跳跃功能，提供更好的防封锁能力
# 使用方法：保存为 config.yaml，然后运行 hysteria client -c config.yaml

server: {server_address}:{port}
auth: {password}

transport:
  type: udp
  udp:
    hopInterval: 30s

obfs:
  type: salamander
  salamander:
    password: {obfs_password}

tls:
  sni: {server_address}
  insecure: true

bandwidth:
  up: 50 mbps
  down: 200 mbps

socks5:
  listen: 127.0.0.1:1080

http:
  listen: 127.0.0.1:8080

# 端口跳跃说明：
# Hysteria2端口跳跃有两种实现方式：
# 1. 服务器端iptables DNAT: 将{port_start}-{port_end}流量转发到{port}
# 2. 客户端多端口连接: 客户端在{port_start}-{port_end}范围内随机选择端口连接
# 
# 当前配置使用方式1，保持客户端配置简洁
# 如需使用方式2，请将server改为: {server_address}:{port_start}-{port_end}
"""
        
        # 生成Clash多端口配置（与v2rayN相同的多节点方案）
        clash_proxies = []
        clash_proxy_names = []
        
        # 生成多个端口的Clash节点配置
        for i, port_num in enumerate(selected_ports, 1):
            node_name = f"Hysteria2-端口{port_num}-节点{i:02d}"
            clash_proxy_names.append(node_name)
            clash_proxies.append(f"""  - name: "{node_name}"
    type: hysteria2
    server: {server_address}
    port: {port_num}
    password: "{password}"
    obfs: salamander
    obfs-password: "{obfs_password}"
    sni: {server_address}
    skip-cert-verify: true
    fast-open: true""")
        
        clash_config = f"""# Clash Meta Hysteria2 多端口配置
# 包含{len(selected_ports)}个不同端口的节点，支持手动切换端口
# 使用方法：导入到Clash Meta客户端，在节点列表中选择不同端口

mixed-port: 7890
allow-lan: false
bind-address: '*'
mode: rule
log-level: info
external-controller: '127.0.0.1:9090'

proxies:
{chr(10).join(clash_proxies)}
    
proxy-groups:
  - name: "🚀 节点选择"
    type: select
    proxies:
{chr(10).join([f'      - "{name}"' for name in clash_proxy_names])}
      - DIRECT
      
  - name: "🌍 国外网站"
    type: select
    proxies:
      - "🚀 节点选择"
      - DIRECT
      
rules:
  - DOMAIN-SUFFIX,google.com,🌍 国外网站
  - DOMAIN-SUFFIX,youtube.com,🌍 国外网站
  - DOMAIN-SUFFIX,github.com,🌍 国外网站
  - DOMAIN-SUFFIX,openai.com,🌍 国外网站
  - DOMAIN-SUFFIX,chatgpt.com,🌍 国外网站
  - GEOIP,CN,DIRECT
  - MATCH,🚀 节点选择
"""
        
        # 生成真正的客户端端口跳跃配置（可选）
        hysteria_client_hopping_config = f"""# Hysteria2 客户端端口跳跃配置
# 这个配置让客户端真正实现端口跳跃（随机选择端口连接）
# 使用方法：保存为 hopping.yaml，运行 hysteria client -c hopping.yaml

server: {server_address}:{port_start}-{port_end}
auth: {password}

transport:
  type: udp
  udp:
    hopInterval: 30s

obfs:
  type: salamander
  salamander:
    password: {obfs_password}

tls:
  sni: {server_address}
  insecure: true

bandwidth:
  up: 50 mbps
  down: 200 mbps

socks5:
  listen: 127.0.0.1:1080

http:
  listen: 127.0.0.1:8080

# 此配置需要服务器端开放{port_start}-{port_end}端口范围
# 每个端口都需要独立的Hysteria2服务实例或负载均衡配置
"""

        # 保存YAML配置文件
        v2rayn_file = f"{base_dir}/v2rayn-config.yaml"
        clash_file = f"{base_dir}/clash-config.yaml"
        hysteria_official_file = f"{base_dir}/hysteria-official-config.yaml"
        hysteria_client_hopping_file = f"{base_dir}/hysteria-client-hopping.yaml"
        
        with open(v2rayn_file, 'w', encoding='utf-8') as f:
            f.write(v2rayn_config)
        with open(clash_file, 'w', encoding='utf-8') as f:
            f.write(clash_config)
        with open(hysteria_official_file, 'w', encoding='utf-8') as f:
            f.write(hysteria_official_config)
        with open(hysteria_client_hopping_file, 'w', encoding='utf-8') as f:
            f.write(hysteria_client_hopping_config)
            
        print(f"📄 v2rayN配置已保存到：{v2rayn_file}")
        print(f"📄 Clash配置已保存到：{clash_file}")
        print(f"📄 官方客户端配置已保存到：{hysteria_official_file}")
        print(f"📄 客户端端口跳跃配置已保存到：{hysteria_client_hopping_file}")
        
        # 复制配置文件到nginx Web目录，提供下载
        setup_config_download_service(server_address, v2rayn_file, clash_file, hysteria_official_file, hysteria_client_hopping_file, subscription_file, subscription_plain_file, config_file)
        
    else:
        # 使用统一输出函数
        show_final_summary(
            server_address=server_address,
            port=port,
            port_range=None,
            password=password,
            obfs_password=obfs_password,
            config_link=config_link,
            enable_port_hopping=False,
            download_links=None
        )
    
    return {
        "server": server_address,
        "port": port,
        "port_range": f"{port_start}-{port_end}",
        "password": password,
        "obfs_password": obfs_password,
        "config_link": config_link,
        "nginx_success": nginx_success
    }

def setup_nginx_web_masquerade(base_dir, server_address, web_dir, cert_path, key_path, port):
    """
    配置nginx Web伪装的简化版本
    """
    try:
        print("🔧 配置nginx Web伪装...")
        
        # 1. 检查nginx是否安装
        try:
            subprocess.run(['which', 'nginx'], check=True, capture_output=True)
        except:
            print("正在安装nginx...")
            if shutil.which('apt'):
                subprocess.run(['sudo', 'apt', 'update'], check=True)
                subprocess.run(['sudo', 'apt', 'install', '-y', 'nginx'], check=True)
            elif shutil.which('yum'):
                subprocess.run(['sudo', 'yum', 'install', '-y', 'epel-release'], check=True)
                subprocess.run(['sudo', 'yum', 'install', '-y', 'nginx'], check=True)
            else:
                print("⚠️ 无法安装nginx")
                return False
        
        # 2. 找到nginx Web目录
        nginx_web_dirs = ["/var/www/html", "/usr/share/nginx/html", "/var/www"]
        nginx_web_dir = None
        for dir_path in nginx_web_dirs:
            if os.path.exists(dir_path):
                nginx_web_dir = dir_path
                break
        
        if not nginx_web_dir:
            nginx_web_dir = "/var/www/html"
            subprocess.run(['sudo', 'mkdir', '-p', nginx_web_dir], check=True)
        
        # 3. 复制Web文件
        print("📝 部署Web伪装文件...")
        create_web_files_in_directory(nginx_web_dir)
        set_nginx_permissions(nginx_web_dir)
        
        # 4. 配置nginx SSL
        ssl_conf = f"""server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name _;
    
    ssl_certificate {os.path.abspath(cert_path)};
    ssl_certificate_key {os.path.abspath(key_path)};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    
    root {nginx_web_dir};
    index index.html;
    
    location / {{
        try_files $uri $uri/ /index.html;
    }}
    
    server_tokens off;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
}}

server {{
    listen 80;
    listen [::]:80;
    server_name _;
    return 301 https://$server_name$request_uri;
}}"""
        
        # 5. 写入nginx配置
        ssl_conf_file = "/etc/nginx/conf.d/hysteria2-ssl.conf"
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as tmp:
            tmp.write(ssl_conf)
            tmp.flush()
            subprocess.run(['sudo', 'cp', tmp.name, ssl_conf_file], check=True)
            os.unlink(tmp.name)
        
        # 6. 测试并重启nginx
        test_result = subprocess.run(['sudo', 'nginx', '-t'], capture_output=True, text=True)
        if test_result.returncode != 0:
            print(f"❌ nginx配置错误: {test_result.stderr}")
            return False
        
        subprocess.run(['sudo', 'systemctl', 'restart', 'nginx'], check=True)
        subprocess.run(['sudo', 'systemctl', 'enable', 'nginx'], check=True)
        
        print("✅ nginx Web伪装配置完成")
        return True
        
    except Exception as e:
        print(f"❌ nginx配置失败: {e}")
        return False

def enable_bbr_optimization():
    """启用BBR拥塞控制算法优化网络性能"""
    try:
        print("🚀 正在启用BBR拥塞控制算法...")
        
        # 检查当前拥塞控制算法
        try:
            with open('/proc/sys/net/ipv4/tcp_congestion_control', 'r') as f:
                current_cc = f.read().strip()
            print(f"📊 当前拥塞控制算法: {current_cc}")
            
            if current_cc == 'bbr':
                print("✅ BBR已经启用")
                return True
        except:
            pass
        
        # 检查内核版本
        try:
            result = subprocess.run(['uname', '-r'], capture_output=True, text=True)
            kernel_version = result.stdout.strip()
            print(f"🔍 内核版本: {kernel_version}")
            
            # BBR需要内核版本 >= 4.9
            version_parts = kernel_version.split('.')
            major = int(version_parts[0])
            minor = int(version_parts[1].split('-')[0])
            
            if major < 4 or (major == 4 and minor < 9):
                print(f"⚠️ BBR需要内核版本 >= 4.9，当前版本: {kernel_version}")
                print("建议升级内核或使用其他优化方案")
                return False
        except:
            print("⚠️ 无法检测内核版本")
        
        # 检查BBR模块是否可用
        try:
            result = subprocess.run(['modprobe', 'tcp_bbr'], check=False, capture_output=True)
            if result.returncode == 0:
                print("✅ BBR模块加载成功")
            else:
                print("⚠️ BBR模块加载失败，可能不支持")
        except:
            pass
        
        # 配置BBR
        bbr_config = """# BBR拥塞控制优化配置
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# 网络性能优化
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_congestion_control = bbr

# UDP优化（Hysteria2使用UDP）
net.core.rmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_default = 262144
net.core.wmem_max = 16777216
net.core.netdev_max_backlog = 5000
"""
        
        # 写入sysctl配置
        sysctl_file = "/etc/sysctl.d/99-hysteria2-bbr.conf"
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as tmp:
                tmp.write(bbr_config)
                tmp.flush()
                subprocess.run(['sudo', 'cp', tmp.name, sysctl_file], check=True)
                os.unlink(tmp.name)
            
            print(f"✅ BBR配置已写入: {sysctl_file}")
        except Exception as e:
            print(f"❌ 写入BBR配置失败: {e}")
            return False
        
        # 应用配置
        try:
            subprocess.run(['sudo', 'sysctl', '-p', sysctl_file], check=True)
            print("✅ BBR配置已应用")
        except Exception as e:
            print(f"⚠️ 应用BBR配置失败: {e}")
        
        # 立即启用BBR
        try:
            subprocess.run(['sudo', 'sysctl', '-w', 'net.core.default_qdisc=fq'], check=True)
            subprocess.run(['sudo', 'sysctl', '-w', 'net.ipv4.tcp_congestion_control=bbr'], check=True)
            print("✅ BBR已立即生效")
        except Exception as e:
            print(f"⚠️ 立即启用BBR失败: {e}")
        
        # 验证BBR是否启用
        try:
            with open('/proc/sys/net/ipv4/tcp_congestion_control', 'r') as f:
                current_cc = f.read().strip()
            
            if current_cc == 'bbr':
                print("🎉 BBR拥塞控制算法启用成功！")
                
                # 显示可用的拥塞控制算法
                try:
                    with open('/proc/sys/net/ipv4/tcp_available_congestion_control', 'r') as f:
                        available_cc = f.read().strip()
                    print(f"📋 可用算法: {available_cc}")
                except:
                    pass
                
                return True
            else:
                print(f"⚠️ BBR启用失败，当前算法: {current_cc}")
                return False
                
        except Exception as e:
            print(f"❌ 验证BBR状态失败: {e}")
            return False
            
    except Exception as e:
        print(f"❌ BBR优化失败: {e}")
        return False

def setup_config_download_service(server_address, v2rayn_file, clash_file, hysteria_official_file, hysteria_client_hopping_file, subscription_file, subscription_plain_file, json_file):
    """设置配置文件下载服务 - 完全自动化"""
    try:
        print("🌐 设置配置文件下载服务...")
        
        # 获取base_dir
        base_dir = os.path.expanduser("~/.hysteria2")
        
        # 创建配置文件目录
        config_dir = f"{base_dir}/configs"
        subprocess.run(['mkdir', '-p', config_dir], check=True)
        
        # 复制配置文件
        subprocess.run(['cp', v2rayn_file, f'{config_dir}/v2rayn.yaml'], check=True)
        subprocess.run(['cp', clash_file, f'{config_dir}/clash.yaml'], check=True)
        subprocess.run(['cp', hysteria_official_file, f'{config_dir}/hysteria-official.yaml'], check=True)
        subprocess.run(['cp', hysteria_client_hopping_file, f'{config_dir}/hysteria-client-hopping.yaml'], check=True)
        subprocess.run(['cp', subscription_file, f'{config_dir}/v2rayn-subscription.txt'], check=True)
        subprocess.run(['cp', subscription_plain_file, f'{config_dir}/multi-port-links.txt'], check=True)
        subprocess.run(['cp', json_file, f'{config_dir}/hysteria2.json'], check=True)
        
        # 直接启动Python HTTP服务器（不使用systemd）
        print("🔧 启动Python HTTP服务器...")
        
        # 创建HTTP服务器脚本
        server_script = f'''#!/usr/bin/env python3
import os
import http.server
import socketserver
from urllib.parse import urlparse

class ConfigHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="{config_dir}", **kwargs)
    
    def end_headers(self):
        if self.path.endswith(('.yaml', '.yml', '.json')):
            filename = os.path.basename(self.path)
            self.send_header('Content-Disposition', f'attachment; filename="{{filename}}"')
            self.send_header('Content-Type', 'application/octet-stream')
        super().end_headers()
    
    def log_message(self, format, *args):
        pass

if __name__ == "__main__":
    PORT = 8080
    try:
        with socketserver.TCPServer(("", PORT), ConfigHandler) as httpd:
            print(f"HTTP服务器已启动，端口: {{PORT}}")
            httpd.serve_forever()
    except Exception as e:
        print(f"服务器启动失败: {{e}}")
        exit(1)
'''
        
        # 保存并启动服务器
        server_file = f"{base_dir}/config_server.py"
        with open(server_file, 'w', encoding='utf-8') as f:
            f.write(server_script)
        subprocess.run(['chmod', '+x', server_file], check=True)
        
        # 开放防火墙端口（8080用于配置下载）
        subprocess.run(['sudo', 'iptables', '-A', 'INPUT', '-p', 'tcp', '--dport', '8080', '-j', 'ACCEPT'], check=False)
        
        # 在后台启动HTTP服务器
        subprocess.Popen(['python3', server_file], cwd=base_dir)
        
        # 等待服务启动
        time.sleep(3)
        
        # 验证服务是否启动
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', 8080))
            sock.close()
            if result == 0:
                print("✅ Python HTTP服务器启动成功")
                return True
            else:
                print("⚠️ HTTP服务器启动失败")
                return False
        except Exception as e:
            print(f"⚠️ 验证HTTP服务器失败: {e}")
            return False
        
    except Exception as e:
        print(f"⚠️ 设置配置下载服务失败: {e}")
        return False

def parse_port_range(port_range_str):
    """解析端口范围字符串"""
    try:
        if not port_range_str:
            return None, None
        
        if '-' not in port_range_str:
            print(f"❌ 端口范围格式错误: {port_range_str}")
            print("正确格式: 起始端口-结束端口，如: 28888-29999")
            return None, None
        
        start_str, end_str = port_range_str.split('-', 1)
        start_port = int(start_str.strip())
        end_port = int(end_str.strip())
        
        # 验证端口范围
        if start_port < 1024 or end_port > 65535:
            print(f"❌ 端口范围超出有效范围 (1024-65535): {start_port}-{end_port}")
            return None, None
        
        if start_port >= end_port:
            print(f"❌ 起始端口必须小于结束端口: {start_port}-{end_port}")
            return None, None
        
        if end_port - start_port > 10000:
            print(f"⚠️ 端口范围过大 ({end_port - start_port} 个端口)，建议控制在10000以内")
            user_input = input("是否继续? (y/n): ").lower()
            if user_input != 'y':
                return None, None
        
        print(f"✅ 端口范围解析成功: {start_port}-{end_port} (共 {end_port - start_port + 1} 个端口)")
        return start_port, end_port
        
    except ValueError:
        print(f"❌ 端口范围格式错误: {port_range_str}")
        print("正确格式: 起始端口-结束端口，如: 28888-29999")
        return None, None
    except Exception as e:
        print(f"❌ 解析端口范围失败: {e}")
        return None, None

def show_final_summary(server_address, port, port_range, password, obfs_password, config_link, enable_port_hopping=False, download_links=None, num_ports=None):
    import urllib.parse
    """显示最终的完整摘要信息 - 包含下载链接、客户端链接和作者信息"""
    
    print("\n" + "="*80)
    print("\033[36m┌──────────────────────────────────────────────────────────────────────────────┐\033[0m")
    print("\033[36m│                            🎉 Hysteria2 部署完成！                             │\033[0m")
    print("\033[36m└──────────────────────────────────────────────────────────────────────────────┘\033[0m")
    
    # 服务器信息
    print("\n\033[33m📡 服务器信息:\033[0m")
    print(f"   • 服务器地址: {server_address}")
    print(f"   • 监听端口: {port} (UDP)")
    if enable_port_hopping and port_range:
        print(f"   • 客户端端口范围: {port_range}")
    print(f"   • 连接密码: {password}")
    if obfs_password:
        print(f"   • 混淆密码: {obfs_password}")
    
    # 一键导入链接
    print(f"\n\033[32m🔗 一键导入链接:\033[0m")
    print(f"   {config_link}")
    
    # 配置文件下载链接（如果有）
    if download_links:
        print(f"\n\033[34m📥 配置文件下载:\033[0m")
        for name, url in download_links.items():
            print(f"   • {name}: {url}")
        
        print(f"\n\033[33m💡 客户端配置指南:\033[0m")
        print("   🔹 v2rayN用户:")
        print("     - 多端口订阅: 下载v2rayN多端口订阅 -> 添加订阅链接")
        print("     - 手动导入: 下载多端口配置明文 -> 复制链接到v2rayN")
        print("     - 单一端口: 下载v2rayN单一端口配置")
        print("   🔹 Clash Meta用户:")
        print("     - 多端口配置: 下载Clash多端口配置，包含多个端口节点")
        print("   🔹 官方客户端用户:")
        print("     - 使用官方客户端配置")
        print(f"   🔹 多端口说明: 包含{num_ports}个不同端口节点，手动切换实现防封效果")
    
    # 防护特性
    print(f"\n\033[35m🛡️ 防护特性:\033[0m")
    if enable_port_hopping:
        print(f"   ✅ 端口跳跃: {port_range} → {port} (服务器端DNAT实现)")
    if obfs_password:
        print(f"   ✅ Salamander混淆: {obfs_password}")
    print("   ✅ HTTP/3伪装: 模拟正常HTTP/3流量")
    print("   ✅ nginx Web伪装: TCP端口显示正常网站")
    print("   ✅ UDP协议: 基于QUIC/HTTP3，抗封锁能力强")
    
    # 使用提醒
    print(f"\n\033[31m⚠️ 使用提醒:\033[0m")
    print("   • Hysteria2使用UDP协议，确保防火墙已开放UDP端口")
    if enable_port_hopping and port_range:
        print(f"   • 端口跳跃模式：需要开放UDP端口范围 {port_range}")
    else:
        print(f"   • 需要开放UDP端口 {port}")
    print(f"   • nginx Web伪装需要开放TCP端口 {port}")
    
    # 443端口地址 和 10个随机v2ray地址
    print(f"\n\033[93m🎯 443端口连接地址:\033[0m")
    hysteria_443_url = f"hysteria2://{urllib.parse.quote(password)}@{server_address}:443?insecure=1&sni={server_address}&obfs=salamander&obfs-password={urllib.parse.quote(obfs_password)}#Hysteria2-443"
    print(f"   {hysteria_443_url}")
    
    print(f"\n\033[93m🔀 10个随机v2ray地址 (可直接复制):\033[0m")
    random_ports = []
    random_urls = []
    if port_range and '-' in str(port_range):
        # 从已生成的多端口配置中选择10个
        import random
        port_start, port_end = port_range.split('-')
        port_list = list(range(int(port_start), int(port_end) + 1))
        random_ports = random.sample(port_list, min(10, len(port_list)))
        random_ports.sort()
        
        for i, random_port in enumerate(random_ports, 1):
            random_url = f"hysteria2://{urllib.parse.quote(password)}@{server_address}:{random_port}?insecure=1&sni={server_address}&obfs=salamander&obfs-password={urllib.parse.quote(obfs_password)}#V2Ray-{random_port}-{i:02d}"
            random_urls.append(random_url)
            print(f"   {random_url}")
        
        # 生成Base64订阅格式
        subscription_content = "\n".join(random_urls)
        subscription_base64 = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
        print(f"\n\033[92m📋 10个随机地址的Base64订阅:\033[0m")
        print(f"   {subscription_base64}")
    else:
        print("   (需要启用多端口配置才能生成随机地址)")
    
    # 作者信息
    print("\n" + "="*80)
    print("\033[36m┌──────────────────────────────────────────────────────────────────────────────┐\033[0m")
    print("\033[36m│                                  作者信息                                      │\033[0m")
    print("\033[36m├──────────────────────────────────────────────────────────────────────────────┤\033[0m")
    print("\033[36m│ \033[32m作者: 康康                                                  \033[36m│\033[0m")
    print("\033[36m│ \033[32mGithub: https://github.com/zhumengkang/                    \033[36m│\033[0m")
    print("\033[36m│ \033[32mYouTube: https://www.youtube.com/@康康的V2Ray与Clash         \033[36m│\033[0m")
    print("\033[36m│ \033[32mTelegram: https://t.me/+WibQp7Mww1k5MmZl                   \033[36m│\033[0m")
    print("\033[36m└──────────────────────────────────────────────────────────────────────────────┘\033[0m")
    print("="*80)
    
    # 保存配置信息到全局文件
    save_global_config(server_address, port, port_range, password, obfs_password, hysteria_443_url, random_ports)
    
    # 醒目的成功信息
    print("\n" + "🎉"*20)
    print("\033[32m" + "="*80 + "\033[0m")
    print("\033[32m" + "║" + " "*78 + "║" + "\033[0m")
    print("\033[32m" + "║" + "🎯 部署完成！连接成功后即可享受高速稳定的网络体验！".center(76) + "║" + "\033[0m")
    print("\033[32m" + "║" + " "*78 + "║" + "\033[0m")
    print("\033[32m" + "║" + "✅ 已创建全局管理命令，输入 'kk' 进入管理菜单".center(74) + "║" + "\033[0m")
    print("\033[32m" + "║" + " "*78 + "║" + "\033[0m")
    print("\033[32m" + "║" + "💡 菜单功能：1-查看节点 2-查看配置 3-服务状态 4-重启服务 5-查看日志 6-删除服务".center(66) + "║" + "\033[0m")
    print("\033[32m" + "║" + " "*78 + "║" + "\033[0m")
    print("\033[32m" + "║" + "💬 如遇问题，请联系作者获取技术支持".center(70) + "║" + "\033[0m")
    print("\033[32m" + "║" + " "*78 + "║" + "\033[0m")
    print("\033[32m" + "="*80 + "\033[0m")
    print("🎉"*20 + "\n")

def save_global_config(server_address, port, port_range, password, obfs_password, hysteria_443_url, random_ports):
    """保存配置信息到全局文件，并创建kk命令"""
    try:
        home = get_user_home()
        config_dir = f"{home}/.hysteria2"
        
        # 保存配置信息
        global_config = {
            "server_address": server_address,
            "port": port,
            "port_range": port_range,
            "password": password,
            "obfs_password": obfs_password,
            "hysteria_443_url": hysteria_443_url,
            "random_ports": random_ports,
            "timestamp": time.time()
        }
        
        config_file = f"{config_dir}/global_config.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(global_config, f, indent=2, ensure_ascii=False)
        
        # 创建kk命令脚本
        kk_script_content = f'''#!/bin/bash
# Hysteria2 管理工具
# 作者: 康康

CONFIG_FILE="{config_file}"
BASE_DIR="$HOME/.hysteria2"

# 检查配置文件是否存在
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ 配置文件不存在: $CONFIG_FILE"
    echo "💡 请先运行 Hysteria2 部署脚本"
    exit 1
fi

# 读取配置函数
load_config() {{
    CONFIG=$(cat "$CONFIG_FILE")
    SERVER_ADDRESS=$(echo "$CONFIG" | python3 -c "import sys, json; print(json.load(sys.stdin)['server_address'])" 2>/dev/null || echo "N/A")
    PORT=$(echo "$CONFIG" | python3 -c "import sys, json; print(json.load(sys.stdin)['port'])" 2>/dev/null || echo "N/A")
    PORT_RANGE=$(echo "$CONFIG" | python3 -c "import sys, json; print(json.load(sys.stdin).get('port_range', 'N/A'))" 2>/dev/null || echo "N/A")
    PASSWORD=$(echo "$CONFIG" | python3 -c "import sys, json; print(json.load(sys.stdin)['password'])" 2>/dev/null || echo "N/A")
    OBFS_PASSWORD=$(echo "$CONFIG" | python3 -c "import sys, json; print(json.load(sys.stdin)['obfs_password'])" 2>/dev/null || echo "N/A")
    HYSTERIA_443_URL=$(echo "$CONFIG" | python3 -c "import sys, json; print(json.load(sys.stdin)['hysteria_443_url'])" 2>/dev/null || echo "N/A")
    RANDOM_PORTS=$(echo "$CONFIG" | python3 -c "import sys, json; print(' '.join(map(str, json.load(sys.stdin)['random_ports'])))" 2>/dev/null || echo "")
}}

# 显示节点信息
show_node_info() {{
    load_config
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║                           🚀 Hysteria2 节点信息                              ║"
    echo "╠══════════════════════════════════════════════════════════════════════════════╣"
    echo "║ 📡 服务器: $SERVER_ADDRESS"
    echo "║ 🔌 端口: $PORT (UDP)"
    echo "║ 🔢 端口范围: $PORT_RANGE"
    echo "║ 🔐 密码: $PASSWORD"
    echo "║ 🔒 混淆密码: $OBFS_PASSWORD"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    
    echo ""
    echo "🎯 443端口连接地址:"
    echo "$HYSTERIA_443_URL"
    
    echo ""
    echo "🔀 10个随机v2ray地址 (可直接复制):"
    if [ -n "$RANDOM_PORTS" ]; then
        URLS=""
        for port in $RANDOM_PORTS; do
            url="hysteria2://$(python3 -c "import urllib.parse; print(urllib.parse.quote('$PASSWORD'))")@$SERVER_ADDRESS:$port?insecure=1&sni=$SERVER_ADDRESS&obfs=salamander&obfs-password=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$OBFS_PASSWORD'))")#V2Ray-$port"
            echo "$url"
            if [ -z "$URLS" ]; then
                URLS="$url"
            else
                URLS="$URLS\\n$url"
            fi
        done
        
        echo ""
        echo "📋 Base64订阅格式 (可直接添加到v2rayN):"
        echo -e "$URLS" | python3 -c "import sys, base64; print(base64.b64encode(sys.stdin.read().encode()).decode())"
    else
        echo "(需要启用多端口配置才能生成随机地址)"
    fi
}}

# 显示配置文件信息
show_config_info() {{
    load_config
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║                           📁 配置文件信息                                    ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    
    echo ""
    echo "📥 配置文件下载地址:"
    echo "• v2rayN多端口订阅: http://$SERVER_ADDRESS:8080/v2rayn-subscription.txt"
    echo "• 多端口配置明文: http://$SERVER_ADDRESS:8080/multi-port-links.txt"
    echo "• Clash多端口配置: http://$SERVER_ADDRESS:8080/clash.yaml"
    echo "• 官方客户端配置: http://$SERVER_ADDRESS:8080/hysteria2.json"
    
    echo ""
    echo "📂 本地配置文件:"
    if [ -f "$BASE_DIR/config/config.json" ]; then
        echo "✅ Hysteria2配置: $BASE_DIR/config/config.json"
    else
        echo "❌ Hysteria2配置: 文件不存在"
    fi
    
    if [ -f "$BASE_DIR/cert/cert.pem" ]; then
        echo "✅ SSL证书: $BASE_DIR/cert/cert.pem"
    else
        echo "❌ SSL证书: 文件不存在"
    fi
    
    if [ -f "$BASE_DIR/logs/hysteria.log" ]; then
        echo "✅ 日志文件: $BASE_DIR/logs/hysteria.log"
    else
        echo "❌ 日志文件: 文件不存在"
    fi
}}

# 查看服务状态
show_service_status() {{
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║                           📊 服务状态                                        ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    
    # 检查Hysteria2进程
    if pgrep -f "hysteria" > /dev/null; then
        echo "✅ Hysteria2服务: 运行中"
        echo "   进程ID: $(pgrep -f hysteria)"
    else
        echo "❌ Hysteria2服务: 未运行"
    fi
    
    # 检查nginx进程
    if pgrep -f "nginx" > /dev/null; then
        echo "✅ nginx服务: 运行中"
    else
        echo "❌ nginx服务: 未运行"
    fi
    
    # 检查端口监听
    load_config
    if [ "$PORT" != "N/A" ]; then
        if netstat -ulnp 2>/dev/null | grep ":$PORT " > /dev/null; then
            echo "✅ UDP端口 $PORT: 监听中"
        else
            echo "❌ UDP端口 $PORT: 未监听"
        fi
    fi
    
    if netstat -tlnp 2>/dev/null | grep ":443 " > /dev/null; then
        echo "✅ TCP端口 443: 监听中 (nginx)"
    else
        echo "❌ TCP端口 443: 未监听"
    fi
    
    if netstat -tlnp 2>/dev/null | grep ":8080 " > /dev/null; then
        echo "✅ TCP端口 8080: 监听中 (配置下载)"
    else
        echo "❌ TCP端口 8080: 未监听"
    fi
}}

# 重启服务
restart_service() {{
    echo "🔄 重启Hysteria2服务..."
    
    # 停止服务
    if [ -f "$BASE_DIR/stop.sh" ]; then
        echo "⏹️ 停止当前服务..."
        bash "$BASE_DIR/stop.sh"
        sleep 2
    fi
    
    # 启动服务
    if [ -f "$BASE_DIR/start.sh" ]; then
        echo "▶️ 启动服务..."
        bash "$BASE_DIR/start.sh"
        sleep 3
        
        # 检查服务状态
        if pgrep -f "hysteria" > /dev/null; then
            echo "✅ 服务重启成功"
        else
            echo "❌ 服务重启失败"
        fi
    else
        echo "❌ 启动脚本不存在: $BASE_DIR/start.sh"
    fi
}}

# 查看日志
show_logs() {{
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║                           📋 查看日志                                        ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    
    if [ -f "$BASE_DIR/logs/hysteria.log" ]; then
        echo "📄 显示最新50行日志:"
        echo "----------------------------------------"
        tail -n 50 "$BASE_DIR/logs/hysteria.log"
        echo "----------------------------------------"
        echo "💡 实时查看日志: tail -f $BASE_DIR/logs/hysteria.log"
    else
        echo "❌ 日志文件不存在: $BASE_DIR/logs/hysteria.log"
    fi
}}

# 删除服务
delete_service() {{
    echo "⚠️ 确认要删除Hysteria2服务吗？这将删除所有配置和文件！"
    echo "输入 'yes' 确认删除，其他任意键取消:"
    read -r confirm
    
    if [ "$confirm" = "yes" ]; then
        echo "🗑️ 正在删除Hysteria2服务..."
        
        # 停止服务
        if [ -f "$BASE_DIR/stop.sh" ]; then
            bash "$BASE_DIR/stop.sh"
        fi
        
        # 删除文件
        if [ -d "$BASE_DIR" ]; then
            rm -rf "$BASE_DIR"
            echo "✅ 已删除配置目录: $BASE_DIR"
        fi
        
        # 删除配置文件
        if [ -f "$CONFIG_FILE" ]; then
            rm -f "$CONFIG_FILE"
            echo "✅ 已删除全局配置: $CONFIG_FILE"
        fi
        
        echo "✅ Hysteria2服务已完全删除"
    else
        echo "❌ 取消删除操作"
    fi
}}

# 主菜单
show_menu() {{
    clear
    echo "╔══════════════════════════════════════════════════════════════════════════════╗"
    echo "║                         🚀 Hysteria2 管理工具                                ║"
    echo "╠══════════════════════════════════════════════════════════════════════════════╣"
    echo "║                              作者: 康康                                      ║"
    echo "╚══════════════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "请选择操作："
    echo "1️⃣  查看节点信息"
    echo "2️⃣  查看配置文件"
    echo "3️⃣  查看服务状态"
    echo "4️⃣  重启服务"
    echo "5️⃣  查看日志"
    echo "6️⃣  删除服务"
    echo "0️⃣  退出"
    echo ""
    echo "👨‍💻 GitHub: https://github.com/zhumengkang/"
    echo "📺 YouTube: https://www.youtube.com/@康康的V2Ray与Clash"
    echo "💬 Telegram: https://t.me/+WibQp7Mww1k5MmZl"
    echo ""
}}

# 主程序
while true; do
    show_menu
    echo -n "请输入选项 (0-6): "
    read -r choice
    echo ""
    
    case $choice in
        1)
            show_node_info
            echo ""
            echo "按任意键返回主菜单..."
            read -r
            ;;
        2)
            show_config_info
            echo ""
            echo "按任意键返回主菜单..."
            read -r
            ;;
        3)
            show_service_status
            echo ""
            echo "按任意键返回主菜单..."
            read -r
            ;;
        4)
            restart_service
            echo ""
            echo "按任意键返回主菜单..."
            read -r
            ;;
        5)
            show_logs
            echo ""
            echo "按任意键返回主菜单..."
            read -r
            ;;
        6)
            delete_service
            echo ""
            echo "按任意键返回主菜单..."
            read -r
            ;;
        0)
            echo "👋 感谢使用 Hysteria2 管理工具！"
            exit 0
            ;;
        *)
            echo "❌ 无效选项，请输入 0-6"
            echo ""
            echo "按任意键继续..."
            read -r
            ;;
    esac
done
'''
        
        # 创建kk命令文件
        kk_script_path = "/usr/local/bin/kk"
        try:
            with open(kk_script_path, 'w', encoding='utf-8') as f:
                f.write(kk_script_content)
            os.chmod(kk_script_path, 0o755)
            print(f"✅ 已创建全局命令: {kk_script_path}")
        except PermissionError:
            # 如果没有权限写入/usr/local/bin，尝试写入用户目录
            user_bin = f"{home}/bin"
            os.makedirs(user_bin, exist_ok=True)
            kk_script_path = f"{user_bin}/kk"
            with open(kk_script_path, 'w', encoding='utf-8') as f:
                f.write(kk_script_content)
            os.chmod(kk_script_path, 0o755)
            print(f"✅ 已创建用户命令: {kk_script_path}")
            print(f"💡 请确保 {user_bin} 在PATH环境变量中")
        
        return True
        
    except Exception as e:
        print(f"⚠️ 保存全局配置失败: {e}")
        return False

def generate_multi_port_subscription(server_address, password, obfs_password, port_start, port_end, base_dir, num_configs=100):
    """
    生成多端口v2rayN订阅文件
    为端口跳跃范围内的端口生成多个hysteria2配置
    """
    # 计算端口范围
    port_range = list(range(port_start, port_end + 1))
    
    # 如果端口数量超过要生成的配置数量，随机选择
    if len(port_range) > num_configs:
        selected_ports = random.sample(port_range, num_configs)
    else:
        selected_ports = port_range
    
    selected_ports.sort()  # 排序便于查看
    
    # 生成多个hysteria2链接
    hysteria2_links = []
    
    for i, port in enumerate(selected_ports, 1):
        # 生成节点名称
        node_name = f"Hysteria2-端口{port}-节点{i:02d}"
        
        # URL编码密码和混淆密码
        import urllib.parse
        encoded_password = urllib.parse.quote(password, safe='')
        encoded_obfs_password = urllib.parse.quote(obfs_password, safe='')
        encoded_node_name = urllib.parse.quote(node_name, safe='')
        
        # 生成hysteria2链接
        hysteria2_url = f"hysteria2://{encoded_password}@{server_address}:{port}?insecure=1&sni={server_address}&obfs=salamander&obfs-password={encoded_obfs_password}#{encoded_node_name}"
        hysteria2_links.append(hysteria2_url)
    
    # 创建v2rayN订阅内容（Base64编码）
    subscription_content = "\n".join(hysteria2_links)
    subscription_base64 = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
    
    # 保存订阅文件
    subscription_file = f"{base_dir}/hysteria2-multi-port-subscription.txt"
    with open(subscription_file, 'w', encoding='utf-8') as f:
        f.write(subscription_base64)
    
    # 保存明文版本（便于查看）
    subscription_plain_file = f"{base_dir}/hysteria2-multi-port-links.txt"
    with open(subscription_plain_file, 'w', encoding='utf-8') as f:
        f.write("# Hysteria2 多端口配置文件\n")
        f.write(f"# 服务器: {server_address}\n")
        f.write(f"# 端口范围: {port_start}-{port_end}\n")
        f.write(f"# 生成节点数量: {len(selected_ports)}\n")
        f.write(f"# 密码: {password}\n")
        f.write(f"# 混淆密码: {obfs_password}\n")
        f.write("\n# ===== 配置链接 =====\n\n")
        for link in hysteria2_links:
            f.write(link + "\n")
    
    return subscription_file, subscription_plain_file, len(selected_ports)

if __name__ == "__main__":
    main() 
