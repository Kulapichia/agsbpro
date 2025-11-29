#!/bin/bash

ROOT_PASSWORD="acW8E!X#hX0ktRMs"
PROJECT_ID=$(gcloud config get-value project)
MAX_CONCURRENT=12  # 最大并发数

echo "开始为项目 $PROJECT_ID 中的所有VM实例配置SSH root密码登录..."
echo "🔧 使用多线程处理，最大并发数: $MAX_CONCURRENT"

# 获取所有实例到数组中
echo "正在获取所有运行中的实例..."
mapfile -t instance_list < <(gcloud compute instances list --filter="status=RUNNING" --format="value(name,zone)")

if [ ${#instance_list[@]} -eq 0 ]; then
    echo "❌ 没有找到任何运行中的实例"
    exit 1
fi

echo "找到以下正在运行的实例："
for instance_info in "${instance_list[@]}"; do
    IFS=$'\t' read -r name zone <<< "$instance_info"
    echo "  - $name ($zone)"
done

echo ""
echo "总共找到 ${#instance_list[@]} 个实例，开始并行修复..."

# 创建增强的修复脚本
cat > /tmp/fix_ssh_enhanced.sh << 'EOF'
#!/bin/bash
set -e  # 遇到错误立即退出

echo "=== 开始增强SSH配置修复 ==="

# 设置root密码
echo "步骤1: 设置root密码..."
echo "root:acW8E!X#hX0ktRMs" | sudo chpasswd
if [ $? -eq 0 ]; then
    echo "✅ root密码设置成功"
else
    echo "❌ root密码设置失败"
    exit 1
fi

# 备份所有SSH相关配置
echo "步骤2: 备份SSH配置文件..."
timestamp=$(date +%Y%m%d_%H%M%S)
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup.$timestamp
if [ -d /etc/ssh/sshd_config.d ]; then
    sudo cp -r /etc/ssh/sshd_config.d /etc/ssh/sshd_config.d.backup.$timestamp
fi

# 强制修改主配置文件
echo "步骤3: 修改主SSH配置文件..."
sudo sed -i '/^#*PermitRootLogin/d' /etc/ssh/sshd_config
sudo sed -i '/^#*PasswordAuthentication/d' /etc/ssh/sshd_config
sudo sed -i '/^#*ChallengeResponseAuthentication/d' /etc/ssh/sshd_config
sudo sed -i '/^#*PubkeyAuthentication/d' /etc/ssh/sshd_config

# 添加新配置
cat << 'CONFIG' | sudo tee -a /etc/ssh/sshd_config
# Enhanced SSH Configuration for Password Authentication
PermitRootLogin yes
PasswordAuthentication yes
ChallengeResponseAuthentication no
PubkeyAuthentication yes
UsePAM yes
CONFIG

echo "✅ 主配置文件修改完成"

# 处理Ubuntu Cloud镜像的配置目录
echo "步骤4: 处理Cloud镜像特殊配置..."
if [ -d /etc/ssh/sshd_config.d ]; then
    # 禁用或修改所有可能干扰的配置文件
    for config_file in /etc/ssh/sshd_config.d/*.conf; do
        if [ -f "$config_file" ]; then
            echo "处理配置文件: $config_file"
            # 注释掉可能冲突的设置
            sudo sed -i 's/^PasswordAuthentication no/# PasswordAuthentication no # Disabled by script/' "$config_file"
            sudo sed -i 's/^PermitRootLogin no/# PermitRootLogin no # Disabled by script/' "$config_file"
            sudo sed -i 's/^PermitRootLogin prohibit-password/# PermitRootLogin prohibit-password # Disabled by script/' "$config_file"
        fi
    done
    
    # 创建一个优先级更高的配置文件
    cat << 'CONFIG' | sudo tee /etc/ssh/sshd_config.d/99-enable-password-auth.conf
# High priority configuration to enable password authentication
# This file overrides other configurations
PermitRootLogin yes
PasswordAuthentication yes
CONFIG
    echo "✅ Cloud配置文件处理完成"
fi

# 确保PAM配置正确
echo "步骤5: 检查PAM配置..."
if [ -f /etc/pam.d/sshd ]; then
    # 确保PAM没有禁用密码认证
    if ! grep -q "auth.*pam_unix.so" /etc/pam.d/sshd; then
        echo "auth required pam_unix.so" | sudo tee -a /etc/pam.d/sshd
    fi
    echo "✅ PAM配置检查完成"
fi

# 设置正确的权限
echo "步骤6: 设置文件权限..."
sudo chmod 600 /etc/ssh/sshd_config
sudo chmod -R 600 /etc/ssh/sshd_config.d/*.conf 2>/dev/null || true

# 验证配置语法
echo "步骤7: 验证SSH配置语法..."
if sudo sshd -t; then
    echo "✅ SSH配置语法验证通过"
else
    echo "❌ SSH配置语法错误，恢复备份"
    sudo mv /etc/ssh/sshd_config.backup.$timestamp /etc/ssh/sshd_config
    exit 1
fi

# 重启SSH服务
echo "步骤8: 重启SSH服务..."
if sudo systemctl restart ssh 2>/dev/null || sudo systemctl restart sshd 2>/dev/null || sudo service ssh restart 2>/dev/null || sudo service sshd restart 2>/dev/null; then
    echo "✅ SSH服务重启成功"
else
    echo "❌ SSH服务重启失败"
    exit 1
fi

# 等待服务完全启动
sleep 3

# 验证配置是否生效
echo "步骤9: 验证SSH配置..."
auth_status=$(sudo sshd -T | grep -E "passwordauthentication|permitrootlogin" || echo "无法获取配置")
echo "当前SSH认证设置: $auth_status"

# 检查SSH服务状态
if sudo systemctl is-active ssh >/dev/null 2>&1 || sudo systemctl is-active sshd >/dev/null 2>&1; then
    echo "✅ SSH服务运行正常"
else
    echo "❌ SSH服务状态异常"
    exit 1
fi

echo "=== SSH配置修复完成 ==="
echo "✅ 所有配置步骤执行成功"
EOF

# 创建处理单个实例的函数
process_instance() {
    local instance_info="$1"
    local instance_num="$2"
    local total_instances="$3"
    
    IFS=$'\t' read -r instance zone <<< "$instance_info"
    
    if [ -z "$instance" ] || [ -z "$zone" ]; then
        echo "[$instance_num/$total_instances] ❌ 实例信息格式错误: $instance_info"
        return 1
    fi
    
    echo "[$instance_num/$total_instances] 🔧 开始修复实例: $instance (Zone: $zone)"
    
    # 创建实例专用的日志文件
    local log_file="/tmp/ssh_fix_${instance}_${zone//\//_}.log"
    
    {
        echo "=== 实例 $instance 修复日志 ==="
        echo "时间: $(date)"
        echo "区域: $zone"
        echo ""
        
        # 上传修复脚本
        if gcloud compute scp /tmp/fix_ssh_enhanced.sh $instance:~/fix_ssh_enhanced.sh --zone=$zone --quiet 2>&1; then
            echo "✅ 脚本上传成功"
            
            # 执行修复脚本
            if gcloud compute ssh $instance --zone=$zone --command="chmod +x ~/fix_ssh_enhanced.sh && bash ~/fix_ssh_enhanced.sh && rm ~/fix_ssh_enhanced.sh" --quiet 2>&1; then
                echo "✅ 修复脚本执行成功"
                echo "[$instance_num/$total_instances] ✅ 实例 $instance 修复成功"
                return 0
            else
                echo "❌ 修复脚本执行失败"
                echo "[$instance_num/$total_instances] ❌ 实例 $instance 执行修复失败"
                return 1
            fi
        else
            echo "❌ 脚本上传失败"
            echo "[$instance_num/$total_instances] ❌ 实例 $instance 无法连接"
            return 1
        fi
    } > "$log_file" 2>&1
    
    # 显示关键信息
    if [ $? -eq 0 ]; then
        return 0
    else
        echo "📄 错误详情 (查看完整日志: $log_file):"
        tail -5 "$log_file" | sed 's/^/    /'
        return 1
    fi
}

# 创建工作队列和结果统计
declare -a pids=()
declare -a results=()
success_count=0
failed_count=0
total_count=${#instance_list[@]}

echo "🚀 开始并行处理..."
echo ""

# 并行处理实例
for i in "${!instance_list[@]}"; do
    instance_info="${instance_list[$i]}"
    instance_num=$((i + 1))
    
    # 控制并发数
    while [ ${#pids[@]} -ge $MAX_CONCURRENT ]; do
        # 检查已完成的进程
        for j in "${!pids[@]}"; do
            pid=${pids[$j]}
            if ! kill -0 $pid 2>/dev/null; then
                # 进程已完成，获取结果
                wait $pid
                exit_code=$?
                if [ $exit_code -eq 0 ]; then
                    ((success_count++))
                else
                    ((failed_count++))
                fi
                # 从数组中移除已完成的进程
                unset pids[$j]
            fi
        done
        # 重新整理数组索引
        pids=("${pids[@]}")
        sleep 0.5
    done
    
    # 启动新的处理进程
    process_instance "$instance_info" "$instance_num" "$total_count" &
    pids+=($!)
done

# 等待所有剩余进程完成
echo "⏳ 等待所有实例处理完成..."
for pid in "${pids[@]}"; do
    wait $pid
    exit_code=$?
    if [ $exit_code -eq 0 ]; then
        ((success_count++))
    else
        ((failed_count++))
    fi
done

# 清理临时文件
rm -f /tmp/fix_ssh_enhanced.sh
echo ""
echo "🧹 清理临时文件..."

echo ""
echo "=== 批量修复完成 ==="
echo "📊 修复统计："
echo "   - 总实例数: $total_count"
echo "   - ✅ 修复成功: $success_count"
echo "   - ❌ 修复失败: $failed_count"
echo "   - 📈 成功率: $(( total_count > 0 ? success_count * 100 / total_count : 0 ))%"
echo "   - 🔧 处理方式: 多线程并行 (最大并发: $MAX_CONCURRENT)"
echo ""

if [ $success_count -gt 0 ]; then
    echo "🎉 现在您可以使用密码登录成功修复的实例："
    echo "🔐 登录命令: ssh root@<实例IP>"
    echo "🔑 密码: $ROOT_PASSWORD"
    echo ""
    echo "📋 所有实例的外部IP："
    gcloud compute instances list --filter="status=RUNNING" --format="table(name,zone,EXTERNAL_IP)"
    
    echo ""
    echo "🧪 快速测试连接 (请等待几秒让SSH服务完全启动):"
    first_ip=$(gcloud compute instances list --filter="status=RUNNING" --format="value(EXTERNAL_IP)" --limit=1)
    if [ -n "$first_ip" ]; then
        echo "   ssh root@$first_ip"
        echo "   密码: $ROOT_PASSWORD"
        echo ""
        echo "⚠️  如果连接仍然失败，请等待30秒后重试，SSH服务可能需要时间完全重新加载配置"
    fi
    
    echo ""
    echo "🔍 故障排除："
    echo "   - 如果仍然无法连接，日志文件位于: /tmp/ssh_fix_*.log"
    echo "   - 手动检查配置: gcloud compute ssh <实例名> --zone=<区域> --command='sudo sshd -T | grep -E \"passwordauth|permitroot\"'"
    echo "   - 重启实例: gcloud compute instances reset <实例名> --zone=<区域>"
else
    echo "❌ 没有成功修复任何实例，请检查错误信息"
    echo "💡 常见问题："
    echo "   - 实例可能没有外部IP"
    echo "   - 防火墙可能阻止了SSH连接"
    echo "   - 实例可能还在启动中"
    echo "   - 查看详细日志: /tmp/ssh_fix_*.log"
fi

echo ""
echo "💡 改进要点："
echo "   ✅ 增强的SSH配置处理（处理多个配置文件）"
echo "   ✅ 多线程并行处理（提升 ${MAX_CONCURRENT}x 速度）"
echo "   ✅ 详细的配置验证和错误检查"
echo "   ✅ 完整的备份和恢复机制"
echo "   ✅ PAM配置检查和修复"
fi
